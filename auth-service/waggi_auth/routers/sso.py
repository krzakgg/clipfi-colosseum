"""SSO endpoints: OAuth login flow (Google/Apple) + multi-identity link management.

Login flow (authorization code, backend callback):
- POST /authorize  -> { authorize_url } — the SPA sends the browser there.
- GET|POST /callback <- provider redirect; exchanges the code, resolves the
  user (existing link, or auto-link on verified email), then redirects the
  browser to the frontend finish route with a one-time handle.
- POST /complete   -> TokenResponse | MfaRequiredResponse (handle exchange).

Link management (authed): list/link/unlink identities on `user_sso_links`.
Linking runs a full OAuth ceremony (POST /link/{provider} -> provider ->
shared callback) that binds the identity ONLY when the provider's verified
email equals the account email. Unlinking is plain (own-link check only):
every account has a password, so no last-credential lockout guard is needed
(removed by decision Aug 20 2026).
"""

from __future__ import annotations

import secrets
import uuid
from urllib.parse import quote, urlencode

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from waggi_auth import rate_limit
from waggi_auth.config import settings
from waggi_auth.dependencies import get_current_user, get_db
from waggi_auth.models import User, UserSsoLink
from waggi_auth.providers import VerifiedIdentity, get_provider_client, provider_status
from waggi_auth.schemas import (
    MfaRequiredResponse,
    SetupRequiredResponse,
    SsoAuthorizeRequest,
    SsoAuthorizeResponse,
    SsoCompleteRequest,
    SsoLinkOut,
    SsoProviderOut,
    TokenResponse,
)
from waggi_auth.security.signing import create_mfa_token
from waggi_auth.stores import sso_states
from waggi_auth.tokens import issue_tokens_or_setup
from waggi_shared.errors import (
    APIError,
    NotFoundError,
    UnauthorizedError,
)

router = APIRouter(prefix="/api/v1/auth/sso", tags=["sso"])


# --- Login: provider discovery + authorize --------------------------------


@router.get("/providers", response_model=list[SsoProviderOut])
async def list_providers() -> list[SsoProviderOut]:
    return [SsoProviderOut(provider=name, enabled=enabled) for name, enabled in provider_status()]


def _frontend_origin(request: Request) -> str:
    """Origin the browser is actually on (trusted hosts only; else the default)."""
    origin = request.headers.get("origin", "")
    if origin and origin.rstrip("/") in settings.allowed_frontend_origins():
        return origin.rstrip("/")
    return settings.frontend_url.rstrip("/")


def _api_origin(origin: str) -> str:
    """Origin hosting THIS API. Prod serves the API on its own origin
    (api.waggi.local, API_PUBLIC_URL) while the browser sits on the SPA
    origin; dev leaves it empty and derives it from the frontend origin
    (Vite same-origin proxy). OAuth redirect URIs are built on this."""
    return settings.api_public_url.rstrip("/") if settings.api_public_url else origin


def _error_redirect(origin: str, code: str) -> RedirectResponse:
    url = f"{origin}/login/sso/callback?{urlencode({'error': code})}"
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


@router.post("/{provider}/authorize", response_model=SsoAuthorizeResponse)
async def authorize(
    provider: str,
    body: SsoAuthorizeRequest,
    request: Request,
) -> SsoAuthorizeResponse:
    client_ip = request.client.host if request.client else "unknown"
    await rate_limit.enforce_sso_authorize(client_ip)
    client = get_provider_client(provider)  # 404 unknown / 501 not configured
    origin = _frontend_origin(request)
    # The OAuth redirect_uri must land on the host serving THIS API (prod:
    # api.waggi.local per API_PUBLIC_URL), not the SPA the browser is on.
    redirect_uri = f"{_api_origin(origin)}/api/v1/auth/sso/{provider}/callback"
    return_to = f"{origin}/login/sso/callback"
    # Only same-site frontend paths are honored: must start with "/", must not
    # start with "//" (protocol-relative) and must not contain "\" (browsers
    # treat "/\evil.com" like "//evil.com" — a classic open-redirect bypass).
    if body.redirect and body.redirect.startswith("/") and not body.redirect.startswith("//") and "\\" not in body.redirect:
        sep = "&" if "?" in return_to else "?"
        return_to = f"{return_to}{sep}redirect={quote(body.redirect, safe='/')}"
    nonce = secrets.token_urlsafe(24)
    try:
        state = await sso_states.store_state(
            sso_states.PendingSsoState(provider=provider, nonce=nonce, redirect_uri=redirect_uri, return_to=return_to)
        )
    except aioredis.RedisError as exc:
        raise APIError(
            "Login state store unavailable; try again shortly",
            code="store_unavailable",
            status_code=503,
            title="Service Unavailable",
        ) from exc
    return SsoAuthorizeResponse(authorize_url=client.authorize_url(redirect_uri, state, nonce))


# --- Login: provider callback (backend) -------------------------------------


async def _resolve_user(db: AsyncSession, provider: str, identity: VerifiedIdentity) -> User | None:
    """Find the user for a verified identity: existing link, or auto-link by
    verified email (no JIT account creation — users are admin-precreated)."""
    link = (
        await db.execute(
            select(UserSsoLink).where(
                UserSsoLink.provider == provider,
                UserSsoLink.provider_subject == identity.subject,
            )
        )
    ).scalar_one_or_none()
    if link is not None:
        return await db.get(User, link.user_id)

    if identity.email is None or not identity.email_verified:
        return None
    user = (await db.execute(select(User).where(User.email == identity.email))).scalar_one_or_none()
    if user is None:
        return None
    # Auto-link on first login. A concurrent insert races the unique constraint;
    # re-query (the winner's link points at the same email's user).
    db.add(UserSsoLink(user_id=user.id, provider=provider, provider_subject=identity.subject))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        link = (
            await db.execute(
                select(UserSsoLink).where(
                    UserSsoLink.provider == provider,
                    UserSsoLink.provider_subject == identity.subject,
                )
            )
        ).scalar_one_or_none()
        if link is None:
            return None
        return await db.get(User, link.user_id)
    return user


def _link_redirect(return_to: str, *, provider: str | None = None, error: str | None = None) -> RedirectResponse:
    """Redirect back to the account page carrying the link outcome."""
    params: dict[str, str] = {}
    if provider is not None:
        params["sso_link"] = provider
    if error is not None:
        params["sso_link_error"] = error
    sep = "&" if "?" in return_to else "?"
    return RedirectResponse(f"{return_to}{sep}{urlencode(params)}", status_code=status.HTTP_302_FOUND)


async def _finish_link(
    db: AsyncSession, entry: sso_states.PendingSsoState, provider: str, identity: VerifiedIdentity
) -> RedirectResponse:
    """Complete an identity-link ceremony started by POST /link/{provider}.

    The `user_sso_links` row is inserted ONLY when the provider's VERIFIED
    email equals the initiating account's email (case-insensitive;
    `users.email` is citext + unique). A provider identity with that verified
    email can therefore only ever belong to this account — binding someone
    ELSE'S Google/Apple identity to it is impossible, which is what makes
    client-supplied subjects (the old 501 takeover vector) unnecessary here.
    """
    if entry.user_id is None:  # corrupt/foreign state: cannot attribute the link
        return _link_redirect(entry.return_to, error="state")
    user = await db.get(User, entry.user_id)
    if user is None or not user.is_active:
        return _link_redirect(entry.return_to, error="no_account")
    if identity.email is None or not identity.email_verified:
        return _link_redirect(entry.return_to, error="email_unverified")
    if identity.email.lower() != user.email.lower():
        return _link_redirect(entry.return_to, error="email_mismatch")

    existing = (
        await db.execute(
            select(UserSsoLink).where(
                UserSsoLink.provider == provider,
                UserSsoLink.provider_subject == identity.subject,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.user_id == user.id:
            return _link_redirect(entry.return_to, provider=provider)  # idempotent re-link
        return _link_redirect(entry.return_to, error="already_linked")

    db.add(UserSsoLink(user_id=user.id, provider=provider, provider_subject=identity.subject))
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent ceremony inserted the same (provider, subject) first.
        await db.rollback()
        winner = (
            await db.execute(
                select(UserSsoLink).where(
                    UserSsoLink.provider == provider,
                    UserSsoLink.provider_subject == identity.subject,
                )
            )
        ).scalar_one_or_none()
        # Compare against entry.user_id (a plain value): the rollback above
        # expired the identity map, and touching user.id would lazy-refresh
        # synchronously -> MissingGreenlet (async sessions cannot do sync IO).
        if winner is not None and winner.user_id == entry.user_id:
            return _link_redirect(entry.return_to, provider=provider)
        return _link_redirect(entry.return_to, error="already_linked")
    return _link_redirect(entry.return_to, provider=provider)


@router.get("/{provider}/callback", response_class=RedirectResponse)
@router.post("/{provider}/callback", response_class=RedirectResponse)
async def provider_callback(
    provider: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Provider -> backend redirect (GET query params; Apple posts a form)."""
    if request.method == "POST":
        # Apple's form-post payload is tiny (~1 KB). Cap it before parsing so
        # an oversized body can't burn memory/CPU in multipart handling.
        content_length = request.headers.get("content-length", "")
        if content_length.isdigit() and int(content_length) > 65536:
            raise APIError(
                "Callback payload too large",
                code="payload_too_large",
                status_code=413,
                title="Payload Too Large",
            )
        form = await request.form()
        code = str(form.get("code", ""))
        state = str(form.get("state", ""))
        error = str(form.get("error", ""))
    else:
        code = request.query_params.get("code", "")
        state = request.query_params.get("state", "")
        error = request.query_params.get("error", "")

    fallback_origin = _frontend_origin(request)
    if error or not code or not state:
        return _error_redirect(fallback_origin, "denied" if error else "invalid_request")
    try:
        client = get_provider_client(provider)
    except APIError:
        return _error_redirect(fallback_origin, "config")

    try:
        entry = await sso_states.pop_state(state)
    except aioredis.RedisError as exc:
        raise APIError(
            "Login state store unavailable; try again shortly",
            code="store_unavailable",
            status_code=503,
            title="Service Unavailable",
        ) from exc
    if entry is None or entry.provider != provider:
        return _error_redirect(fallback_origin, "state")

    try:
        identity = await client.exchange_code(code, entry.redirect_uri, entry.nonce)
    except APIError:
        return _error_redirect(fallback_origin, "denied")

    if entry.purpose == "link":
        return await _finish_link(db, entry, provider, identity)

    user = await _resolve_user(db, provider, identity)
    if user is None or not user.is_active:
        # Unknown identity AND no verified-email match (or inactive account).
        return _error_redirect(fallback_origin, "no_account")

    try:
        handle = await sso_states.store_login(user.id)
    except aioredis.RedisError as exc:
        raise APIError(
            "Login state store unavailable; try again shortly",
            code="store_unavailable",
            status_code=503,
            title="Service Unavailable",
        ) from exc
    sep = "&" if "?" in entry.return_to else "?"
    return RedirectResponse(f"{entry.return_to}{sep}handle={handle}", status_code=status.HTTP_302_FOUND)


@router.post("/complete", response_model=TokenResponse | MfaRequiredResponse | SetupRequiredResponse)
async def complete_login(
    body: SsoCompleteRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse | MfaRequiredResponse | SetupRequiredResponse:
    """Finish an SSO login: exchange the one-time handle for session tokens
    (or an MFA challenge when the user has TOTP enabled)."""
    try:
        user_id = await sso_states.pop_login(body.handle)
    except aioredis.RedisError as exc:
        raise APIError(
            "Login state store unavailable; try again shortly",
            status_code=503,
            title="Service Unavailable",
        ) from exc
    if user_id is None:
        raise UnauthorizedError(detail="Unknown or expired login handle", code="sso_handle_invalid")

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError(detail="User not found or inactive", code="account_inactive")

    # OAuth proves email control only — not a second factor. TOTP-enabled
    # users get the same MFA step as password login; the password-setup gate
    # applies after it (at /login/mfa) or right here when TOTP is off.
    if user.totp_enabled:
        mfa_token, ttl = create_mfa_token(user_id=user.id)
        return MfaRequiredResponse(mfa_token=mfa_token, expires_in=ttl)
    return await issue_tokens_or_setup(user, db)


@router.get("/identities", response_model=list[SsoLinkOut])
async def list_sso_identities(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SsoLinkOut]:
    rows = (await db.execute(select(UserSsoLink).where(UserSsoLink.user_id == current.id))).scalars().all()
    return [SsoLinkOut.model_validate(r) for r in rows]


@router.post("/link/{provider}", response_model=SsoAuthorizeResponse)
async def begin_link(
    provider: str,
    request: Request,
    current: User = Depends(get_current_user),
) -> SsoAuthorizeResponse:
    """Start linking `provider` to the CURRENT account (authed).

    Returns the provider consent URL. The OAuth `state` stored alongside it is
    bound server-side to `current.id`; the shared provider callback completes
    the link only when the provider's VERIFIED email equals the account email
    (`_finish_link`) — no client-supplied identity data is ever trusted, so
    binding someone else's provider account to this one is not possible.
    """
    client = get_provider_client(provider)  # 404 unknown / 501 not configured
    origin = _frontend_origin(request)
    # Same rule as the login authorize flow: the redirect_uri lands on the
    # host serving THIS API (API_PUBLIC_URL in prod), not the SPA origin.
    redirect_uri = f"{_api_origin(origin)}/api/v1/auth/sso/{provider}/callback"
    return_to = f"{origin}/account"
    nonce = secrets.token_urlsafe(24)
    try:
        state = await sso_states.store_state(
            sso_states.PendingSsoState(
                provider=provider,
                nonce=nonce,
                redirect_uri=redirect_uri,
                return_to=return_to,
                purpose="link",
                user_id=current.id,
            )
        )
    except aioredis.RedisError as exc:
        raise APIError(
            "Login state store unavailable; try again shortly",
            code="store_unavailable",
            status_code=503,
            title="Service Unavailable",
        ) from exc
    return SsoAuthorizeResponse(authorize_url=client.authorize_url(redirect_uri, state, nonce))


@router.delete("/link/{identity_id}", response_model=SsoLinkOut)
async def unlink_sso(
    identity_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SsoLinkOut:
    link = await db.get(UserSsoLink, identity_id)
    if link is None or link.user_id != current.id:
        raise NotFoundError(detail="Linked identity not found", code="sso_identity_not_found")
    out = SsoLinkOut.model_validate(link)
    await db.delete(link)
    await db.commit()
    return out


__all__ = ["router"]
