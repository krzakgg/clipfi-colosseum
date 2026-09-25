import asyncio
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List
from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError
from sqlalchemy import text

from database import Base, engine
from settings import get_settings
from tracking_client import TrackingClient
from controllers import (
    application_router,
    campaign_router,
    company_router,
    creator_router,
    submission_router,
    reflink_router,
    auth_router,
)
import models  # Wymagane, aby SQLAlchemy załadowało definicje tabel przed create_all

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
ALLOWED_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024


async def save_image(file: UploadFile) -> str:
    extension = ALLOWED_IMAGE_TYPES.get(file.content_type)
    if not extension:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Dozwolone formaty obrazów: JPG, PNG, WEBP i GIF"
        )

    content = await file.read(MAX_IMAGE_SIZE + 1)
    if len(content) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Obraz '{file.filename}' może mieć maksymalnie 10 MB"
        )

    filename = f"{uuid.uuid4().hex}{extension}"
    (UPLOAD_DIR / filename).write_bytes(content)
    return f"http://localhost:8000/uploads/{filename}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Próba połączenia z bazą danych z automatycznym ponawianiem
    retries = 5
    while retries > 0:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                await conn.execute(text(
                    "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS "
                    "cover_image_url VARCHAR(1000)"
                ))
                await conn.execute(text(
                    "ALTER TABLE campaigns ADD COLUMN IF NOT EXISTS "
                    "gallery_image_urls JSON"
                ))
                await conn.execute(text(
                    "ALTER TABLE companies ADD COLUMN IF NOT EXISTS "
                    "password_hash VARCHAR(256)"
                ))
                await conn.execute(text(
                    "ALTER TABLE creators ADD COLUMN IF NOT EXISTS "
                    "password_hash VARCHAR(256)"
                ))
            print("Pomyślnie połączono z bazą danych i utworzono tabele.")
            break
        except (OperationalError, ConnectionRefusedError, OSError) as e:
            retries -= 1
            if retries == 0:
                print("Nie udało się połączyć z bazą danych po kilku próbach.")
                raise e
            print(f"Oczekiwanie na bazę danych... pozostało prób: {retries}")
            await asyncio.sleep(2)

    settings = get_settings()
    app.state.tracking = TrackingClient(
        settings.tracking_internal_url,
        settings.tracking_service_token.get_secret_value(),
        settings.tracking_redirect_base,
        timeout=settings.tracking_timeout,
    )
    try:
        yield
    finally:
        await app.state.tracking.aclose()


app = FastAPI(title="Platforma Kampanii API", lifespan=lifespan)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

# Konfiguracja CORS (umożliwia komunikację z frontendem Vue na porcie 5173)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rejestracja ścieżek API (kontrolery zawierają już w sobie prefix np. /api/campaigns)
app.include_router(application_router)
app.include_router(campaign_router)
app.include_router(company_router)
app.include_router(creator_router)
app.include_router(submission_router)
app.include_router(reflink_router)
app.include_router(auth_router)


@app.post("/api/uploads/image")
async def upload_image(file: UploadFile = File(...)):
    return {"url": await save_image(file)}


@app.post("/api/uploads/images")
async def upload_images(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="Wybierz co najmniej jeden obraz")
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Możesz wgrać maksymalnie 20 obrazów naraz")

    return {"urls": [await save_image(file) for file in files]}