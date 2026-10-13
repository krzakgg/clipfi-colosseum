"""Session endpoints: registration, password login, the MFA second step, refresh, logout."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from typing import cast as typing_cast

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import CursorResult, func, or_, select, update
from sqlalchemy.sql import false as sqlalchemy_false
from sqlalchemy.ext.asyncio import AsyncSession

from waggi_auth import rate_limit
from waggi_auth.config import settings
from waggi_auth.dependencies import get_db
from waggi_auth.models import RefreshToken, User
from waggi_auth.schemas import (
    LoginMfaRequest,
    LoginRequest,
    MessageResponse,
    MfaRequiredResponse,
    RefreshRequest,
    RegisterRequest,
    SetupRequiredResponse,
    TokenResponse,
)
from waggi_auth.security.signing import create_mfa_token, hash_refresh_token, verify_mfa_token
from waggi_auth.security.totp import match_backup_code, verify_totp_for_user
from waggi_auth.stores import mfa
from waggi_auth.tokens import issue_tokens, issue_tokens_or_setup
from waggi_shared.errors import APIError, ConflictError, UnauthorizedError, ValidationError
from waggi_shared.password_policy import password_policy_violation
from waggi_shared.passwords import hash_password, needs_rehash, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """A real argon2 hash of a random string, for timing-equalized rejects.

    Every login rejection path (unknown email, inactive account, SSO-only
    user, wrong password) verifies against this when there is no real hash to
    check, making the response time indistinguishable across paths
    (anti-enumeration).
    """
    return hash_password(secrets.token_urlsafe(24))


# --- Login / refresh / logout --------------------------------------------


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Public self-signup (waggi: companies and creators register themselves).

    waggi's frontend registers accounts directly — the password policy and
    per-IP rate limiting apply.
    """
    await rate_limit.enforce_register(_client_ip(request))
    email = body.email.lower()
    username = body.username.lower() if body.username else None

    username_clause = User.username == username if username is not None else sqlalchemy_false()
    existing = (
        await db.execute(select(User).where(or_(User.email == email, username_clause)))
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError(detail="Account already exists", code="account_exists")

    violation = password_policy_violation(
        body.password,
        email=email,
        full_name=body.full_name,
        min_length=settings.password_min_length,
        min_uppercase=settings.password_min_uppercase,
        min_lowercase=settings.password_min_lowercase,
        min_digit=settings.password_min_digit,
        min_symbol=settings.password_min_symbol,
    )
    if violation:
        raise ValidationError(detail="Password does not meet the policy", code=violation)

    user = User(
        email=email,
        username=username,
        full_name=body.full_name,
        phone=body.phone,
        account_type=body.account_type,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return await issue_tokens(user, db)


@router.post(
    "/login",
    response_model=TokenResponse | MfaRequiredResponse | SetupRequiredResponse,
    status_code=status.HTTP_200_OK,
)
async def login(
    body: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse | MfaRequiredResponse | SetupRequiredResponse:
    # creators may log in with email OR username.
    identifier = body.email
    if "@" in identifier:
        user = (await db.execute(select(User).where(User.email == identifier))).scalar_one_or_none()
    else:
        user = (
            await db.execute(select(User).where(or_(User.email == identifier, User.username == identifier)))
        ).scalar_one_or_none()
    await rate_limit.enforce_login(identifier.lower(), _client_ip(request))
    # Exactly ONE argon2 verify in every path — unknown email, inactive
    # account, SSO-only user (no stored hash) and wrong password all burn the
    # same argon2 work, so response time reveals which reason did NOT apply
    # (anti-enumeration; an inactive account used to reject before hashing).
    stored_hash = user.password_hash if user is not None else None
    password_ok = verify_password(body.password, stored_hash or _dummy_hash())
    if user is None or not user.is_active or not password_ok:
        raise UnauthorizedError(detail="Invalid email or password", code="invalid_credentials")
    # Transparent upgrade: if the stored hash uses outdated parameters
    # (passlib-era or older argon2-cffi defaults), re-hash now — the password
    # is already proven. Runs before the TOTP branch so the upgrade is not
    # deferred to the second login step.
    if stored_hash is not None and needs_rehash(stored_hash):
        user.password_hash = hash_password(body.password)
        await db.commit()
    # If TOTP is enabled, issue an MFA challenge token instead of session tokens.
    # The password-setup gate (issue_tokens_or_setup) applies at the MFA step —
    # knowing only the shared temp password must not be enough to reach the
    # password change.
    if user.totp_enabled:
        mfa_token, ttl = create_mfa_token(user_id=user.id)
        return MfaRequiredResponse(mfa_token=mfa_token, expires_in=ttl)
    return await issue_tokens_or_setup(user, db)


@router.post(
    "/login/mfa",
    response_model=TokenResponse | SetupRequiredResponse,
    status_code=status.HTTP_200_OK,
)
async def login_mfa(
    body: LoginMfaRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse | SetupRequiredResponse:
    """Second login step: verify the MFA token + a TOTP code OR a backup code."""
    await rate_limit.enforce_login_mfa(_client_ip(request))
    mfa_token_data = verify_mfa_token(body.mfa_token)
    if mfa_token_data is None:
        raise UnauthorizedError(detail="Invalid or expired MFA token", code="mfa_token_invalid")
    user = await db.get(User, mfa_token_data.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError(detail="User not found or inactive", code="account_inactive")

    # Validate the second factor first (a typo must NOT burn the mfa token).
    # match_backup_code returns the STORED hash (peppered or legacy) so the
    # redemption UPDATE below removes the right row entry either way.
    stored_backup_hash: str | None = None
    if body.backup_code:
        stored_backup_hash = match_backup_code(user.totp_backup_codes_hashed, body.backup_code)
        if stored_backup_hash is None:
            raise UnauthorizedError(detail="Invalid backup code", code="backup_code_invalid")
    elif body.code:
        if not verify_totp_for_user(user, body.code):
            raise UnauthorizedError(detail="Invalid TOTP code", code="totp_code_invalid")
    else:
        raise ValidationError(detail="Provide either a TOTP code or a backup code", code="second_factor_required")

    # Single-use gates (atomic SET NX): a replayed mfa token or a reused TOTP
    # code is rejected even though its credentials are still valid. These are
    # PER-TOKEN gates — they do not by themselves stop two DIFFERENT valid mfa
    # tokens from redeeming the SAME backup code concurrently (that is the
    # conditional UPDATE below).
    try:
        if not await mfa.consume_mfa_jti(mfa_token_data.jti):
            raise UnauthorizedError(detail="MFA token already used", code="mfa_token_reused")
        if body.code and not await mfa.consume_totp_code(user.id, body.code):
            raise UnauthorizedError(detail="TOTP code already used", code="totp_code_reused")
    except aioredis.RedisError as exc:
        raise APIError(
            "MFA store unavailable; try again shortly",
            code="store_unavailable",
            status_code=503,
            title="Service Unavailable",
        ) from exc

    # Redeem the one-time backup code (the TOTP path redeems via Redis above).
    # Conditional UPDATE — the refresh-rotation pattern: the code is removed
    # only while it is still present, so of two concurrent requests spending
    # the same code (with different, valid mfa tokens) exactly one wins; the
    # loser gets a 401 instead of a second session.
    if stored_backup_hash is not None:
        redeem = typing_cast(
            "CursorResult[Any]",
            await db.execute(
                update(User)
                .where(
                    User.id == user.id,
                    # `codes @> ARRAY[<hash>]` — true while the code is present
                    User.totp_backup_codes_hashed.contains([stored_backup_hash]),
                )
                .values(totp_backup_codes_hashed=func.array_remove(User.totp_backup_codes_hashed, stored_backup_hash))
                .execution_options(synchronize_session=False)
            ),
        )
        if redeem.rowcount != 1:
            raise UnauthorizedError(detail="Invalid backup code", code="backup_code_invalid")
    # Second factor cleared — the setup gate (if flagged) applies now.
    return await issue_tokens_or_setup(user, db)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    token_row = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(body.refresh_token)))
    ).scalar_one_or_none()

    if token_row is None:
        raise UnauthorizedError(detail="Invalid refresh token", code="refresh_token_invalid")

    user = await db.get(User, token_row.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError(detail="User not found or inactive", code="account_inactive")
    if token_row.revoked_at is not None:
        # A revoked token being presented again. If it was revoked BY
        # ROTATION (a replacement exists), someone other than the current
        # holder still has a copy — the theft signal (L7): revoke the ENTIRE
        # family (this token and every descendant), forcing re-login
        # everywhere. Logout revocations have no replacement — a stale client
        # replaying those gets a plain 401 and siblings stay alive.
        if token_row.replaced_by_id is not None:
            await db.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.family_id == token_row.family_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=_utcnow())
                .execution_options(synchronize_session=False)
            )
            await db.commit()
        raise UnauthorizedError(detail="Refresh token expired or revoked", code="refresh_token_revoked")
    if token_row.expires_at < _utcnow():
        raise UnauthorizedError(detail="Refresh token expired or revoked", code="refresh_token_revoked")
    if token_row.issued_at < user.tokens_invalid_before:
        raise UnauthorizedError(detail="Refresh token invalidated by password change", code="refresh_token_invalidated")

    # Rotate WITHIN the family: issue_tokens inserts the replacement and
    # revokes this token (recording the replacement) in one atomic commit.
    # A concurrent refresh of the same token loses the conditional UPDATE
    # inside and gets a 401 — exactly one winner, no double-rotation window.
    return await issue_tokens(user, db, family_id=token_row.family_id, replaced_token_id=token_row.id)


@router.post("/logout", response_model=MessageResponse)
async def logout(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    token_row = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(body.refresh_token)))
    ).scalar_one_or_none()
    if token_row is not None and token_row.revoked_at is None:
        token_row.revoked_at = _utcnow()
        await db.commit()
    return MessageResponse(message="Logged out")


__all__ = ["router"]
