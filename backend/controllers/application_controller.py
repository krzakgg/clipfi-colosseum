from typing import List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from database import get_db
from models import Campaign, CampaignApplication, Company, Creator
from schemas import ApplicationCreate, ApplicationStatusUpdate, ApplicationResponse

router = APIRouter(prefix="/api/applications", tags=["applications"])

# 1. Twórca składa aplikację do kampanii
@router.post("", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
async def create_application(app_data: ApplicationCreate, db: AsyncSession = Depends(get_db)):
    campaign = await db.get(Campaign, app_data.campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")

    creator = await db.get(Creator, app_data.creator_id)
    if not creator:
        raise HTTPException(status_code=404, detail="Twórca nie istnieje")

    # Sprawdzenie czy twórca nie złożył już zgłoszenia do tej samej kampanii
    existing = await db.execute(
        select(CampaignApplication).where(
            CampaignApplication.campaign_id == app_data.campaign_id,
            CampaignApplication.creator_id == app_data.creator_id
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=400, 
            detail="Aplikowałeś już do tej kampanii."
        )

    new_app = CampaignApplication(**app_data.model_dump())
    db.add(new_app)
    await db.commit()
    await db.refresh(new_app)
    return new_app

# 2. Marka pobiera listę zgłoszeń dla danej kampanii
@router.get("/campaign/{campaign_id}", response_model=List[ApplicationResponse])
async def get_campaign_applications(
    campaign_id: int,
    company_id: int,
    db: AsyncSession = Depends(get_db)
):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")
    if campaign.company_id != company_id:
        raise HTTPException(status_code=403, detail="Nie masz dostępu do zgłoszeń tej kampanii")

    result = await db.execute(
        select(CampaignApplication)
        .where(CampaignApplication.campaign_id == campaign_id)
        .order_by(CampaignApplication.created_at.desc())
    )
    return result.scalars().all()

# 3. Marka akceptuje lub odrzuca zgłoszenie (oraz dodaje uwagi)
@router.patch("/{application_id}/status", response_model=ApplicationResponse)
async def update_application_status(
    application_id: int,
    status_data: ApplicationStatusUpdate,
    db: AsyncSession = Depends(get_db)
):
    app = await db.get(CampaignApplication, application_id)
    if not app:
        raise HTTPException(status_code=404, detail="Zgłoszenie nie istnieje")

    campaign = await db.get(Campaign, app.campaign_id)
    company = await db.get(Company, status_data.company_id)
    if not company or campaign.company_id != company.id:
        raise HTTPException(status_code=403, detail="Nie możesz oceniać tego zgłoszenia")
    if status_data.status not in ("accepted", "rejected"):
        raise HTTPException(status_code=400, detail="Nieprawidłowy status decyzji")

    app.status = status_data.status
    app.feedback = status_data.feedback
    app.reviewed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(app)
    return app