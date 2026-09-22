import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError

from database import Base, engine
from controllers import (
    application_router,
    campaign_router,
    company_router,
    creator_router,
    submission_router,
)
import models  # Wymagane, aby SQLAlchemy załadowało definicje tabel przed create_all


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Próba połączenia z bazą danych z automatycznym ponawianiem
    retries = 5
    while retries > 0:
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            print("Pomyślnie połączono z bazą danych i utworzono tabele.")
            break
        except (OperationalError, ConnectionRefusedError, OSError) as e:
            retries -= 1
            if retries == 0:
                print("Nie udało się połączyć z bazą danych po kilku próbach.")
                raise e
            print(f"Oczekiwanie na bazę danych... pozostało prób: {retries}")
            await asyncio.sleep(2)
    
    yield


app = FastAPI(title="Platforma Kampanii API", lifespan=lifespan)

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