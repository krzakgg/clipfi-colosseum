from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from database import get_db
from models import Creator
from schemas import CreatorCreate, CreatorResponse
from security import hash_password

router = APIRouter(prefix="/api/creators", tags=["creators"])

@router.post("", response_model=CreatorResponse, status_code=status.HTTP_201_CREATED)
async def create_creator(creator: CreatorCreate, db: AsyncSession = Depends(get_db)):
    creator_data = creator.model_dump()
    password = creator_data.pop("password")
    new_creator = Creator(**creator_data, password_hash=hash_password(password))
    db.add(new_creator)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Twórca z tym e-mailem lub username już istnieje")
    await db.refresh(new_creator)
    return new_creator