from typing import List
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from database import get_db
from models import CampaignApplication
from schemas import ApplicationCreate, ApplicationStatusUpdate, ApplicationResponse

router = APIRouter(prefix="/api/applications", tags=["applications"])

# 1. Twórca składa aplikację do kampanii
@router.post("", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
async def create_application(app_data: ApplicationCreate, db: AsyncSession = Depends(get_db)):
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
async def get_campaign_applications(campaign_id: int, db: AsyncSession = Depends(get_db)):
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

    app.status = status_data.status
    app.feedback = status_data.feedback
    app.reviewed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(app)
    return app