"""Login/session lifecycle schemas (password login, MFA step, refresh)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    # waggi: email OR username (creators use either). Not EmailStr — a bare
    # username would fail email validation.
    email: str = Field(min_length=3, max_length=255, description="Email or username")
    # Bounded so an oversized password can't be fed to argon2 (CPU/RAM DoS);
    # 128 matches every other password field in the service.
    password: str = Field(max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class MfaRequiredResponse(BaseModel):
    """Returned by login when the user has TOTP enabled — client must complete the MFA step."""

    mfa_required: bool = True
    mfa_token: str
    expires_in: int


class SetupRequiredResponse(BaseModel):
    """Returned by ANY login flow while `must_set_password` is set.

    No session tokens are issued — the client must complete
    POST /auth/setup-password with the single-use setup token first.
    """

    setup_required: bool = True
    setup_token: str
    expires_in: int


class LoginMfaRequest(BaseModel):
    """Second login step: an MFA token (from the first step) + a TOTP code OR a backup code."""

    mfa_token: str
    code: str | None = Field(default=None, description="6-digit TOTP code")
    backup_code: str | None = Field(default=None, description="One-time backup code (alternative to TOTP)")
