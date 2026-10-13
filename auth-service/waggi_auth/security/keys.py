"""RSA signing keypair lifecycle + JWKS exposure.

The private key never leaves this service; the public key is published as a
JWK at `/.well-known/jwks.json` (served by `routers/jwks.py`) so admin and
bookings can verify auth-issued RS256 JWTs.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from waggi_auth.config import settings


def _generate_keypair() -> tuple[RSAPrivateKey, RSAPublicKey]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@lru_cache(maxsize=1)
def _ensure_keypair() -> tuple[RSAPrivateKey, RSAPublicKey]:
    """Load the RSA keypair from disk, generating + persisting it on first run.

    In prod, mount the keys via a volume instead of letting them be generated.
    """
    priv_path = Path(settings.jwt_private_key_path)
    pub_path = Path(settings.jwt_public_key_path)

    if priv_path.exists() and pub_path.exists():
        priv_pem = priv_path.read_bytes()
        loaded = serialization.load_pem_private_key(priv_pem, password=None)
        assert isinstance(loaded, RSAPrivateKey)
        private_key = loaded
        public_key = private_key.public_key()
        return private_key, public_key

    # Generate + persist (dev convenience).
    private_key, public_key = _generate_keypair()
    priv_path.parent.mkdir(parents=True, exist_ok=True)
    priv_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    pub_path.write_bytes(
        public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    priv_path.chmod(0o600)
    return private_key, public_key


@lru_cache(maxsize=1)
def get_private_key() -> RSAPrivateKey:
    """Return the RSA private key (cached singleton)."""
    return _ensure_keypair()[0]


@lru_cache(maxsize=1)
def get_public_key() -> RSAPublicKey:
    """Return the RSA public key (cached singleton)."""
    return _ensure_keypair()[1]


def jwks_document() -> dict[str, Any]:
    """Build the JWKS document served at `/.well-known/jwks.json`.

    Returns the public key as a proper JWK (n, e) so PyJWT's PyJWK can consume it.
    """
    public_key = get_public_key()
    numbers = public_key.public_numbers()

    def _b64u(num: int) -> str:
        length = (num.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(num.to_bytes(length, "big")).rstrip(b"=").decode()

    jwk = {
        "kid": settings.jwt_key_id,
        "kty": "RSA",
        "alg": "RS256",
        "use": "sig",
        "n": _b64u(numbers.n),
        "e": _b64u(numbers.e),
    }
    return {"keys": [jwk]}


__all__ = ["get_private_key", "get_public_key", "jwks_document"]
