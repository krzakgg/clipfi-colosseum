"""JWKS endpoint — exposes auth's public signing keys at the well-known root URL.

This is the cross-service trust root: admin + bookings fetch it to verify the
RS256 JWTs auth issues. It is mounted at the app ROOT (``/.well-known/jwks.json``),
NOT under ``/api/v1`` — RFC 8615 well-known URIs live at the origin root by
convention, and the JWKS consumers (``JWKS_URL`` in .env / docker-compose) point
here. Mounting it inside the ``/api/v1`` router would put it at
``/api/v1/.well-known/jwks.json`` and break verification across services.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from waggi_auth.security.keys import jwks_document

router = APIRouter(tags=["jwks"])


@router.get("/.well-known/jwks.json", include_in_schema=False)
async def jwks() -> dict[str, Any]:
    """Public signing keys — the cross-service trust root (admin + bookings)."""
    return jwks_document()


__all__ = ["router"]
