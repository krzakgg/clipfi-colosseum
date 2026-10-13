"""A minimal software WebAuthn authenticator for passkey tests.

Produces real ES256 credentials/assertions (fmt="none" attestation) that pass
py_webauthn's verification, plus the failure shapes the router must reject
(wrong origin, missing user verification, bad challenge, stale sign count).
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import uuid
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDSA,
    SECP256R1,
    EllipticCurvePrivateKey,
    generate_private_key,
)
from webauthn.helpers import bytes_to_base64url

FLAGS_UP = 0x01
FLAGS_UV = 0x04
FLAGS_BE = 0x08  # backup eligible (multi-device / syncable)
FLAGS_BS = 0x10  # currently backed up
FLAGS_AT = 0x40


class SoftAuthenticator:
    """One software credential (ES256 keypair) + ceremony response builders."""

    def __init__(self) -> None:
        self.private_key: EllipticCurvePrivateKey = generate_private_key(SECP256R1())
        self.credential_id: bytes = os.urandom(32)
        self.sign_count: int = 0

    # --- building blocks -------------------------------------------------

    def _cose_key(self) -> dict[int, Any]:
        """Public key as a COSE ES256 map (kty=EC2, alg=-7, crv=P-256)."""
        numbers = self.private_key.public_key().public_numbers()
        return {
            1: 2,  # kty: EC2
            3: -7,  # alg: ES256
            -1: 1,  # crv: P-256
            -2: numbers.x.to_bytes(32, "big"),
            -3: numbers.y.to_bytes(32, "big"),
        }

    def _auth_data(
        self,
        rp_id: str,
        *,
        flags: int,
        sign_count: int,
        include_credential: bool,
        aaguid: str | None = None,
    ) -> bytes:
        data = hashlib.sha256(rp_id.encode()).digest()
        data += bytes([flags])
        data += struct.pack(">I", sign_count)
        if include_credential:
            # AAGUID identifies the authenticator; all zeros = unidentified.
            guid = uuid.UUID(aaguid).bytes if aaguid else b"\x00" * 16
            data += guid
            data += struct.pack(">H", len(self.credential_id))
            data += self.credential_id
            data += cbor2.dumps(self._cose_key())
        return data

    def _client_data(self, type_: str, challenge: bytes, origin: str) -> bytes:
        payload = {
            "type": type_,
            "challenge": bytes_to_base64url(challenge),
            "origin": origin,
            "crossOrigin": False,
        }
        return json.dumps(payload, separators=(",", ":")).encode()

    # --- ceremonies --------------------------------------------------------

    def register(
        self,
        *,
        challenge: bytes,
        rp_id: str,
        origin: str,
        user_verification: bool = True,
        aaguid: str | None = None,
        attachment: str | None = "platform",
        backup_eligible: bool = False,
    ) -> dict[str, Any]:
        """A registration credential (attestation format "none", real key).

        Device-metadata knobs mirror what real browsers report: `aaguid`
        (provider UUID embedded in authenticator data), `attachment`
        (top-level authenticatorAttachment) and `backup_eligible` (BE+BS flags
        → py_webauthn reports the credential as backed up / multi-device).
        """
        flags = FLAGS_UP | FLAGS_AT | (FLAGS_UV if user_verification else 0)
        if backup_eligible:
            flags |= FLAGS_BE | FLAGS_BS
        auth_data = self._auth_data(
            rp_id,
            flags=flags,
            sign_count=self.sign_count,
            include_credential=True,
            aaguid=aaguid,
        )
        attestation_object = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": bytes_to_base64url(self.credential_id),
            "rawId": bytes_to_base64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(self._client_data("webauthn.create", challenge, origin)),
                "attestationObject": bytes_to_base64url(attestation_object),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": attachment,
        }

    def assertion(
        self,
        *,
        challenge: bytes,
        rp_id: str,
        origin: str,
        user_verification: bool = True,
        sign_count: int | None = None,
        corrupt_signature: bool = False,
    ) -> dict[str, Any]:
        """A login assertion signed with the credential's private key."""
        count = self.sign_count + 1 if sign_count is None else sign_count
        flags = FLAGS_UP | (FLAGS_UV if user_verification else 0)
        auth_data = self._auth_data(rp_id, flags=flags, sign_count=count, include_credential=False)
        client_data = self._client_data("webauthn.get", challenge, origin)
        message = auth_data + hashlib.sha256(client_data).digest()
        signature = self.private_key.sign(message, ECDSA(hashes.SHA256()))
        if corrupt_signature:
            signature = signature[:-1] + bytes([signature[-1] ^ 0xFF])
        if sign_count is None:
            self.sign_count = count
        return {
            "id": bytes_to_base64url(self.credential_id),
            "rawId": bytes_to_base64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(signature),
                "userHandle": bytes_to_base64url(b"test-user-handle"),
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
        }
