from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime

class CreatorBase(BaseModel):
    username: str
    full_name: Optional[str] = None
    email: EmailStr
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    languages: Optional[List[str]] = None
    categories: Optional[List[str]] = None
    platform_stats: Optional[Dict[str, Any]] = None

class CreatorCreate(CreatorBase):
    pass

class CreatorResponse(CreatorBase):
    id: int
    is_verified: bool
    rating: float
    created_at: datetime

    class Config:
        from_attributes = True