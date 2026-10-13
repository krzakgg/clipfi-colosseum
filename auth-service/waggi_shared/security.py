"""JWT/JWKS verification used by *admin* and *bookings* (never by *auth*).

Validates RS256 JWTs issued by auth, fetching the public key from auth's JWKS
endpoint with caching + re-fetch on unknown `kid` (key rotation).

Auth does NOT use the verifier — it has the private key and signs tokens.

Password hashing used to live here; it moved to `waggi_shared.passwords`
(direct argon2-cffi) when the unmaintained `passlib` was retired.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt

from waggi_shared.email import EmailSender

# --- JWT claims model ------------------------------------------------------


@dataclass(frozen=True)
class TokenClaims:
    """Decoded JWT claims for the currently authenticated user."""

    user_id: str
    email: str
    name: str
    role: str
    issuer: str
    issued_at: int
    expires_at: int
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    @property
    def is_privileged(self) -> bool:
        """Owner or admin — roles that require TOTP 2FA and elevated access."""
        return self.role in ("owner", "admin")

    @property
    def can_book_on_behalf(self) -> bool:
        """Owner, admin, or receptionist — roles allowed to create bookings for others."""
        return self.role in ("owner", "admin", "receptionist")


# --- JWKS client (used by admin/bookings to trust auth) -------------------


class JWKSClient:
    """Fetches + caches auth's public signing keys (kid -> public key).

    Keys are cached in-memory and re-fetched when a token's `kid` is unknown
    (handles key rotation). For an internal tool this is sufficient; a TTL
    cache can be added if needed.
    """

    def __init__(self, jwks_url: str, *, issuer: str | None = None) -> None:
        self._jwks_url = jwks_url
        self._issuer = issuer
        self._keys: dict[str, dict[str, Any]] = {}
        self._fetched = False

    async def _ensure_loaded(self) -> None:
        if self._fetched:
            return
        await self._refresh()
        self._fetched = True

    async def _refresh(self) -> None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(self._jwks_url)
            resp.raise_for_status()
            jwks = resp.json()
        self._keys = {str(k["kid"]): dict(k) for k in jwks.get("keys", [])}

    async def get_key(self, kid: str) -> dict[str, Any]:
        """Return the JWK for a kid, refreshing once if unknown."""
        await self._ensure_loaded()
        if kid in self._keys:
            return self._keys[kid]
        # Unknown kid → maybe auth rotated keys; refresh once.
        await self._refresh()
        if kid not in self._keys:
            raise jwt.InvalidTokenError(f"Unknown kid: {kid!r}")
        return self._keys[kid]


class TokenVerifier:
    """Verifies RS256 JWTs from auth using a JWKSClient."""

    def __init__(self, jwks_client: JWKSClient, *, issuer: str, algorithms: list[str] | None = None) -> None:
        self._jwks = jwks_client
        self._issuer = issuer
        self._algorithms = algorithms or ["RS256"]

    async def verify(self, token: str) -> TokenClaims:
        """Verify signature + standard claims; return decoded TokenClaims.

        Raises jwt.PyJWTError subclass on any failure. Callers map these to 401.
        """
        # Peek at unverified header to find kid without exposing ourselves to
        # a "none" algorithm: we pass the explicit algorithm list to decode.
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            raise jwt.InvalidTokenError("Missing kid in token header")

        # The JWKS key is a JWK dict; PyJWT can use it directly via PyJWK.
        jwk = await self._jwks.get_key(kid)  # returns dict (JWK)
        signing_key = jwt.PyJWK(jwk)

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=self._algorithms,
            issuer=self._issuer,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
        now = int(time.time())
        if payload.get("exp", 0) < now:
            raise jwt.ExpiredSignatureError("Token expired")

        return TokenClaims(
            user_id=str(payload["sub"]),
            email=str(payload.get("email", "")),
            name=str(payload.get("name", "")),
            role=str(payload.get("role", "worker")),
            issuer=str(payload.get("iss", "")),
            issued_at=int(payload.get("iat", 0)),
            expires_at=int(payload.get("exp", 0)),
            raw=payload,
        )


__all__ = [
    "EmailSender",
    "JWKSClient",
    "TokenClaims",
    "TokenVerifier",
]
