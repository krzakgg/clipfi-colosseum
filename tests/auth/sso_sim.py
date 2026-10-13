"""A fake OAuth/OIDC provider for SSO tests: mint RS256 id_tokens + a JWKS.

The provider signs id_tokens with its own RSA key and exposes the matching
JWKS document, so the full verify path (JWKS fetch → signature → iss/aud/exp/
nonce) runs for real — tests only mock the HTTP endpoints via respx.
"""

from __future__ import annotations

import base64
import time
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

# Values matching the test-configured Google client (see conftest env bootstrap).
GOOGLE_CLIENT_ID = "test-google-client-id"
GOOGLE_ISSUER = "accounts.google.com"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_ENDPOINT = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"


def _b64u(num: int) -> str:
    length = (num.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(num.to_bytes(length, "big")).rstrip(b"=").decode()


class FakeProvider:
    """Signs id_tokens like Google/Apple would; serves the matching JWKS."""

    def __init__(self, *, kid: str = "test-kid-1") -> None:
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.kid = kid

    def jwks_document(self) -> dict[str, Any]:
        numbers = self._key.public_key().public_numbers()
        return {
            "keys": [
                {
                    "kid": self.kid,
                    "kty": "RSA",
                    "alg": "RS256",
                    "use": "sig",
                    "n": _b64u(numbers.n),
                    "e": _b64u(numbers.e),
                }
            ]
        }

    def id_token(
        self,
        *,
        subject: str,
        nonce: str,
        issuer: str = GOOGLE_ISSUER,
        audience: str = GOOGLE_CLIENT_ID,
        email: str | None = "user@example.com",
        email_verified: bool | Any = True,
        name: str | None = "Test User",
        expires_in: int = 3600,
        include_email: bool = True,
    ) -> str:
        now = int(time.time())
        payload: dict[str, Any] = {
            "iss": issuer,
            "aud": audience,
            "sub": subject,
            "iat": now,
            "exp": now + expires_in,
            "nonce": nonce,
        }
        if include_email:
            payload["email"] = email
            payload["email_verified"] = email_verified
        if name is not None:
            payload["name"] = name
        return jwt.encode(payload, self._key, algorithm="RS256", headers={"kid": self.kid})
