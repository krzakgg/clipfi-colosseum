"""Auth service FastAPI dependencies.

Auth verifies its own JWTs using the public key (it has it). Other services
verify via `waggi_shared.security.TokenVerifier` + JWKS — that path is NOT used
here.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any

import jwt
from fastapi import Depends, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from waggi_auth.config import settings
from waggi_auth.models import AccountType, User
from waggi_auth.security.keys import get_public_key
from waggi_shared.database import engine_for, sessionmaker_for
from waggi_shared.database import get_session as _get_session
from waggi_shared.errors import ForbiddenError, UnauthorizedError

_engine = engine_for(settings.database_url, "auth")
_SessionLocal = sessionmaker_for(_engine)

# Declared via HTTPBearer (not manual header parsing) so FastAPI registers an
# OpenAPI security scheme: Swagger UI then shows the Authorize button and the
# padlocks on protected routes. Paste the access token WITHOUT the "Bearer "
# prefix — the UI adds it.
bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Access token from POST /api/v1/auth/login",
)


async def get_db() -> AsyncGenerator[AsyncSession]:
    async for session in _get_session(_SessionLocal):
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract + verify the bearer JWT, returning the active User row.

    Raises UnauthorizedError for missing/invalid/expired tokens or inactive users.
    """
    if credentials is None:
        raise UnauthorizedError(detail="Missing bearer token", code="missing_token")
    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            _public_pem(),
            algorithms=["RS256"],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedError(detail="Invalid or expired token", code="invalid_token") from exc

    user_id = _parse_uuid(payload.get("sub"))
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError(detail="User not found or inactive", code="account_inactive")
    return user


def require_account_types(*account_types: AccountType) -> Any:
    """Dependency factory enforcing that the caller has one of `account_types`."""

    async def _checker(user: User = Depends(get_current_user)) -> User:
        if user.account_type not in account_types:
            raise ForbiddenError(detail="Insufficient account type", code="account_type_required")
        return user

    return _checker


def _public_pem() -> str:
    from cryptography.hazmat.primitives import serialization

    return (
        get_public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )


def _parse_uuid(raw: object) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError) as exc:
        raise UnauthorizedError(detail="Invalid subject in token", code="invalid_token") from exc


__all__ = ["get_current_user", "get_db", "require_account_types"]
