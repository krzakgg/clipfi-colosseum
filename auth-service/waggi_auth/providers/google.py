"""Google OAuth / OIDC provider.

Console: https://console.cloud.google.com/apis/credentials (Web application).
Redirect URI to register: <FRONTEND_URL>/api/v1/auth/sso/google/callback

Env: GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET (empty = provider disabled).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from waggi_auth.providers.base import JwksCache, ProviderClient, ProviderSpec

if TYPE_CHECKING:  # pragma: no cover — typing only, avoids import at runtime
    from waggi_auth.config import Settings

_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
# Google has historically issued both issuer spellings; accept either.
_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
_SCOPE = "openid email profile"

# Shared across every GoogleClient build.
_JWKS = JwksCache("https://www.googleapis.com/oauth2/v3/certs")


class GoogleClient(ProviderClient):
    name = "google"
    scope = _SCOPE

    def __init__(self, client_id: str, client_secret: str) -> None:
        super().__init__(
            client_id=client_id,
            authorize_endpoint=_AUTH_ENDPOINT,
            token_endpoint=_TOKEN_ENDPOINT,
            jwks=_JWKS,
            issuers=_ISSUERS,
        )
        self._client_secret = client_secret

    def _client_secret_fields(self) -> dict[str, str]:
        return {"client_secret": self._client_secret}


def _is_configured(settings: Settings) -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def _build(settings: Settings) -> GoogleClient:
    return GoogleClient(settings.google_client_id, settings.google_client_secret)


SPEC = ProviderSpec(name="google", is_configured=_is_configured, build=_build)

__all__ = ["SPEC", "GoogleClient"]
