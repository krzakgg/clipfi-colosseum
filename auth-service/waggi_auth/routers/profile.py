"""Profile self-service endpoints: GET/PATCH /auth/me."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from waggi_auth.dependencies import get_current_user, get_db
from waggi_auth.models import User
from waggi_auth.schemas import UpdateMeRequest, UserOut

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/me", response_model=UserOut)
async def me(current: User = Depends(get_current_user)) -> User:
    return current


@router.patch("/me", response_model=UserOut)
async def update_me(
    body: UpdateMeRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Self-service profile edit. Email and account_type are read-only."""
    current.full_name = body.full_name
    current.phone = body.phone
    await db.commit()
    await db.refresh(current)
    return current


__all__ = ["router"]
