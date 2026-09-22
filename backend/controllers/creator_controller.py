from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import Creator
from schemas import CreatorCreate, CreatorResponse

router = APIRouter(prefix="/api/creators", tags=["creators"])

@router.post("", response_model=CreatorResponse, status_code=status.HTTP_201_CREATED)
async def create_creator(creator: CreatorCreate, db: AsyncSession = Depends(get_db)):
    new_creator = Creator(**creator.model_dump())
    db.add(new_creator)
    await db.commit()
    await db.refresh(new_creator)
    return new_creator