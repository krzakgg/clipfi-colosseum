"""Token creation + verification (the issuing side).

Three token types, none interchangeable:

- **Access token** — short-lived RS256 JWT (kid header points into the JWKS).
  Claims: sub, email, name, account_type, iss, iat, exp.
- **Refresh token** — 48 bytes of entropy, opaque; only its sha256 is stored
  (indexed O(1) lookup) and only the raw form is ever returned to the client.
- **MFA challenge token** — short-lived HS256 JWT proving the password check
  passed; carries a `jti` that `/login/mfa` consumes for single-use semantics.
- **Password-setup token** — short-lived HS256 JWT issued by login flows
  while `must_set_password` is set, in place of session tokens; carries a
  `jti` that `/setup-password` consumes for single-use semantics. Same secret
  as MFA tokens, but the distinct `aud` (audience) claim — the IANA-registered
  way to bind a token to its recipient endpoint — keeps them
  non-interchangeable in both directions.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives import serialization

from waggi_auth.config import settings
from waggi_auth.security.keys import get_private_key

# --- Access tokens ---------------------------------------------------------


def create_access_token(
    *,
    user_id: uuid.UUID,
    email: str,
    full_name: str,
    account_type: str,
) -> tuple[str, int]:
    """Sign a short-lived RS256 access JWT. Returns (token, ttl_seconds)."""
    ttl = settings.access_token_ttl_minutes * 60
    now = datetime.now(tz=UTC)
    payload = {
        "sub": str(user_id),
        "email": email,
        "name": full_name,
        "account_type": account_type,
        "iss": settings.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + ttl,
    }
    token = jwt.encode(payload, _private_pem(), algorithm="RS256", headers={"kid": settings.jwt_key_id})
    return token, ttl


# --- Refresh tokens --------------------------------------------------------


def create_refresh_token() -> tuple[str, str, datetime, datetime]:
    """Create a new refresh token. Returns (raw_token, token_hash, issued_at, expires_at).

    `token_hash` is a deterministic sha256 of the raw token so it can be indexed
    and looked up in O(1). The raw token has 48 bytes of entropy, so the sha256
    is not brute-forceable. Only the raw token is ever returned to the client.
    """
    raw = secrets.token_urlsafe(48)
    token_hash = hash_refresh_token(raw)
    now = datetime.now(tz=UTC)
    expires_at = now + timedelta(days=settings.refresh_token_ttl_days)
    return raw, token_hash, now, expires_at


def hash_refresh_token(raw: str) -> str:
    """Hash a raw refresh token for storage/lookup (deterministic sha256)."""
    return hashlib.sha256(raw.encode()).hexdigest()


def _private_pem() -> str:
    return (
        get_private_key()
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode()
    )


# --- Single-use challenge tokens (MFA step, forced password setup) ---------


@dataclass(frozen=True)
class MfaTokenData:
    """Verified contents of an MFA challenge token.

    `jti` uniquely identifies the token so `/login/mfa` can enforce single use
    (blacklist-on-consume in Redis).
    """

    user_id: uuid.UUID
    jti: str


@dataclass(frozen=True)
class SetupTokenData:
    """Verified contents of a password-setup token (same shape as MFA)."""

    user_id: uuid.UUID
    jti: str


def _create_purpose_token(*, user_id: uuid.UUID, audience: str, ttl_minutes: int) -> tuple[str, int]:
    """Sign a short-lived HS256 challenge token (shared MFA/setup machinery).

    `aud` (RFC 7519, IANA-registered) names the ONE endpoint the token opens;
    PyJWT enforces the match on decode (`audience=`), so a token minted for
    one ceremony cannot be replayed at another.
    """
    ttl = ttl_minutes * 60
    now = datetime.now(tz=UTC)
    payload = {
        "sub": str(user_id),
        "aud": audience,
        "jti": secrets.token_urlsafe(16),
        "iss": settings.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + ttl,
    }
    return jwt.encode(payload, settings.mfa_token_secret, algorithm="HS256"), ttl


def create_mfa_token(*, user_id: uuid.UUID) -> tuple[str, int]:
    """Sign a short-lived HS256 MFA challenge token. Returns (token, ttl_seconds).

    This is NOT an access or refresh token — it only proves the password check
    passed, so the second step (TOTP code / backup code) can complete login.
    Stays stateless: the embedded `jti` is what makes it single-use later.
    """
    return _create_purpose_token(user_id=user_id, audience="mfa", ttl_minutes=settings.mfa_token_ttl_minutes)


def create_setup_token(*, user_id: uuid.UUID) -> tuple[str, int]:
    """Sign a short-lived HS256 password-setup token. Returns (token, ttl_seconds).

    Returned by every login flow while `must_set_password` is set, INSTEAD of
    session tokens — a shared temporary password must never reach the API.
    It proves the caller authenticated (and cleared TOTP when enrolled) and is
    exchangeable ONLY at POST /setup-password. Stateless like the MFA token:
    the embedded `jti` is consumed there for single use.
    """
    return _create_purpose_token(user_id=user_id, audience="setup_password", ttl_minutes=settings.setup_token_ttl_minutes)


def _decode_purpose_token(token: str, audience: str) -> tuple[uuid.UUID, str] | None:
    """Decode + validate an audience-bound challenge token -> (user_id, jti).

    None on any signature/expiry/issuer/audience problem or malformed sub.
    The audience match is enforced by PyJWT itself (`InvalidAudienceError`,
    plus `MissingRequiredClaimError` when `aud` is absent).
    """
    try:
        payload = jwt.decode(
            token,
            settings.mfa_token_secret,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience=audience,
            options={"require": ["exp", "iat", "iss", "sub", "aud", "jti"]},
        )
    except jwt.PyJWTError:
        return None
    try:
        user_id = uuid.UUID(str(payload["sub"]))
    except (ValueError, TypeError):
        return None
    return user_id, str(payload["jti"])


def verify_mfa_token(token: str) -> MfaTokenData | None:
    """Verify an MFA challenge token. Returns its claims, or None if invalid/expired."""
    decoded = _decode_purpose_token(token, "mfa")
    if decoded is None:
        return None
    return MfaTokenData(user_id=decoded[0], jti=decoded[1])


def verify_setup_token(token: str) -> SetupTokenData | None:
    """Verify a password-setup token. Returns its claims, or None if invalid/expired."""
    decoded = _decode_purpose_token(token, "setup_password")
    if decoded is None:
        return None
    return SetupTokenData(user_id=decoded[0], jti=decoded[1])


__all__ = [
    "MfaTokenData",
    "SetupTokenData",
    "create_access_token",
    "create_mfa_token",
    "create_refresh_token",
    "create_setup_token",
    "hash_refresh_token",
    "verify_mfa_token",
    "verify_setup_token",
]
