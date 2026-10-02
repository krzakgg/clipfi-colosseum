from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class GameKeyCreate(BaseModel):
    company_id: int
    key_value: str = Field(min_length=1, max_length=500)


class GameKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    key_value: str
    status: str
    assigned_to_creator_id: int | None = None
    assigned_at: datetime | None = None
    created_at: datetime | None = None


class KeyRequestCreate(BaseModel):
    creator_id: int
    message: str | None = None


class KeyRequestStatusUpdate(BaseModel):
    company_id: int
    status: str
    reviewer_feedback: str | None = None


class KeyRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    campaign_id: int
    creator_id: int
    game_key_id: int | None = None
    status: str
    message: str | None = None
    reviewer_feedback: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    key_value: str | None = None
