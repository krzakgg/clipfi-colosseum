from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from decimal import Decimal
from models.application import ApplicationStatus

# Dane wejściowe do złożenia aplikacji przez twórcę
class ApplicationCreate(BaseModel):
    campaign_id: int
    creator_id: int
    pitch: Optional[str] = None
    proposed_rate: Optional[Decimal] = None
    proposed_content_type: Optional[str] = None  # np. "Short", "LongVideo"

# Dane do decyzji marki (akceptacja / odrzucenie)
class ApplicationStatusUpdate(BaseModel):
    status: ApplicationStatus  # ACCEPTED lub REJECTED
    feedback: Optional[str] = None
    company_id: int

# Odpowiedź z API
class ApplicationResponse(BaseModel):
    id: int
    campaign_id: int
    creator_id: int
    status: ApplicationStatus
    pitch: Optional[str] = None
    proposed_rate: Optional[Decimal] = None
    proposed_content_type: Optional[str] = None
    feedback: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime
    creator_username: Optional[str] = None
    creator_full_name: Optional[str] = None
    creator_avatar_url: Optional[str] = None
    creator_languages: Optional[list[str]] = None
    creator_platform_stats: Optional[dict] = None

    class Config:
        from_attributes = True