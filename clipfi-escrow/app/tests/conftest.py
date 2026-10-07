import pytest
import pytest_asyncio

from app.db import Database
from app.indexer.decoder import EventDecoder
import app.indexer.models
import app.partner.models

MEM_URL = "sqlite+aiosqlite://"


@pytest_asyncio.fixture
async def db():
    d = Database(MEM_URL)
    await d.create_all()
    yield d
    await d.dispose()


@pytest.fixture(scope="session")
def decoder():
    return EventDecoder.from_file()


@pytest.fixture(scope="session")
def idl(decoder):
    return decoder.idl
