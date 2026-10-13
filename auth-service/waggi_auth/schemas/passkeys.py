"""Passkey (WebAuthn) ceremony schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PasskeyBeginResponse(BaseModel):
    """Ceremony start: an opaque handle + the JSON options for the browser API."""

    handle: str
    options: dict[str, Any]


class PasskeyRegisterFinishRequest(BaseModel):
    """Finish registration. `password` is the step-up check: a stolen access
    token must not be able to register an attacker's passkey (which would be a
    persistent backdoor — passkey login skips TOTP by design)."""

    handle: str
    credential: dict[str, Any]
    password: str = Field(max_length=128)
    nickname: str | None = Field(default=None, max_length=120)


class PasskeyLoginFinishRequest(BaseModel):
    handle: str
    credential: dict[str, Any]


class PasskeyRenameRequest(BaseModel):
    nickname: str = Field(min_length=1, max_length=120)


class PasskeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nickname: str | None
    created_at: datetime
    last_used_at: datetime | None
    # Device metadata (best-effort, captured at registration).
    transports: list[str] = []
    aaguid: str | None = None  # provider UUID, NULL when unidentified
    attachment: str | None = None  # "platform" | "cross-platform" | None
    backed_up: bool = False  # True for synced passkeys (WebAuthn BS flag)
