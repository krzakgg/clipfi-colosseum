from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, HttpUrl, field_validator

MAX_URL_LENGTH = 500


class CampaignRefLinkCreate(BaseModel):
    campaign_id: int
    creator_id: int
    company_id: int
    url: HttpUrl

    @field_validator("url")
    @classmethod
    def _fits_the_column(cls, value: HttpUrl) -> HttpUrl:
        if len(str(value)) > MAX_URL_LENGTH:
            raise ValueError(f"adres po zakodowaniu nie może mieć więcej niż {MAX_URL_LENGTH} znaków")
        return value


class CampaignRefLinkResponse(BaseModel):
    id: int
    campaign_id: int
    creator_id: int
    code: str
    url: HttpUrl
    public_url: str
    clicks_count: int | None
    raw_clicks: int | None
    click_payout: Decimal | None
    created_at: datetime | None = None
