from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Company, Creator
from schemas.auth import LoginRequest
from schemas.company import CompanyResponse
from schemas.creator import CreatorResponse
from security import verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
async def login(credentials: LoginRequest, db: AsyncSession = Depends(get_db)):
    login_value = credentials.login.strip().lower()

    if credentials.account_type == "company":
        result = await db.execute(select(Company).where(Company.email == login_value))
        account = result.scalar_one_or_none()
        response_model = CompanyResponse
    else:
        result = await db.execute(
            select(Creator).where(
                or_(Creator.email == login_value, Creator.username == credentials.login.strip())
            )
        )
        account = result.scalar_one_or_none()
        response_model = CreatorResponse

    if not account or not verify_password(credentials.password, account.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nieprawidłowy login lub hasło",
        )

    return {
        "account_type": credentials.account_type,
        "user": response_model.model_validate(account).model_dump(mode="json"),
    }