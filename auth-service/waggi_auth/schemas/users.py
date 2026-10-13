"""User directory schemas (public registration; UserOut also by /auth/me)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from waggi_auth.models import AccountType
from waggi_shared.validation import PhoneNumber


class RegisterRequest(BaseModel):
    """Public self-signup (waggi: companies and creators register themselves)."""

    account_type: AccountType = AccountType.company
    email: EmailStr
    # Creators log in with email OR username; companies typically skip it.
    username: str | None = Field(default=None, min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    full_name: str = Field(min_length=1, max_length=255)
    phone: PhoneNumber | None = Field(default=None, max_length=32, description="International format (E.164), e.g. +48600100200")
    # Length bounds mirrored by the password policy (max fixed at 64, NIST 800-63B floor).
    password: str = Field(min_length=8, max_length=64)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    username: str | None
    full_name: str
    phone: str | None
    account_type: AccountType
    is_active: bool
    totp_enabled: bool
    created_at: datetime


class UpdateMeRequest(BaseModel):
    """Self-service profile update (PATCH /auth/me). Email + account_type are read-only."""

    full_name: str = Field(min_length=1, max_length=255)
    phone: PhoneNumber | None = Field(default=None, max_length=32, description="International format (E.164), e.g. +48600100200")
