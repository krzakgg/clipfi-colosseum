"""Tests for token issuance (issue_tokens persists the refresh hash)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from waggi_auth.models import RefreshToken
from waggi_auth.tokens import issue_tokens
from waggi_shared.errors import UnauthorizedError


async def test_issue_tokens_persists_refresh_hash(db, make_user) -> None:
    user = await make_user()
    response = await issue_tokens(user, db)

    assert response.access_token and response.refresh_token
    assert response.token_type == "Bearer"
    assert response.expires_in > 0

    rows = (await db.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.token_hash == hashlib.sha256(response.refresh_token.encode()).hexdigest()
    assert row.token_hash != response.refresh_token  # never the raw token
    assert row.revoked_at is None
    assert row.replaced_by_id is None
    assert row.expires_at > row.issued_at


async def test_issue_tokens_multiple_sessions(db, make_user) -> None:
    user = await make_user()
    first = await issue_tokens(user, db)
    second = await issue_tokens(user, db)
    assert first.refresh_token != second.refresh_token
    rows = (await db.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))).scalars().all()
    assert len(rows) == 2


async def test_issue_tokens_fresh_logins_start_separate_families(db, make_user) -> None:
    """Without the keyword extras every issuance mints a NEW family."""
    user = await make_user()
    await issue_tokens(user, db)
    await issue_tokens(user, db)
    rows = (await db.execute(select(RefreshToken).where(RefreshToken.user_id == user.id))).scalars().all()
    assert len(rows) == 2
    assert rows[0].family_id != rows[1].family_id


async def test_issue_tokens_rotation_atomic_and_marks_replacement(db, make_user) -> None:
    """Rotation: replacement inherits the family; the old row is revoked with
    replaced_by_id pointing at its successor — in the same commit."""
    user = await make_user()
    first = await issue_tokens(user, db)
    old_row = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hashlib.sha256(first.refresh_token.encode()).hexdigest())
        )
    ).scalar_one()

    second = await issue_tokens(user, db, family_id=old_row.family_id, replaced_token_id=old_row.id)
    # The Core UPDATE bypasses the identity map (synchronize_session=False)
    # and expire_on_commit=False keeps the stale in-memory object — refresh to
    # see the DB truth.
    await db.refresh(old_row)
    new_row = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hashlib.sha256(second.refresh_token.encode()).hexdigest())
        )
    ).scalar_one()

    assert new_row.family_id == old_row.family_id  # family inherited
    assert old_row.revoked_at is not None
    assert old_row.replaced_by_id == new_row.id  # theft-signal marker
    assert new_row.revoked_at is None


async def test_issue_tokens_rotation_lost_race_rolls_back(db, make_user) -> None:
    """If the old row was already revoked (concurrent rotation won), the
    replacement insert rolls back — no orphan token survives."""
    user = await make_user()
    first = await issue_tokens(user, db)
    old_row = (
        await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hashlib.sha256(first.refresh_token.encode()).hexdigest())
        )
    ).scalar_one()
    # Simulate the concurrent winner: revoke out-of-band, then rotate.
    old_row.revoked_at = datetime.now(tz=UTC)
    await db.commit()

    user_id = user.id  # capture: the rollback below expires all ORM objects
    with pytest.raises(UnauthorizedError):
        await issue_tokens(user, db, family_id=old_row.family_id, replaced_token_id=old_row.id)

    rows = (await db.execute(select(RefreshToken).where(RefreshToken.user_id == user_id))).scalars().all()
    assert len(rows) == 1  # the loser's insert was rolled back
    assert rows[0].replaced_by_id is None
