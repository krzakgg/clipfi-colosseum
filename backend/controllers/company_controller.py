from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from database import get_db
from models import Company
from schemas import CompanyCreate, CompanyResponse
from security import hash_password

router = APIRouter(prefix="/api/companies", tags=["companies"])

@router.get("", response_model=List[CompanyResponse])
async def get_companies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Company).order_by(Company.name))
    return result.scalars().all()

@router.post("", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
async def create_company(company: CompanyCreate, db: AsyncSession = Depends(get_db)):
    company_data = company.model_dump()
    password = company_data.pop("password")
    new_company = Company(**company_data, password_hash=hash_password(password))
    db.add(new_company)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Firma z tym adresem e-mail już istnieje")
    await db.refresh(new_company)
    return new_company