"""Sign in with Apple provider.

Setup (needs a paid Apple Developer account):
- Register a Services ID (= client id) with Sign In with Apple enabled.
- Register a Key, download the .p8 EC private key.
- Return URL: https://<frontend-host>/api/v1/auth/sso/apple/callback (HTTPS only).

Env: APPLE_CLIENT_ID + APPLE_TEAM_ID + APPLE_KEY_ID + APPLE_PRIVATE_KEY_PATH
(empty = provider disabled).

Provider quirks handled here:
- the authorize call uses `response_mode=form_post`, so the callback route
  must accept POST form data (the router registers GET and POST);
- `email_verified` arrives as the STRING "true" (normalized in base);
- the token exchange needs an ephemeral ES256 JWT as the client secret,
  regenerated for every exchange (exp = now + 10 min).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey

from waggi_auth.providers.base import JwksCache, ProviderClient, ProviderSpec
from waggi_shared.errors import APIError

if TYPE_CHECKING:  # pragma: no cover — typing only, avoids import at runtime
    from waggi_auth.config import Settings

_AUTH_ENDPOINT = "https://appleid.apple.com/auth/authorize"
_TOKEN_ENDPOINT = "https://appleid.apple.com/auth/token"
_ISSUER = "https://appleid.apple.com"
_SCOPE = "name email"

# Shared across every AppleClient build.
_JWKS = JwksCache("https://appleid.apple.com/auth/keys")

# Apple rejects client secrets with a longer lifetime; we regenerate per exchange.
_CLIENT_SECRET_TTL_SECONDS = 600


class AppleClient(ProviderClient):
    name = "apple"
    scope = _SCOPE

    def __init__(self, client_id: str, team_id: str, key_id: str, private_key_path: str) -> None:
        super().__init__(
            client_id=client_id,
            authorize_endpoint=_AUTH_ENDPOINT,
            token_endpoint=_TOKEN_ENDPOINT,
            jwks=_JWKS,
            issuers=(_ISSUER,),
            extra_auth_params={"response_mode": "form_post"},
        )
        self._team_id = team_id
        self._key_id = key_id
        self._private_key_path = private_key_path

    def _client_secret_fields(self) -> dict[str, str]:
        try:
            with open(self._private_key_path, "rb") as fh:
                private_key = serialization.load_pem_private_key(fh.read(), password=None)
        except (OSError, ValueError) as exc:
            raise APIError(
                "Apple private key could not be loaded",
                code="sso_provider_misconfigured",
                status_code=500,
                title="Server Error",
            ) from exc
        if not isinstance(private_key, EllipticCurvePrivateKey):
            raise APIError(
                "Apple private key must be an EC key (.p8)",
                code="sso_provider_misconfigured",
                status_code=500,
                title="Server Error",
            )
        now = int(time.time())
        secret = jwt.encode(
            {
                "iss": self._team_id,
                "sub": self.client_id,
                "aud": _ISSUER,
                "iat": now,
                "exp": now + _CLIENT_SECRET_TTL_SECONDS,
            },
            private_key,
            algorithm="ES256",
            headers={"kid": self._key_id},
        )
        return {"client_secret": secret}


def _is_configured(settings: Settings) -> bool:
    return bool(settings.apple_client_id and settings.apple_team_id and settings.apple_key_id and settings.apple_private_key_path)


def _build(settings: Settings) -> AppleClient:
    return AppleClient(
        settings.apple_client_id,
        settings.apple_team_id,
        settings.apple_key_id,
        settings.apple_private_key_path,
    )


SPEC = ProviderSpec(name="apple", is_configured=_is_configured, build=_build)

__all__ = ["SPEC", "AppleClient"]
