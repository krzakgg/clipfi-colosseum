"""TOTP 2FA management endpoints: setup, verify/enable, disable, regenerate backups."""

from __future__ import annotations

import pyotp
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from waggi_auth import rate_limit
from waggi_auth.dependencies import get_current_user, get_db
from waggi_auth.models import User
from waggi_auth.schemas import (
    MessageResponse,
    TotpBackupCodesResponse,
    TotpDisableRequest,
    TotpRegenerateRequest,
    TotpSetupRequest,
    TotpSetupResponse,
    TotpStatusResponse,
    TotpVerifyRequest,
)
from waggi_auth.security.totp import (
    encrypt_totp_secret,
    generate_backup_codes,
    hash_backup_codes,
    match_backup_code,
    verify_totp_for_user,
)
from waggi_shared.errors import ConflictError, ValidationError
from waggi_shared.passwords import verify_password

router = APIRouter(prefix="/api/v1/auth/2fa", tags=["2fa"])


@router.get("", response_model=TotpStatusResponse)
async def totp_status(current: User = Depends(get_current_user)) -> TotpStatusResponse:
    """2FA status for the account page: enabled + how many backup codes are still unused.

    Only the COUNT is exposed — the codes themselves are sha256-hashed at rest
    and unrecoverable by design.
    """
    return TotpStatusResponse(
        totp_enabled=current.totp_enabled,
        backup_codes_remaining=len(current.totp_backup_codes_hashed),
    )


@router.post("/setup", response_model=TotpSetupResponse)
async def setup_totp(
    body: TotpSetupRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TotpSetupResponse:
    """Generate a TOTP secret + provisioning URI. Does NOT enable 2FA yet.

    Step-up (password): a stolen access token must not be able to enroll an
    attacker-controlled authenticator on the account. The client must call
    /verify with a valid code to activate it.
    """
    await rate_limit.enforce_step_up(current.id)
    if current.totp_enabled:
        raise ConflictError(detail="2FA is already enabled", code="twofa_already_enabled")
    if not verify_password(body.password, current.password_hash):
        # 422, not 401: the access token authenticated fine — the password
        # input is invalid. A 401 here would make API clients mistake a
        # wrong password for an expired token (refresh + retry loops).
        raise ValidationError(detail="Current password is incorrect", code="password_incorrect")
    secret = pyotp.random_base32()
    # Temporarily stash the (encrypted) pending secret on the user so /verify
    # can activate it. It is NOT marked enabled until verification succeeds.
    current.totp_secret = encrypt_totp_secret(secret)
    await db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=current.email, issuer_name="Waggi")
    return TotpSetupResponse(secret=secret, otpauth_uri=uri)


@router.post("/verify", response_model=TotpBackupCodesResponse)
async def verify_totp(
    body: TotpVerifyRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TotpBackupCodesResponse:
    """Verify the pending secret with a code, enabling TOTP + returning backup codes."""
    await rate_limit.enforce_totp_verify(current.id)
    if current.totp_enabled:
        raise ConflictError(detail="2FA is already enabled", code="twofa_already_enabled")
    if not current.totp_secret:
        raise ValidationError(detail="No pending 2FA setup; call /setup first", code="twofa_no_pending_setup")
    if not verify_totp_for_user(current, body.code):
        # 422, not 401 — the session is authenticated; the code is bad input.
        raise ValidationError(detail="Invalid TOTP code", code="totp_code_invalid")
    backup_codes = generate_backup_codes()
    current.totp_enabled = True
    current.totp_backup_codes_hashed = hash_backup_codes(backup_codes)
    await db.commit()
    return TotpBackupCodesResponse(backup_codes=backup_codes)


@router.post("/disable", response_model=MessageResponse)
async def disable_totp(
    body: TotpDisableRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Disable TOTP. Requires the current password + a valid code (or backup code)."""
    await rate_limit.enforce_totp_disable(current.id)
    if not current.totp_enabled:
        raise ConflictError(detail="2FA is not enabled", code="twofa_not_enabled")
    if not verify_password(body.password, current.password_hash):
        raise ValidationError(detail="Current password is incorrect", code="password_incorrect")
    # A backup code is as strong a second factor as a TOTP code here — it lets
    # a user who lost their authenticator still turn 2FA off (all codes die
    # with 2FA anyway). Peppered and legacy-format codes both match.
    if body.backup_code:
        if match_backup_code(current.totp_backup_codes_hashed, body.backup_code) is None:
            raise ValidationError(detail="Invalid backup code", code="backup_code_invalid")
    elif body.code:
        if not verify_totp_for_user(current, body.code):
            raise ValidationError(detail="Invalid TOTP code", code="totp_code_invalid")
    else:
        raise ValidationError(detail="Provide either a TOTP code or a backup code", code="second_factor_required")
    current.totp_enabled = False
    current.totp_secret = None
    current.totp_backup_codes_hashed = []
    await db.commit()
    return MessageResponse(message="2FA disabled")


@router.post("/backup/regenerate", response_model=TotpBackupCodesResponse)
async def regenerate_backup_codes(
    body: TotpRegenerateRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TotpBackupCodesResponse:
    """Replace all backup codes with a fresh set. Previous codes are invalidated.

    Step-up (password): the response carries the LIVE one-time codes — handing
    them to a stolen access token would defeat 2FA entirely (password + fresh
    backup code passes /login/mfa).
    """
    await rate_limit.enforce_step_up(current.id)
    if not current.totp_enabled:
        raise ConflictError(detail="2FA is not enabled", code="twofa_not_enabled")
    if not verify_password(body.password, current.password_hash):
        raise ValidationError(detail="Current password is incorrect", code="password_incorrect")
    backup_codes = generate_backup_codes()
    current.totp_backup_codes_hashed = hash_backup_codes(backup_codes)
    await db.commit()
    return TotpBackupCodesResponse(backup_codes=backup_codes)


__all__ = ["router"]
