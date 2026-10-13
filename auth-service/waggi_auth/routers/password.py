"""Password lifecycle endpoints: forced first-login setup, self-service change,
and the (prepared) email reset flow.

The email reset is admin-independent and always returns 202 on request
(no email enumeration). v1 sends via `LoggingEmailSender` (token logged, not
emailed) — swap the implementation to go live, no schema/endpoint changes.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from typing import cast as typing_cast

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from waggi_auth import rate_limit
from waggi_auth.config import settings
from waggi_auth.dependencies import get_current_user, get_db
from waggi_auth.models import PasswordReset, User
from waggi_auth.schemas import (
    ChangePasswordRequest,
    MessageResponse,
    PasswordPolicyOut,
    PasswordResetConfirm,
    PasswordResetRequest,
    SetupPasswordRequest,
    TokenResponse,
)
from waggi_auth.security.signing import verify_setup_token
from waggi_auth.stores import mfa
from waggi_auth.tokens import issue_tokens
from waggi_shared.email import LoggingEmailSender
from waggi_shared.errors import APIError, ConflictError, UnauthorizedError, ValidationError
from waggi_shared.password_policy import PASSWORD_MAX_LENGTH
from waggi_shared.passwords import hash_password, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


_POLICY_DETAIL = {
    "password_character_requirements": "Password does not meet the character requirements",
    "password_contains_personal": "Password must not contain your name or email",
}


def _enforce_policy(new_password: str, user: User) -> None:
    """Reject weak new passwords (422, code = the policy violation).

    Called by every endpoint that SETS a password, after any must-differ /
    token checks and BEFORE consuming single-use state (setup jti, reset
    used_at) — a policy rejection must never burn the credential. Minimums
    come from settings (env-configurable, published via /password-policy);
    the max length is the fixed schema bound (64).
    """
    policy = settings.validated_password_policy()
    violation = policy.check(new_password, email=user.email, full_name=user.full_name)
    if violation is not None:
        if violation == "password_too_short":
            raise ValidationError(detail=f"Password must be at least {policy.min_length} characters", code=violation)
        if violation == "password_too_long":
            raise ValidationError(detail=f"Password must be at most {PASSWORD_MAX_LENGTH} characters", code=violation)
        raise ValidationError(detail=_POLICY_DETAIL[violation], code=violation)


@router.get("/password-policy", response_model=PasswordPolicyOut)
async def get_password_policy() -> PasswordPolicyOut:
    """The active password policy (public: pre-auth setup/reset forms need it)."""
    p = settings.validated_password_policy()
    return PasswordPolicyOut(
        min_length=p.min_length,
        min_uppercase=p.min_uppercase,
        min_lowercase=p.min_lowercase,
        min_digit=p.min_digit,
        min_symbol=p.min_symbol,
    )


# --- Self-service change ---------------------------------------------------


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    body: ChangePasswordRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    # Step-up limiter: the current password is checked below, so this endpoint
    # must not be usable to brute-force it with a stolen access token.
    await rate_limit.enforce_step_up(current.id)
    if not verify_password(body.current_password, current.password_hash):
        # 422, not 401: the access token authenticated fine — the submitted
        # current password is bad input, not a failed authentication.
        raise ValidationError(detail="Current password is incorrect", code="password_incorrect")
    if body.current_password == body.new_password:
        raise ValidationError(detail="New password must differ from current", code="password_must_differ")
    _enforce_policy(body.new_password, current)
    current.password_hash = hash_password(body.new_password)
    # Knowing the current (temporary) password satisfies the setup gate —
    # reachable when an admin reset a logged-in user mid-session.
    current.must_set_password = False
    current.tokens_invalid_before = _utcnow()  # revoke all prior refresh tokens
    await db.commit()
    return MessageResponse(message="Password changed; other sessions have been signed out")


# --- Forced password setup (first login / after admin reset) ---------------


@router.post("/setup-password", response_model=TokenResponse)
async def setup_password(
    body: SetupPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Choose the account's real password after a gated login.

    The single-use setup token returned by the login flow is the credential
    here — gated users never receive a bearer token. Sets the password,
    clears `must_set_password`, and returns fresh session tokens.
    """
    token_data = verify_setup_token(body.setup_token)
    if token_data is None:
        raise UnauthorizedError(detail="Invalid or expired setup token", code="setup_token_invalid")

    user = await db.get(User, token_data.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError(detail="User not found or inactive", code="account_inactive")
    await rate_limit.enforce_step_up(user.id)

    # Stale token: setup already completed (or the flag was cleared another
    # way) and a real password exists. Passwordless rows with a cleared flag
    # are still allowed through (legacy SSO-only users gaining a password).
    if not user.must_set_password and user.password_hash is not None:
        raise ConflictError(detail="Password already set", code="password_already_set")

    # A typo must not burn the setup token (the /login/mfa ordering:
    # validate, then consume). Passwordless accounts skip this check.
    if user.password_hash is not None and verify_password(body.new_password, user.password_hash):
        raise ValidationError(detail="New password must differ from the temporary one", code="password_must_differ")
    _enforce_policy(body.new_password, user)

    try:
        if not await mfa.consume_setup_jti(token_data.jti):
            raise UnauthorizedError(detail="Setup token already used", code="setup_token_reused")
    except aioredis.RedisError as exc:
        raise APIError(
            "Setup store unavailable; try again shortly",
            code="store_unavailable",
            status_code=503,
            title="Service Unavailable",
        ) from exc

    user.password_hash = hash_password(body.new_password)
    user.must_set_password = False
    # Defense in depth: no session should pre-exist for a gated user, but an
    # admin reset can race a login — this kills any that slipped through.
    user.tokens_invalid_before = _utcnow()
    return await issue_tokens(user, db)


# --- Email password reset (prepared; v1 uses LoggingEmailSender) ---------


@router.post(
    "/password-reset/request",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_password_reset(
    body: PasswordResetRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Always 202 to avoid email enumeration. Sends a reset token only if the
    email exists. With v1's LoggingEmailSender the token is logged instead of emailed.
    """
    # Fail closed in prod: there is no real email sender yet, and logging raw
    # reset tokens to prod logs would make them readable by anyone with log
    # access. Uniform 503 for every email — no enumeration. Flip this when a
    # real EmailSender implementation is wired.
    if settings.environment == "prod":
        raise APIError(
            "Email delivery is not configured; password reset is unavailable",
            code="email_not_configured",
            status_code=503,
            title="Service Unavailable",
        )
    await rate_limit.enforce_password_reset_request(body.email, _client_ip(request))
    user = (await db.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    # Always return 202 regardless of whether the user exists.
    if user is not None and user.is_active:
        raw = _urlsafe_token()
        reset = PasswordReset(
            user_id=user.id,
            token_hash=_sha256(raw),
            expires_at=_utcnow() + timedelta(minutes=settings.password_reset_ttl_minutes),
        )
        db.add(reset)
        await db.commit()
        sender = LoggingEmailSender()
        await sender.send(
            to=user.email,
            subject="Waggi — password reset",
            body=(f"Use this token to reset your password (TTL {settings.password_reset_ttl_minutes}m):\n\n{raw}"),
        )
    return MessageResponse(message="If that email exists, a reset link has been sent.")


@router.post("/password-reset/confirm", response_model=MessageResponse)
async def confirm_password_reset(
    body: PasswordResetConfirm,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    reset = (await db.execute(select(PasswordReset).where(PasswordReset.token_hash == _sha256(body.token)))).scalar_one_or_none()
    if reset is None or reset.used_at is not None or reset.expires_at < _utcnow():
        raise UnauthorizedError(detail="Invalid or expired reset token", code="reset_token_invalid")

    user = await db.get(User, reset.user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError(detail="User not found or inactive", code="account_inactive")

    # A reset must not re-arm the CURRENT password: resets typically follow a
    # suspected compromise, so re-using it would defeat the point. Checked
    # BEFORE the redemption UPDATE — a rejected attempt must not burn the
    # token (same ordering as setup-password). Passwordless rows skip it.
    if user.password_hash is not None and verify_password(body.new_password, user.password_hash):
        raise ValidationError(detail="New password must differ from the current one", code="password_must_differ")
    _enforce_policy(body.new_password, user)

    # Conditional UPDATE on used_at: under a concurrent double-spend of the
    # same reset token, exactly one request wins (the loser gets 401).
    result = typing_cast(
        "CursorResult[Any]",
        await db.execute(
            update(PasswordReset)
            .where(PasswordReset.id == reset.id, PasswordReset.used_at.is_(None))
            .values(used_at=_utcnow())
            .execution_options(synchronize_session=False)
        ),
    )
    if result.rowcount != 1:
        raise UnauthorizedError(detail="Invalid or expired reset token", code="reset_token_invalid")

    user.password_hash = hash_password(body.new_password)
    # Proving email control and choosing a new password satisfies the gate.
    user.must_set_password = False
    user.tokens_invalid_before = _utcnow()  # revoke all sessions
    await db.commit()
    return MessageResponse(message="Password reset; all sessions have been signed out")


# --- helpers --------------------------------------------------------------


def _sha256(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _urlsafe_token() -> str:
    return secrets.token_urlsafe(32)


__all__ = ["router"]
