import asyncio
import logging

from sqlalchemy import select

from database import AsyncSessionLocal
from models import Campaign, CampaignRefLink
from settings import get_settings
from tracking_client import TrackingClient, TrackingError

log = logging.getLogger(__name__)


async def backfill(tracking: TrackingClient) -> int:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    CampaignRefLink.code,
                    CampaignRefLink.creator_id,
                    CampaignRefLink.url,
                    Campaign.id,
                    Campaign.start_date,
                    Campaign.end_date,
                ).join(Campaign, CampaignRefLink.campaign_id == Campaign.id)
            )
        ).all()

    registered = 0
    for code, creator_id, url, campaign_id, starts_at, ends_at in rows:
        try:
            await tracking.update_link(
                code, campaign_id=campaign_id, creator_id=creator_id, target_url=url, starts_at=starts_at, ends_at=ends_at
            )
        except TrackingError as exc:
            log.error("reflink %s could not be registered: %s", code, exc)
            continue
        registered += 1
    return registered


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    tracking = TrackingClient(
        settings.tracking_internal_url,
        settings.tracking_service_token.get_secret_value(),
        settings.tracking_redirect_base,
        timeout=settings.tracking_timeout,
    )
    try:
        registered = await backfill(tracking)
    finally:
        await tracking.aclose()
    log.info("registered %d reflink(s) with the tracking service", registered)


if __name__ == "__main__":
    asyncio.run(main())
