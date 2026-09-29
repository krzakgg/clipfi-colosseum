from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, List
from decimal import Decimal
from datetime import datetime, timezone
from models.campaign import CampaignStatus

class CampaignBase(BaseModel):
    company_id: int
    title: str
    description: Optional[str] = None
    status: CampaignStatus = CampaignStatus.DRAFT
    is_private: bool = False
    cover_image_url: Optional[str] = None
    gallery_image_urls: Optional[List[str]] = None
    social_media_links: Optional[Dict[str, str]] = None
    
    product_description: Optional[str] = None
    press_kit_url: Optional[str] = None
    brand_guidelines: Optional[str] = None

    total_budget: Decimal = Field(ge=0, le=9999999999.99)
    budget_per_creator: Optional[Decimal] = Field(default=None, ge=0, le=99999999.99)
    budget_per_time_unit: Optional[Decimal] = Field(default=None, ge=0, le=99999999.99)
    budget_per_language: Optional[Dict[str, Decimal]] = None

    languages: Optional[List[str]] = None
    max_videos_per_creator: Optional[int] = None
    max_submissions_per_day: Optional[int] = None

    min_views: int = 0
    min_subscribers: int = 0
    platform_requirements: Optional[Dict[str, Dict[str, int]]] = None

    payout_by_content_type: Optional[Dict[str, Decimal]] = None
    payout_per_views: Optional[Decimal] = Field(default=None, ge=0, le=99999999.99)
    views_unit_step: int = 1000
    payout_per_click: Optional[Decimal] = Field(default=None, ge=0, le=99999999.99)

    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    rollover_remaining_budget: bool = False

    @field_validator("start_date", "end_date")
    @classmethod
    def _utc_when_naive(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

class CampaignCreate(CampaignBase):
    pass

class CampaignResponse(CampaignBase):
    id: int
    completed: bool

    class Config:
        from_attributes = True