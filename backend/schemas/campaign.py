from pydantic import BaseModel, HttpUrl
from typing import Optional, Dict, List
from decimal import Decimal
from datetime import datetime

class CampaignBase(BaseModel):
    title: str
    description: Optional[str] = None
    is_private: bool = False
    
    product_description: Optional[str] = None
    press_kit_url: Optional[str] = None
    brand_guidelines: Optional[str] = None

    total_budget: Decimal
    budget_per_creator: Optional[Decimal] = None
    budget_per_time_unit: Optional[Decimal] = None
    budget_per_language: Optional[Dict[str, Decimal]] = None

    languages: Optional[List[str]] = None
    max_videos_per_creator: Optional[int] = None
    max_submissions_per_day: Optional[int] = None

    min_views: int = 0
    min_subscribers: int = 0
    platform_requirements: Optional[Dict[str, Dict[str, int]]] = None

    payout_by_content_type: Optional[Dict[str, Decimal]] = None
    payout_per_views: Optional[Decimal] = None
    views_unit_step: int = 1000
    payout_per_click: Optional[Decimal] = None

    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    rollover_remaining_budget: bool = False

class CampaignCreate(CampaignBase):
    pass

class CampaignResponse(CampaignBase):
    id: int
    completed: bool

    class Config:
        from_attributes = True