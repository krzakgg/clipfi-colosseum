from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime

class CompanyBase(BaseModel):
    name: str
    email: EmailStr
    website_url: Optional[str] = None
    logo_url: Optional[str] = None
    description: Optional[str] = None
    industry: Optional[str] = None
    tax_id: Optional[str] = None

class CompanyCreate(CompanyBase):
    password: str = Field(min_length=8)

class CompanyResponse(CompanyBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True