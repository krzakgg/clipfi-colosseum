import logging
import hashlib
import mimetypes
import uuid
from pathlib import Path
from urllib.parse import urlparse
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, List

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
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
PRESS_KIT_DIR = Path(__file__).resolve().parent.parent / "uploads" / "press-kits"
PRESS_KIT_DIR.mkdir(parents=True, exist_ok=True)
MAX_PRESS_KIT_SIZE = 50 * 1024 * 1024
BLOCKED_PRESS_KIT_HOSTS = ("drive.google.com", "docs.google.com", "dropbox.com", "www.dropbox.com")

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


@router.get("/{campaign_id}/press-kit/download")
async def download_press_kit(campaign_id: int, db: AsyncSession = Depends(get_db)):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign or not campaign.press_kit_url:
        raise HTTPException(status_code=404, detail="Kampania nie ma Press Kitu")

    parsed_url = urlparse(campaign.press_kit_url)
    local_name = Path(parsed_url.path).name
    local_file = PRESS_KIT_DIR / local_name
    if local_name and local_file.is_file() and local_file.parent == PRESS_KIT_DIR:
        return FileResponse(local_file, filename=local_file.name)

    hostname = (parsed_url.hostname or "").lower().rstrip(".")
    if parsed_url.scheme not in {"http", "https"} or any(
        hostname == blocked or hostname.endswith(f".{blocked}") for blocked in BLOCKED_PRESS_KIT_HOSTS
    ):
        raise HTTPException(status_code=422, detail="Ten link nie jest bezpośrednim plikiem")

    cache_key = hashlib.sha256(campaign.press_kit_url.encode("utf-8")).hexdigest()
    cached_files = list(PRESS_KIT_DIR.glob(f"{cache_key}.*"))
    if cached_files:
        return FileResponse(cached_files[0], filename=cached_files[0].name)

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            async with client.stream("GET", campaign.press_kit_url) as response:
                response.raise_for_status()
                final_hostname = (urlparse(str(response.url)).hostname or "").lower().rstrip(".")
                if any(
                    final_hostname == blocked or final_hostname.endswith(f".{blocked}")
                    for blocked in BLOCKED_PRESS_KIT_HOSTS
                ):
                    raise HTTPException(status_code=422, detail="Ten link prowadzi do Google Drive lub Dropbox")

                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if not content_type or content_type.startswith("text/html"):
                    raise HTTPException(status_code=422, detail="Link nie prowadzi bezpośrednio do pliku")
                if int(response.headers.get("content-length", 0) or 0) > MAX_PRESS_KIT_SIZE:
                    raise HTTPException(status_code=413, detail="Press Kit może mieć maksymalnie 50 MB")

                extension = mimetypes.guess_extension(content_type) or Path(parsed_url.path).suffix or ".bin"
                target = PRESS_KIT_DIR / f"{cache_key}{extension}"
                size = 0
                with target.open("wb") as file:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_PRESS_KIT_SIZE:
                            target.unlink(missing_ok=True)
                            raise HTTPException(status_code=413, detail="Press Kit może mieć maksymalnie 50 MB")
                        file.write(chunk)
    except HTTPException:
        raise
    except (httpx.HTTPError, OSError) as exc:
        log.warning("Could not cache press kit for campaign %s: %s", campaign_id, exc)
        raise HTTPException(status_code=422, detail="Nie udało się pobrać Press Kitu") from exc

    return FileResponse(target, filename=target.name)


@router.post("/{campaign_id}/press-kit/upload", response_model=CampaignResponse)
async def upload_press_kit(
    campaign_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")
    if not file.filename:
        raise HTTPException(status_code=400, detail="Wybierz plik Press Kit")

    extension = Path(file.filename).suffix.lower()[:12]
    filename = f"{uuid.uuid4().hex}{extension}"
    target = PRESS_KIT_DIR / filename
    size = 0
    try:
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_PRESS_KIT_SIZE:
                    target.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="Press Kit może mieć maksymalnie 50 MB")
                output.write(chunk)
    except HTTPException:
        raise
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Nie udało się zapisać Press Kitu") from exc

    campaign.press_kit_url = f"http://localhost:8000/uploads/press-kits/{filename}"
    await db.commit()
    await db.refresh(campaign)
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
