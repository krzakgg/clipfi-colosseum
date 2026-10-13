"""Passkey (WebAuthn) endpoints: registration + passwordless login ceremonies.

Flow:
- Registration (authed): begin -> browser ceremony -> finish (credential stored).
- Login (public): usernameless — discoverable/resident credentials, so the user
  is resolved from the presented credential at finish, not at begin.
- 2FA policy: a user-verified passkey ceremony is itself two-factor (credential
  possession + biometric/PIN user verification), so finish issues session
  tokens directly and skips TOTP. The MFA challenge remains as a defense-in-depth
  fallback for ceremonies that did not verify the user — UV is REQUIRED today,
  so the fallback is unreachable unless that is ever relaxed.

Challenges are single-use and kept in Redis (`waggi_auth.stores.challenges`,
TTL 5 min), so any worker can finish a ceremony another worker started.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, options_to_json_dict
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidJSONStructure,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from waggi_auth import rate_limit
from waggi_auth.config import settings
from waggi_auth.dependencies import get_current_user, get_db
from waggi_auth.models import User, UserPasskey
from waggi_auth.schemas import (
    MessageResponse,
    MfaRequiredResponse,
    PasskeyBeginResponse,
    PasskeyLoginFinishRequest,
    PasskeyOut,
    PasskeyRegisterFinishRequest,
    PasskeyRenameRequest,
    SetupRequiredResponse,
    TokenResponse,
)
from waggi_auth.security.signing import create_mfa_token
from waggi_auth.stores import challenges
from waggi_auth.tokens import issue_tokens_or_setup
from waggi_shared.errors import (
    APIError,
    ConflictError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from waggi_shared.passwords import verify_password

router = APIRouter(prefix="/api/v1/auth/passkeys", tags=["passkeys"])

_CHALLENGE_TTL = timedelta(minutes=5)


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _resolve_rp(request: Request) -> tuple[str, list[str]]:
    """Pick the WebAuthn rp_id + allowed origins for this ceremony.

    The frontend can be served on several origins at once (localhost on the
    desktop, an ngrok tunnel domain on the phone). The ceremony's rp_id is
    derived from the request's Origin header — but ONLY if that host is
    explicitly configured (default rp_id or WEBAUTHN_EXTRA_RP_HOSTS); anything
    else falls back to the default instead of being trusted.
    """
    origin = request.headers.get("origin", "")
    host = urlsplit(origin).hostname or ""
    known = settings.known_rp_hosts()
    if host and host in known:
        if host == settings.webauthn_rp_id:
            return settings.webauthn_rp_id, settings.webauthn_origins_list
        return host, [f"https://{host}"]
    return settings.webauthn_rp_id, settings.webauthn_origins_list


def _resolve_rp_for_rp_id(rp_id: str) -> tuple[str, list[str]]:
    """Map a stored ceremony rp_id back to its allowed origins (finish step)."""
    if rp_id == settings.webauthn_rp_id:
        return settings.webauthn_rp_id, settings.webauthn_origins_list
    return rp_id, [f"https://{rp_id}"]


async def _store_challenge(challenge: bytes, user_id: uuid.UUID | None, kind: str, rp_id: str) -> str:
    """Persist the ceremony challenge in Redis; return its opaque handle."""
    handle = secrets.token_urlsafe(32)
    try:
        await challenges.store(
            handle,
            challenges.PendingChallenge(kind=kind, user_id=user_id, challenge=challenge, rp_id=rp_id),
            _CHALLENGE_TTL,
        )
    except aioredis.RedisError as exc:
        raise APIError(
            "Challenge store unavailable; try again shortly",
            code="store_unavailable",
            status_code=503,
            title="Service Unavailable",
        ) from exc
    return handle


async def _pop_challenge(handle: str, kind: str, user_id: uuid.UUID | None) -> challenges.PendingChallenge | None:
    """Atomically consume a ceremony challenge (single-use via GETDEL)."""
    try:
        return await challenges.pop(handle, kind, user_id)
    except aioredis.RedisError as exc:
        raise APIError(
            "Challenge store unavailable; try again shortly",
            code="store_unavailable",
            status_code=503,
            title="Service Unavailable",
        ) from exc


def _selection_criteria() -> AuthenticatorSelectionCriteria:
    """Resident key preferred -> usernameless login works; UV required."""
    return AuthenticatorSelectionCriteria(
        resident_key=ResidentKeyRequirement.PREFERRED,
        user_verification=UserVerificationRequirement.REQUIRED,
    )


def _parse_transports(credential: dict[str, Any]) -> list[str]:
    raw = credential.get("response", {}).get("transports")
    if not isinstance(raw, list):
        return []
    return [str(t) for t in raw if isinstance(t, str)]


def _parse_attachment(credential: dict[str, Any]) -> str | None:
    """The browser's attachment report, or None when absent/invalid.

    py_webauthn 3.x already rejects invalid attachment STRINGS during JSON
    parsing; this normalizer additionally guards non-string values.
    """
    raw = credential.get("authenticatorAttachment")
    return raw if raw in ("platform", "cross-platform") else None


_ZERO_AAGUID = "00000000-0000-0000-0000-000000000000"


def _normalize_aaguid(raw: str | None) -> str | None:
    """Normalize a verified AAGUID for storage; None when unidentified.

    The AAGUID is stored as a raw fact — mapping it to a provider brand name
    is a FRONTEND display concern (frontend/src/lib/aaguids.ts, kept in sync
    from the community list by scripts/sync_aaguids.py).
    """
    if not raw:
        return None
    value = raw.strip().lower()
    return None if value == _ZERO_AAGUID else value


# --- Registration (authed) ------------------------------------------------


@router.post("/register/begin", response_model=PasskeyBeginResponse)
async def register_begin(
    request: Request,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PasskeyBeginResponse:
    # Writes a Redis challenge per call (authed, but cap abuse all the same).
    await rate_limit.enforce_passkey_begin(_client_ip(request))
    rp_id, _origins = _resolve_rp(request)
    existing = (await db.execute(select(UserPasskey).where(UserPasskey.user_id == current.id))).scalars().all()
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=settings.webauthn_rp_name,
        user_id=current.id.bytes,
        user_name=current.email,
        user_display_name=current.full_name,
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(pk.credential_id)) for pk in existing],
        authenticator_selection=_selection_criteria(),
    )
    handle = await _store_challenge(options.challenge, current.id, "register", rp_id)
    return PasskeyBeginResponse(handle=handle, options=options_to_json_dict(options))


@router.post("/register/finish", response_model=PasskeyOut, status_code=status.HTTP_201_CREATED)
async def register_finish(
    body: PasskeyRegisterFinishRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PasskeyOut:
    # Step-up (password), BEFORE popping the challenge: registering an
    # attacker's passkey would be a persistent backdoor (passkey login skips
    # TOTP by design — a UV ceremony is itself 2FA). Checking the password
    # first means a typo does not burn the single-use challenge, so the client
    # can retry without re-running the browser ceremony.
    await rate_limit.enforce_step_up(current.id)
    if not verify_password(body.password, current.password_hash):
        raise ValidationError(detail="Current password is incorrect", code="password_incorrect")
    entry = await _pop_challenge(body.handle, "register", current.id)
    if entry is None:
        raise UnauthorizedError(detail="Unknown or expired registration challenge", code="challenge_invalid")
    _, origins = _resolve_rp_for_rp_id(entry.rp_id)
    try:
        verified = verify_registration_response(
            credential=body.credential,
            expected_challenge=entry.challenge,
            expected_origin=origins,
            expected_rp_id=entry.rp_id,
            require_user_verification=True,
        )
    except (InvalidRegistrationResponse, InvalidJSONStructure) as exc:
        # InvalidJSONStructure = malformed credential JSON caught at parse
        # time (py_webauthn 3.x strict parsing), e.g. a bogus attachment value.
        raise ValidationError(detail=f"Passkey registration failed: {exc}", code="passkey_registration_failed") from exc

    passkey = UserPasskey(
        user_id=current.id,
        credential_id=bytes_to_base64url(verified.credential_id),
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        transports=_parse_transports(body.credential),
        aaguid=_normalize_aaguid(verified.aaguid),
        attachment=_parse_attachment(body.credential),
        backed_up=verified.credential_backed_up,
        nickname=body.nickname,
    )
    db.add(passkey)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(detail="This passkey is already registered", code="passkey_already_registered") from exc
    await db.refresh(passkey)
    return PasskeyOut.model_validate(passkey)


# --- Login (public, usernameless) -----------------------------------------


@router.post("/login/begin", response_model=PasskeyBeginResponse)
async def login_begin(request: Request) -> PasskeyBeginResponse:
    # Unauthenticated + writes a Redis challenge per call: cap per IP.
    await rate_limit.enforce_passkey_begin(_client_ip(request))
    # No allow_credentials: the authenticator offers discoverable credentials.
    rp_id, _origins = _resolve_rp(request)
    options = generate_authentication_options(
        rp_id=rp_id,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    handle = await _store_challenge(options.challenge, None, "login", rp_id)
    return PasskeyBeginResponse(handle=handle, options=options_to_json_dict(options))


@router.post("/login/finish", response_model=TokenResponse | MfaRequiredResponse | SetupRequiredResponse)
async def login_finish(
    body: PasskeyLoginFinishRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse | MfaRequiredResponse | SetupRequiredResponse:
    entry = await _pop_challenge(body.handle, "login", None)
    if entry is None:
        raise UnauthorizedError(detail="Unknown or expired login challenge", code="challenge_invalid")

    credential_id = body.credential.get("id")
    if not isinstance(credential_id, str) or not credential_id:
        raise ValidationError(detail="Malformed credential", code="malformed_credential")
    passkey = (await db.execute(select(UserPasskey).where(UserPasskey.credential_id == credential_id))).scalar_one_or_none()
    if passkey is None:
        raise UnauthorizedError(detail="Unknown passkey", code="passkey_not_found")

    user = await db.get(User, passkey.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError(detail="User not found or inactive", code="account_inactive")

    _, origins = _resolve_rp_for_rp_id(entry.rp_id)
    try:
        verified = verify_authentication_response(
            credential=body.credential,
            expected_challenge=entry.challenge,
            expected_origin=origins,
            expected_rp_id=entry.rp_id,
            credential_public_key=passkey.public_key,
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=True,
        )
    except (InvalidAuthenticationResponse, InvalidJSONStructure) as exc:
        # Parse-time (InvalidJSONStructure) and verification failures both
        # reject the login — never a 500 for a malformed client payload.
        raise UnauthorizedError(detail="Passkey verification failed", code="passkey_verification_failed") from exc

    passkey.sign_count = verified.new_sign_count
    passkey.last_used_at = _utcnow()
    await db.commit()

    # A user-verified ceremony is already two-factor: credential possession +
    # user verification (biometric/PIN). Challenge TOTP only when the ceremony
    # ran without UV — UV is REQUIRED today, so this is defense in depth in case
    # that is ever relaxed to "preferred".
    if user.totp_enabled and not verified.user_verified:
        mfa_token, ttl = create_mfa_token(user_id=user.id)
        return MfaRequiredResponse(mfa_token=mfa_token, expires_in=ttl)
    # A user-verified ceremony IS the second factor — the setup gate applies now.
    return await issue_tokens_or_setup(user, db)


# --- Management (authed) ---------------------------------------------------


async def _get_own_passkey(db: AsyncSession, passkey_id: uuid.UUID, user: User) -> UserPasskey:
    passkey = await db.get(UserPasskey, passkey_id)
    # 404 (not 403) for foreign passkeys: do not leak their existence.
    if passkey is None or passkey.user_id != user.id:
        raise NotFoundError(detail="Passkey not found", code="passkey_not_found")
    return passkey


@router.get("", response_model=list[PasskeyOut])
async def list_passkeys(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PasskeyOut]:
    rows = (
        (await db.execute(select(UserPasskey).where(UserPasskey.user_id == current.id).order_by(UserPasskey.created_at.desc())))
        .scalars()
        .all()
    )
    return [PasskeyOut.model_validate(pk) for pk in rows]


@router.patch("/{passkey_id}", response_model=PasskeyOut)
async def rename_passkey(
    passkey_id: uuid.UUID,
    body: PasskeyRenameRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PasskeyOut:
    passkey = await _get_own_passkey(db, passkey_id, current)
    passkey.nickname = body.nickname
    await db.commit()
    await db.refresh(passkey)
    return PasskeyOut.model_validate(passkey)


@router.delete("/{passkey_id}", response_model=MessageResponse)
async def delete_passkey(
    passkey_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    passkey = await _get_own_passkey(db, passkey_id, current)
    await db.delete(passkey)
    await db.commit()
    return MessageResponse(message="Passkey deleted")


__all__ = ["router"]
