from pydantic import BaseModel, HttpUrl, ConfigDict
from datetime import datetime

# 1. Tworzymy nowy reflink dla kampanii
class CampaignRefLinkCreate(BaseModel):
    campaign_id: int
    creator_id: int
    company_id: int
    url: HttpUrl


class CampaignRefLinkResponse(BaseModel):
    id: int
    campaign_id: int
    creator_id: int
    code: str
    url: HttpUrl
    clicks_count: int
    created_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)