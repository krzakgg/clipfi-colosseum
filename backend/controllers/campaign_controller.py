import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import JSON
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from database import get_db
from models import Campaign, CampaignRefLink
from schemas import CampaignCreate, CampaignResponse
from tracking_client import (
    UNAVAILABLE_DETAIL,
    TrackingClient,
    TrackingError,
    TrackingRejected,
    get_tracking,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])

Tracking = Annotated[TrackingClient, Depends(get_tracking)]

JSON_COLUMNS = frozenset(column.name for column in Campaign.__table__.columns if isinstance(column.type, JSON))


@dataclass(frozen=True)
class TrackedLink:
    code: str
    creator_id: int
    url: str


Window = tuple[datetime | None, datetime | None]


def _column_values(payload: CampaignCreate) -> dict:
    values = payload.model_dump(exclude=JSON_COLUMNS)
    values.update(payload.model_dump(mode="json", include=JSON_COLUMNS))
    return values


@router.get("", response_model=List[CampaignResponse])
async def get_campaigns(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign))
    return result.scalars().all()


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(payload: CampaignCreate, db: AsyncSession = Depends(get_db)):
    new_campaign = Campaign(**_column_values(payload))
    db.add(new_campaign)
    await db.commit()
    await db.refresh(new_campaign)
    return new_campaign


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(campaign_id: int, db: AsyncSession = Depends(get_db)):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")
    return campaign


@router.put("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: int,
    campaign_data: CampaignCreate,
    tracking: Tracking,
    db: AsyncSession = Depends(get_db),
):
    campaign = await db.get(Campaign, campaign_id, with_for_update=True)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")

    old_window = (campaign.start_date, campaign.end_date)
    links = await _tracked_links(db, campaign_id)
    for key, value in _column_values(campaign_data).items():
        setattr(campaign, key, value)
    new_window = (campaign.start_date, campaign.end_date)

    if new_window != old_window and links:
        await db.flush()
        moved: list[TrackedLink] = []
        try:
            for link in links:
                await _put_window(tracking, campaign_id, link, new_window)
                moved.append(link)
        except TrackingError as exc:
            await db.rollback()
            await _restore_windows(tracking, campaign_id, moved, old_window)
            raise _tracking_http_error(exc, "reflink windows of campaign %s could not be moved", campaign_id) from exc

    await db.commit()
    await db.refresh(campaign)
    return campaign


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(campaign_id: int, tracking: Tracking, db: AsyncSession = Depends(get_db)):
    campaign = await db.get(Campaign, campaign_id, with_for_update=True)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")

    window = (campaign.start_date, campaign.end_date)
    links = await _tracked_links(db, campaign_id)
    await db.delete(campaign)
    await db.flush()

    deactivated: list[TrackedLink] = []
    try:
        for link in links:
            await tracking.deactivate_link(link.code)
            deactivated.append(link)
    except TrackingError as exc:
        await db.rollback()
        await _restore_windows(tracking, campaign_id, deactivated, window)
        log.error("reflinks of campaign %s could not be deactivated: %s", campaign_id, exc)
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from exc

    await db.commit()
    return None


async def _tracked_links(db: AsyncSession, campaign_id: int) -> list[TrackedLink]:
    rows = await db.execute(
        select(CampaignRefLink.code, CampaignRefLink.creator_id, CampaignRefLink.url).where(
            CampaignRefLink.campaign_id == campaign_id
        )
    )
    return [TrackedLink(code=code, creator_id=creator_id, url=url) for code, creator_id, url in rows.all()]


async def _put_window(tracking: TrackingClient, campaign_id: int, link: TrackedLink, window: Window) -> None:
    await tracking.update_link(
        link.code,
        campaign_id=campaign_id,
        creator_id=link.creator_id,
        target_url=link.url,
        starts_at=window[0],
        ends_at=window[1],
    )


async def _restore_windows(tracking: TrackingClient, campaign_id: int, links: list[TrackedLink], window: Window) -> None:
    for link in links:
        try:
            await _put_window(tracking, campaign_id, link, window)
        except TrackingError as exc:
            log.error("reflink %s of campaign %s is out of sync with the campaign: %s", link.code, campaign_id, exc)


def _tracking_http_error(exc: TrackingError, message: str, campaign_id: int) -> HTTPException:
    if isinstance(exc, TrackingRejected):
        return HTTPException(status_code=422, detail=exc.detail)
    log.error(message + ": %s", campaign_id, exc)
    return HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL)
