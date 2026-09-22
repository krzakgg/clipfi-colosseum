from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from models import Company
from schemas import CompanyCreate, CompanyResponse

router = APIRouter(prefix="/api/companies", tags=["companies"])

@router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
async def create_company(company: CompanyCreate, db: AsyncSession = Depends(get_db)):
    new_company = Company(**company.model_dump())
    db.add(new_company)
    await db.commit()
    await db.refresh(new_company)
    return new_company