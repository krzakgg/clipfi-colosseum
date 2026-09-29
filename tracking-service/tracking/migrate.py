
import asyncio
import logging
from importlib.resources import files

import asyncpg

from tracking.config import Settings, configure_logging

log = logging.getLogger(__name__)

_LOCK_ID = 0x7472616B  # "trak"


async def migrate(conn: asyncpg.Connection) -> list[str]:
    applied: list[str] = []
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock($1)", _LOCK_ID)
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        done = {row["version"] for row in await conn.fetch("SELECT version FROM schema_migrations")}
        for path in sorted(files("tracking").joinpath("migrations").iterdir(), key=lambda p: p.name):
            if not path.name.endswith(".sql") or path.name in done:
                continue
            await conn.execute(path.read_text(encoding="utf-8"))
            await conn.execute("INSERT INTO schema_migrations (version) VALUES ($1)", path.name)
            applied.append(path.name)
    return applied


async def _main(settings: Settings) -> None:
    conn = await asyncpg.connect(settings.migrate_database_url or settings.database_url)
    try:
        applied = await migrate(conn)
    finally:
        await conn.close()
    log.info("applied %d migration(s): %s", len(applied), ", ".join(applied) or "none")


def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    asyncio.run(_main(settings))


if __name__ == "__main__":
    main()
