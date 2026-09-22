from pydantic import BaseModel, HttpUrl
from typing import Optional
from decimal import Decimal
from datetime import datetime
from models import CampaignSubmissionStatus, CampaignPayoutStatus

# 1. Twórca zgłasza wideo
class CampaignSubmissionCreate(BaseModel):
    campaign_id: int
    video_url: str
    platform: str
    content_type: str

# 2. Firma akceptuje/odrzuca materiał
class CampaignSubmissionReview(BaseModel):
    status: CampaignSubmissionStatus
    feedback: Optional[str] = None

# 3. Aktualizacja statystyk i przeliczenie kwoty do wypłaty
class CampaignSubmissionMetricsUpdate(BaseModel):
    views_count: int
    clicks_count: int

# 4. Zmiana statusu wypłaty
class CampaignSubmissionPayoutUpdate(BaseModel):
    payout_status: CampaignPayoutStatus
    paid_amount: Decimal

# 5. Pełna odpowiedź API
class CampaignSubmissionResponse(BaseModel):
    id: int
    campaign_id: int
    creator_id: int
    video_url: str
    platform: str
    content_type: str
    status: CampaignSubmissionStatus
    feedback: Optional[str]
    views_count: int
    clicks_count: int
    payout_status: CampaignPayoutStatus
    calculated_payout: Decimal
    paid_amount: Optional[Decimal]
    created_at: datetime

    class Config:
        from_attributes = True