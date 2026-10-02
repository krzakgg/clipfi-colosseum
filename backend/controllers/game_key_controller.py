from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models import Campaign, CampaignApplication, Company, Creator, GameKey, GameKeyStatus, KeyRequest, KeyRequestStatus
from schemas import GameKeyCreate, GameKeyResponse, KeyRequestCreate, KeyRequestResponse, KeyRequestStatusUpdate

router = APIRouter(tags=["game keys"])


def _request_response(request: KeyRequest) -> dict:
    return {
        **{column.name: getattr(request, column.name) for column in KeyRequest.__table__.columns},
        "key_value": request.game_key.key_value if request.game_key else None,
    }


async def _owned_campaign(campaign_id: int, company_id: int, db: AsyncSession) -> Campaign:
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")
    if campaign.company_id != company_id:
        raise HTTPException(status_code=403, detail="Nie masz dostępu do tej kampanii")
    return campaign


@router.post("/api/campaigns/{campaign_id}/game-keys", response_model=GameKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_game_key(campaign_id: int, key_data: GameKeyCreate, db: AsyncSession = Depends(get_db)):
    await _owned_campaign(campaign_id, key_data.company_id, db)
    duplicate = await db.scalar(select(GameKey).where(GameKey.campaign_id == campaign_id, GameKey.key_value == key_data.key_value))
    if duplicate:
        raise HTTPException(status_code=409, detail="Ten klucz jest już przypisany do kampanii")

    game_key = GameKey(campaign_id=campaign_id, key_value=key_data.key_value)
    db.add(game_key)
    await db.commit()
    await db.refresh(game_key)
    return game_key


@router.get("/api/campaigns/{campaign_id}/game-keys", response_model=List[GameKeyResponse])
async def list_game_keys(campaign_id: int, company_id: int, db: AsyncSession = Depends(get_db)):
    await _owned_campaign(campaign_id, company_id, db)
    result = await db.scalars(select(GameKey).where(GameKey.campaign_id == campaign_id).order_by(GameKey.created_at.desc()))
    return list(result)


@router.post("/api/campaigns/{campaign_id}/key-requests", response_model=KeyRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_key_request(campaign_id: int, request_data: KeyRequestCreate, db: AsyncSession = Depends(get_db)):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")
    if not await db.get(Creator, request_data.creator_id):
        raise HTTPException(status_code=404, detail="Twórca nie istnieje")

    application = await db.scalar(
        select(CampaignApplication).where(
            CampaignApplication.campaign_id == campaign_id,
            CampaignApplication.creator_id == request_data.creator_id,
        )
    )
    if not application or application.status.value != "accepted":
        raise HTTPException(status_code=409, detail="Tylko zaakceptowany twórca może poprosić o klucz")

    existing = await db.scalar(
        select(KeyRequest).where(KeyRequest.campaign_id == campaign_id, KeyRequest.creator_id == request_data.creator_id)
    )
    if existing:
        raise HTTPException(status_code=409, detail="Twórca ma już prośbę o klucz w tej kampanii")

    key_request = KeyRequest(campaign_id=campaign_id, creator_id=request_data.creator_id, message=request_data.message)
    db.add(key_request)
    await db.commit()
    await db.refresh(key_request)
    return _request_response(key_request)


@router.get("/api/campaigns/{campaign_id}/key-requests", response_model=List[KeyRequestResponse])
async def list_key_requests(campaign_id: int, company_id: int, db: AsyncSession = Depends(get_db)):
    await _owned_campaign(campaign_id, company_id, db)
    result = await db.scalars(
        select(KeyRequest).options(selectinload(KeyRequest.game_key)).where(KeyRequest.campaign_id == campaign_id).order_by(KeyRequest.created_at.desc())
    )
    return [_request_response(item) for item in result]


@router.get("/api/key-requests/creator/{creator_id}", response_model=List[KeyRequestResponse])
async def list_creator_key_requests(creator_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.scalars(select(KeyRequest).options(selectinload(KeyRequest.game_key)).where(KeyRequest.creator_id == creator_id).order_by(KeyRequest.created_at.desc()))
    return [_request_response(item) for item in result]


@router.patch("/api/key-requests/{request_id}/status", response_model=KeyRequestResponse)
async def update_key_request_status(
    request_id: int,
    status_data: KeyRequestStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    key_request = await db.get(KeyRequest, request_id)
    if not key_request:
        raise HTTPException(status_code=404, detail="Prośba o klucz nie istnieje")
    await _owned_campaign(key_request.campaign_id, status_data.company_id, db)
    if key_request.status != KeyRequestStatus.PENDING:
        raise HTTPException(status_code=409, detail="Ta prośba została już rozpatrzona")
    if status_data.status not in (KeyRequestStatus.APPROVED.value, KeyRequestStatus.REJECTED.value):
        raise HTTPException(status_code=400, detail="Nieprawidłowy status prośby")

    if status_data.status == KeyRequestStatus.APPROVED.value:
        game_key = await db.scalar(
            select(GameKey)
            .where(GameKey.campaign_id == key_request.campaign_id, GameKey.status == GameKeyStatus.AVAILABLE)
            .order_by(GameKey.created_at)
            .with_for_update()
        )
        if not game_key:
            raise HTTPException(status_code=409, detail="Brak dostępnych kluczy dla tej kampanii")
        game_key.status = GameKeyStatus.ASSIGNED
        game_key.assigned_to_creator_id = key_request.creator_id
        game_key.assigned_at = datetime.now(timezone.utc)
        key_request.game_key = game_key

    key_request.status = status_data.status
    key_request.reviewer_feedback = status_data.reviewer_feedback
    key_request.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(key_request)
    return _request_response(key_request)


@router.delete("/api/key-requests/{request_id}", response_model=KeyRequestResponse)
async def cancel_key_request(request_id: int, creator_id: int, db: AsyncSession = Depends(get_db)):
    key_request = await db.get(KeyRequest, request_id)
    if not key_request:
        raise HTTPException(status_code=404, detail="Prośba o klucz nie istnieje")
    if key_request.creator_id != creator_id:
        raise HTTPException(status_code=403, detail="Nie możesz anulować tej prośby")
    if key_request.status != KeyRequestStatus.PENDING:
        raise HTTPException(status_code=409, detail="Ta prośba została już rozpatrzona")

    key_request.status = KeyRequestStatus.CANCELLED
    await db.commit()
    await db.refresh(key_request)
    return _request_response(key_request)
