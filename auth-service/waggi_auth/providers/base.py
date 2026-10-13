"""Shared skeleton for OAuth/OIDC provider clients.

Every provider (google.py, apple.py, ...) implements:
- a `ProviderClient` subclass supplying endpoints, scope, issuers and the
  client-secret strategy for the token exchange;
- a module-level `SPEC: ProviderSpec` describing how to check configuration
  and build the client from settings.

The package `__init__` keeps the registry; the router only talks to
`get_provider_client` / `provider_status`.

Flow (authorization code, server-side secret):
- `authorize_url` builds the provider consent URL (state + nonce included).
- `exchange_code` swaps the code for tokens and returns the VERIFIED id_token
  claims (JWKS signature, issuer, audience, expiry, nonce all checked).

Error mapping: upstream/network failures raise APIError 502/503 so the
router's error redirect stays informative; verification failures raise 401.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import httpx
import jwt

from waggi_shared.errors import APIError, UnauthorizedError

if TYPE_CHECKING:  # pragma: no cover — typing only, avoids import at runtime
    from waggi_auth.config import Settings


@dataclass(frozen=True)
class VerifiedIdentity:
    """Claims from a verified provider id_token."""

    subject: str  # provider-stable user id ("sub")
    email: str | None
    email_verified: bool
    full_name: str | None


def _truthy(value: Any) -> bool:
    """Google sends a bool; Apple sends the STRING "true"."""
    return value is True or value == "true"


# How long provider signing keys stay cached before a fresh fetch.
_JWKS_CACHE_TTL = 3600


class JwksCache:
    """Process-local JWKS cache (~1h). Refreshes once on an unknown kid.

    One instance per provider (see the provider modules) — keys are shared
    across every client build of that provider.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._keys: dict[str, dict[str, Any]] = {}
        self._fetched_at: float = 0.0

    async def keys(self, client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
        if not self._keys or (time.monotonic() - self._fetched_at) > _JWKS_CACHE_TTL:
            await self._refresh(client)
        return self._keys

    async def key_for(self, client: httpx.AsyncClient, kid: str) -> dict[str, Any] | None:
        keys = await self.keys(client)
        key = keys.get(kid)
        if key is None:  # rotated since our last fetch — try once more
            await self._refresh(client)
            key = self._keys.get(kid)
        return key

    async def _refresh(self, client: httpx.AsyncClient) -> None:
        try:
            res = await client.get(self._url)
            res.raise_for_status()
            self._keys = {k["kid"]: k for k in res.json()["keys"] if "kid" in k}
            self._fetched_at = time.monotonic()
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise APIError(
                "Could not fetch provider signing keys",
                code="sso_provider_unreachable",
                status_code=502,
                title="Bad Gateway",
            ) from exc


class ProviderClient:
    """Shared authorize/exchange/verify skeleton; providers supply specifics."""

    name = ""
    scope = ""

    def __init__(
        self,
        *,
        client_id: str,
        authorize_endpoint: str,
        token_endpoint: str,
        jwks: JwksCache,
        issuers: tuple[str, ...],
        extra_auth_params: dict[str, str] | None = None,
    ) -> None:
        self.client_id = client_id
        self._authorize_endpoint = authorize_endpoint
        self._token_endpoint = token_endpoint
        self._jwks = jwks
        self._issuers = issuers
        self._extra_auth_params = extra_auth_params or {}

    # --- authorize -----------------------------------------------------

    def authorize_url(self, redirect_uri: str, state: str, nonce: str) -> str:
        params: dict[str, str] = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "nonce": nonce,
            "scope": self.scope,
            **self._extra_auth_params,
        }
        return f"{self._authorize_endpoint}?{urlencode(params)}"

    # --- exchange ------------------------------------------------------

    async def exchange_code(self, code: str, redirect_uri: str, nonce: str) -> VerifiedIdentity:
        data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.client_id,
            **self._client_secret_fields(),
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                res = await client.post(self._token_endpoint, data=data)
            except httpx.HTTPError as exc:
                raise APIError(
                    "Provider token endpoint unreachable",
                    code="sso_provider_unreachable",
                    status_code=502,
                    title="Bad Gateway",
                ) from exc
            if res.status_code != 200:
                raise UnauthorizedError(detail="Provider rejected the authorization code", code="sso_code_rejected")
            try:
                id_token = res.json().get("id_token", "")
            except ValueError as exc:
                raise APIError(
                    "Provider returned a malformed token response",
                    code="sso_provider_unreachable",
                    status_code=502,
                    title="Bad Gateway",
                ) from exc
            if not id_token:
                raise APIError(
                    "Provider returned no id_token",
                    code="sso_provider_unreachable",
                    status_code=502,
                    title="Bad Gateway",
                )
            return await self._verify_id_token(id_token, nonce, client)

    def _client_secret_fields(self) -> dict[str, str]:
        """Auth fields for the token exchange; providers with a secret override."""
        return {}

    # --- verify --------------------------------------------------------

    async def _verify_id_token(self, id_token: str, expected_nonce: str, client: httpx.AsyncClient) -> VerifiedIdentity:
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError as exc:
            raise UnauthorizedError(detail="Malformed provider id_token", code="sso_token_invalid") from exc

        jwk = await self._jwks.key_for(client, header.get("kid", ""))
        if jwk is None:
            raise UnauthorizedError(detail="Unknown provider signing key", code="sso_token_invalid")

        # alg pinned to RS256 — never trust the token header's own alg claim
        # (classic alg-confusion vector when verification trusts the header).
        try:
            verified = jwt.decode(
                id_token,
                key=jwt.PyJWK.from_dict(jwk).key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=None,  # checked manually below (Google has two spellings)
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.PyJWTError as exc:
            raise UnauthorizedError(detail="Provider id_token failed verification", code="sso_token_invalid") from exc

        if verified.get("iss") not in self._issuers:
            raise UnauthorizedError(detail="Provider id_token issuer mismatch", code="sso_token_invalid")
        if verified.get("nonce") != expected_nonce:
            raise UnauthorizedError(detail="Provider id_token nonce mismatch", code="sso_token_invalid")

        email = verified.get("email")
        name = verified.get("name") or verified.get("full_name")
        return VerifiedIdentity(
            subject=str(verified["sub"]),
            email=str(email) if email else None,
            email_verified=_truthy(verified.get("email_verified")),
            full_name=str(name) if name else None,
        )


@dataclass(frozen=True)
class ProviderSpec:
    """Registry entry for one provider.

    `is_configured` drives the public provider list (a provider is only
    offered/enabled when its credentials are present); `build` constructs a
    fresh client from settings on every use (no import-time coupling).
    """

    name: str
    is_configured: Callable[[Settings], bool]
    build: Callable[[Settings], ProviderClient]


__all__ = [
    "JwksCache",
    "ProviderClient",
    "ProviderSpec",
    "VerifiedIdentity",
]
