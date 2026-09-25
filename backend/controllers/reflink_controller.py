import logging
from decimal import Decimal
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from database import get_db
from models import Campaign, CampaignApplication, CampaignRefLink
from models.application import ApplicationStatus
from schemas import CampaignRefLinkCreate, CampaignRefLinkResponse
from tracking_client import (
    UNAVAILABLE_DETAIL,
    ClickTotals,
    TrackingClient,
    TrackingError,
    TrackingRejected,
    TrackingUnavailable,
    get_tracking,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reflinks", tags=["ref-links"])

Tracking = Annotated[TrackingClient, Depends(get_tracking)]


@router.post("", response_model=CampaignRefLinkResponse, status_code=status.HTTP_201_CREATED)
async def create_ref_link(payload: CampaignRefLinkCreate, tracking: Tracking, db: AsyncSession = Depends(get_db)):
    campaign = await db.get(Campaign, payload.campaign_id, with_for_update=True)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")
    if campaign.company_id != payload.company_id:
        raise HTTPException(status_code=403, detail="Nie możesz tworzyć reflinków dla tej kampanii")

    accepted = await db.scalar(
        select(CampaignApplication.id).where(
            CampaignApplication.campaign_id == campaign.id,
            CampaignApplication.creator_id == payload.creator_id,
            CampaignApplication.status == ApplicationStatus.ACCEPTED,
        )
    )
    if accepted is None:
        raise HTTPException(status_code=409, detail="Reflink można wygenerować tylko dla twórcy przyjętego do kampanii")

    existing = await db.scalar(
        select(CampaignRefLink.id).where(
            CampaignRefLink.campaign_id == campaign.id,
            CampaignRefLink.creator_id == payload.creator_id,
        )
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Twórca ma już reflink w tej kampanii")

    target_url = str(payload.url)
    try:
        code = await tracking.create_link(
            campaign_id=campaign.id,
            creator_id=payload.creator_id,
            target_url=target_url,
            starts_at=campaign.start_date,
            ends_at=campaign.end_date,
        )
    except TrackingRejected as exc:
        raise HTTPException(status_code=422, detail=exc.detail) from exc
    except TrackingUnavailable as exc:
        log.error("creating a tracking link failed: %s", exc)
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from exc

    ref_link = CampaignRefLink(campaign_id=campaign.id, creator_id=payload.creator_id, url=target_url, code=code)
    db.add(ref_link)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        try:
            await tracking.deactivate_link(code)
        except TrackingError as exc:
            log.error("orphaned tracking link %s could not be deactivated: %s", code, exc)
        raise
    await db.refresh(ref_link)
    return _response(ref_link, campaign, ClickTotals(raw=0, unique=0), tracking)


@router.get("/campaign/{campaign_id}", response_model=List[CampaignRefLinkResponse])
async def get_campaign_ref_links(
    campaign_id: int,
    company_id: int,
    tracking: Tracking,
    db: AsyncSession = Depends(get_db),
):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")
    if campaign.company_id != company_id:
        raise HTTPException(status_code=403, detail="Nie masz dostępu do reflinków tej kampanii")

    result = await db.execute(
        select(CampaignRefLink)
        .where(CampaignRefLink.campaign_id == campaign_id)
        .order_by(CampaignRefLink.created_at.desc())
    )
    links = result.scalars().all()
    totals: dict[str, ClickTotals] = {}
    if links:
        try:
            totals = await tracking.campaign_totals(campaign_id)
        except TrackingError as exc:
            log.warning("click totals for campaign %s unavailable: %s", campaign_id, exc)
    return [_response(link, campaign, totals.get(link.code), tracking) for link in links]


@router.get("/{code}", response_model=CampaignRefLinkResponse)
async def get_ref_link(code: str, tracking: Tracking, db: AsyncSession = Depends(get_db)):
    ref_link = await db.scalar(select(CampaignRefLink).where(CampaignRefLink.code == code))
    if not ref_link:
        raise HTTPException(status_code=404, detail="Reflink nie istnieje")
    campaign = await db.get(Campaign, ref_link.campaign_id)
    try:
        totals = await tracking.link_totals(code)
    except TrackingError as exc:
        log.warning("click totals for %s unavailable: %s", code, exc)
        totals = None
    return _response(ref_link, campaign, totals, tracking)


def _response(
    link: CampaignRefLink, campaign: Campaign, totals: ClickTotals | None, tracking: TrackingClient
) -> CampaignRefLinkResponse:
    click_payout = None
    if totals is not None:
        click_payout = Decimal(totals.unique) * (campaign.payout_per_click or Decimal("0"))
        if campaign.budget_per_creator:
            click_payout = min(click_payout, campaign.budget_per_creator)
        click_payout = click_payout.quantize(Decimal("0.01"))
    return CampaignRefLinkResponse(
        id=link.id,
        campaign_id=link.campaign_id,
        creator_id=link.creator_id,
        code=link.code,
        url=link.url,
        public_url=tracking.public_url(link.code),
        clicks_count=None if totals is None else totals.unique,
        raw_clicks=None if totals is None else totals.raw,
        click_payout=click_payout,
        created_at=link.created_at,
    )
