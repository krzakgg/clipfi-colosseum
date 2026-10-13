"""Generate the RS256 keypair used to sign waggi auth JWTs.

Usage (from auth-service/):
    python scripts/generate_keys.py [output_dir]

Writes auth_private.pem / auth_public.pem (2048-bit RSA, PKCS#8) to the
output dir (default: ./keys). Keep the private key out of git.
"""

from __future__ import annotations

import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main() -> None:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("keys")
    out_dir.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    private_path = out_dir / "auth_private.pem"
    private_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

    public_path = out_dir / "auth_public.pem"
    public_path.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )

    print(f"Wrote {private_path} and {public_path}")


if __name__ == "__main__":
    main()
