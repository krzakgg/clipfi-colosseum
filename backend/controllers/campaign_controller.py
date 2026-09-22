from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from database import get_db
from models import Campaign
from schemas import CampaignCreate, CampaignResponse

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


# 1. Pobieranie listy wszystkich kampanii (GET /api/campaigns)
@router.get("", response_model=List[CampaignResponse])
async def get_campaigns(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Campaign))
    return result.scalars().all()


# 2. Tworzenie nowej kampanii (POST /api/campaigns)
@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(payload: CampaignCreate, db: AsyncSession = Depends(get_db)):
    # model_dump(mode='json') konwertuje obiekty Decimal/date na typy zgodne z JSON
    campaign_data = payload.model_dump(mode='json')
    
    new_campaign = Campaign(**campaign_data)
    db.add(new_campaign)
    await db.commit()
    await db.refresh(new_campaign)
    return new_campaign


# 3. Pobieranie pojedynczej kampanii po ID (GET /api/campaigns/{campaign_id})
@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(campaign_id: int, db: AsyncSession = Depends(get_db)):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")
    return campaign


# 4. Edycja istniejącej kampanii (PUT /api/campaigns/{campaign_id})
@router.put("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: int, 
    campaign_data: CampaignCreate, 
    db: AsyncSession = Depends(get_db)
):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")

    for key, value in campaign_data.model_dump(mode='json').items():
        setattr(campaign, key, value)

    await db.commit()
    await db.refresh(campaign)
    return campaign


# 5. Usuwanie kampanii po ID (DELETE /api/campaigns/{campaign_id})
@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(campaign_id: int, db: AsyncSession = Depends(get_db)):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")
    
    await db.delete(campaign)
    await db.commit()
    return None