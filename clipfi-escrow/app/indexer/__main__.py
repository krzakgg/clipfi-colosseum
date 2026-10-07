import asyncio
import logging

import uvicorn

from app.db import Database
from app.indexer.api import create_app
from app.indexer.decoder import EventDecoder
from app.indexer.poller import Poller
from app.settings import settings


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    db = Database()
    await db.create_all()
    poller = Poller(db, EventDecoder.from_file())
    stop = asyncio.Event()
    server = uvicorn.Server(uvicorn.Config(create_app(db), host="0.0.0.0", port=settings.indexer_port, log_level="info"))
    task = asyncio.create_task(poller.run(stop=stop))
    try:
        await server.serve()
    finally:
        stop.set()
        task.cancel()
        await poller.rpc.close()
        await db.dispose()


if __name__ == "__main__":
    asyncio.run(main())
