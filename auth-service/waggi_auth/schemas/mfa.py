"""TOTP 2FA enrollment/management schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TotpStatusResponse(BaseModel):
    """Current 2FA state for the account page (incl. unused backup codes)."""

    totp_enabled: bool
    backup_codes_remaining: int


class TotpSetupRequest(BaseModel):
    """Start TOTP enrollment. Requires the current password (step-up): a stolen
    access token must not be able to enroll an attacker's authenticator."""

    password: str = Field(max_length=128)


class TotpSetupResponse(BaseModel):
    """Secret + provisioning URI for a TOTP app. NOT enabled until verified."""

    secret: str
    otpauth_uri: str


class TotpVerifyRequest(BaseModel):
    """Verify a code against the pending secret to enable TOTP."""

    code: str = Field(pattern=r"^\d{6}$")


class TotpDisableRequest(BaseModel):
    """Disable TOTP: requires the current password + a valid code (or a backup code)."""

    password: str = Field(max_length=128)
    code: str | None = Field(default=None, pattern=r"^\d{6}$")
    backup_code: str | None = Field(default=None, description="One-time backup code (alternative to the TOTP code)")


class TotpRegenerateRequest(BaseModel):
    """Regenerate backup codes. Requires the current password (step-up): the
    response carries live one-time codes, which must not be handed to a stolen
    access token."""

    password: str = Field(max_length=128)


class TotpBackupCodesResponse(BaseModel):
    """One-time backup codes. Returned ONLY at enable time and on regeneration."""

    backup_codes: list[str]
