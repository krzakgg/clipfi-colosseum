"""Password lifecycle schemas (self-service change, email reset)."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from waggi_shared.password_policy import PASSWORD_MAX_LENGTH


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=8, max_length=PASSWORD_MAX_LENGTH)


class SetupPasswordRequest(BaseModel):
    """Complete a gated login: exchange the single-use setup token for the
    account's real password (and session tokens)."""

    setup_token: str
    new_password: str = Field(min_length=8, max_length=PASSWORD_MAX_LENGTH)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=PASSWORD_MAX_LENGTH)


class PasswordPolicyOut(BaseModel):
    """The configured password policy, for password-choice forms.

    Public (unauthenticated) — the pre-auth setup/reset flows need it, and
    the minimums are not sensitive. The frontend mirrors these into its
    zod validation so client and server agree without hardcoding. The max
    length is deliberately NOT here — it is fixed at 64
    (PASSWORD_MAX_LENGTH), hard-coded into the request schemas on both
    sides.
    """

    min_length: int
    min_uppercase: int
    min_lowercase: int
    min_digit: int
    min_symbol: int
