import secrets
import string
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from database import get_db
from models import Campaign, CampaignRefLink, Creator
from schemas import CampaignRefLinkCreate, CampaignRefLinkResponse

router = APIRouter(tags=["ref-links"])
CODE_ALPHABET = string.ascii_letters + string.digits


def generate_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(12))


@router.post(
    "/api/reflinks",
    response_model=CampaignRefLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_ref_link(
    payload: CampaignRefLinkCreate,
    db: AsyncSession = Depends(get_db),
):
    campaign = await db.get(Campaign, payload.campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")

    if campaign.company_id != payload.company_id:
        raise HTTPException(status_code=403, detail="Nie możesz tworzyć reflinków dla tej kampanii")

    creator = await db.get(Creator, payload.creator_id)
    if not creator:
        raise HTTPException(status_code=404, detail="Twórca nie istnieje")

    for _ in range(5):
        code = generate_code()
        existing = await db.execute(
            select(CampaignRefLink.id).where(CampaignRefLink.code == code)
        )
        if existing.scalar_one_or_none() is None:
            break
    else:
        raise HTTPException(status_code=503, detail="Nie udało się wygenerować reflinka")

    ref_link = CampaignRefLink(
        campaign_id=payload.campaign_id,
        creator_id=payload.creator_id,
        url=str(payload.url),
        code=code,
    )
    db.add(ref_link)
    await db.commit()
    await db.refresh(ref_link)
    return ref_link


@router.get("/api/reflinks/{code}", response_model=CampaignRefLinkResponse)
async def get_ref_link(code: str, db: AsyncSession = Depends(get_db)):
    ref_link = await db.scalar(
        select(CampaignRefLink).where(CampaignRefLink.code == code)
    )
    if not ref_link:
        raise HTTPException(status_code=404, detail="Reflink nie istnieje")
    return ref_link


@router.get("/api/reflinks/campaign/{campaign_id}", response_model=List[CampaignRefLinkResponse])
async def get_campaign_ref_links(
    campaign_id: int,
    company_id: int,
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
    return result.scalars().all()


@router.get("/r/{code}", include_in_schema=False)
async def redirect_ref_link(code: str, db: AsyncSession = Depends(get_db)):
    ref_link = await db.scalar(
        select(CampaignRefLink).where(CampaignRefLink.code == code)
    )
    if not ref_link:
        raise HTTPException(status_code=404, detail="Reflink nie istnieje")

    await db.execute(
        update(CampaignRefLink)
        .where(CampaignRefLink.id == ref_link.id)
        .values(clicks_count=CampaignRefLink.clicks_count + 1)
    )
    await db.commit()
    return RedirectResponse(url=ref_link.url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)