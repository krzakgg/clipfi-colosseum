"""Session token issuance shared by all login flows (password, MFA step, passkey).

Kept out of the routers so any login flow (session, passkey, SSO) can issue
tokens without importing a router module.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from typing import cast as typing_cast

from sqlalchemy import CursorResult, update
from sqlalchemy.ext.asyncio import AsyncSession

from waggi_auth.models import RefreshToken, User
from waggi_auth.schemas import SetupRequiredResponse, TokenResponse
from waggi_auth.security.signing import create_access_token, create_refresh_token, create_setup_token
from waggi_shared.errors import UnauthorizedError


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


async def issue_tokens(
    user: User,
    db: AsyncSession,
    *,
    family_id: uuid.UUID | None = None,
    replaced_token_id: uuid.UUID | None = None,
) -> TokenResponse:
    """Issue an access + refresh token pair, persisting the refresh token hash.

    Login flows call this without the keyword extras — each login starts a
    FRESH token family. The refresh endpoint passes `family_id` (inherit the
    rotating family) and `replaced_token_id` (the token being rotated away):
    the replacement row is inserted and the old row's revocation (with
    replaced_by_id, the L7 theft-signal marker) happen in ONE atomic commit.
    If a concurrent refresh already revoked the old row, the conditional
    UPDATE matches nothing: the whole transaction rolls back (no orphan
    replacement token) and the caller gets a 401 — exactly one winner.
    """
    access, ttl = create_access_token(
        user_id=user.id, email=user.email, full_name=user.full_name, account_type=user.account_type.value
    )
    raw_refresh, refresh_hash, issued_at, expires_at = create_refresh_token()
    new_id = uuid.uuid4()
    db.add(
        RefreshToken(
            id=new_id,
            user_id=user.id,
            token_hash=refresh_hash,
            issued_at=issued_at,
            expires_at=expires_at,
            family_id=family_id or uuid.uuid4(),
        )
    )
    if replaced_token_id is not None:
        # Autoflush runs the pending INSERT first; the UPDATE then revokes the
        # old row only if it is still live. Both land in the same commit.
        revoke = typing_cast(
            "CursorResult[Any]",
            await db.execute(
                update(RefreshToken)
                .where(RefreshToken.id == replaced_token_id, RefreshToken.revoked_at.is_(None))
                .values(revoked_at=_utcnow(), replaced_by_id=new_id)
                .execution_options(synchronize_session=False)
            ),
        )
        if revoke.rowcount != 1:
            await db.rollback()
            raise UnauthorizedError(detail="Refresh token expired or revoked", code="refresh_token_revoked")
    await db.commit()
    return TokenResponse(access_token=access, refresh_token=raw_refresh, expires_in=ttl)


async def issue_tokens_or_setup(user: User, db: AsyncSession) -> TokenResponse | SetupRequiredResponse:
    """Login-flow issuance with the forced-password-setup gate.

    While `must_set_password` is set (account created with a temp/absent
    password, or admin reset), login must NOT hand out session tokens — the
    shared temp password would then work against every API. Instead a
    single-use setup token is returned, exchangeable only at
    POST /setup-password. Refresh rotation keeps calling `issue_tokens`
    directly: it is not a login, and a gated user never holds a refresh
    token to rotate in the first place.
    """
    if user.must_set_password:
        setup_token, ttl = create_setup_token(user_id=user.id)
        return SetupRequiredResponse(setup_token=setup_token, expires_in=ttl)
    return await issue_tokens(user, db)


__all__ = ["issue_tokens", "issue_tokens_or_setup"]
