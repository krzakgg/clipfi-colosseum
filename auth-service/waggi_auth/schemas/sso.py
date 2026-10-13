"""SSO schemas: OAuth login flow + multi-identity link management."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SsoProviderOut(BaseModel):
    """A login provider + whether it is configured (client creds present)."""

    provider: str
    enabled: bool


class SsoAuthorizeRequest(BaseModel):
    """Start an SSO login. `redirect` is a frontend path to land on after login."""

    redirect: str | None = Field(default=None, description="Frontend path, e.g. /account")


class SsoAuthorizeResponse(BaseModel):
    """The provider consent URL — the SPA navigates the browser here."""

    authorize_url: str


class SsoCompleteRequest(BaseModel):
    """Finish an SSO login: exchange the one-time handle from the callback redirect."""

    handle: str = Field(min_length=16, max_length=128)


class SsoLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    provider_subject: str
    linked_at: datetime
