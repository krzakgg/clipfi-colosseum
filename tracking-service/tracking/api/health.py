import asyncio
import logging

from fastapi import APIRouter, Request, Response, status

log = logging.getLogger(__name__)

router = APIRouter()

_PROBE_TIMEOUT = 2.0


@router.get("/healthz", include_in_schema=False)
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def ready(request: Request, response: Response) -> dict[str, str]:
    deps = request.app.state.deps
    checks = {"redis": deps.check_redis, "database": deps.check_database}
    result: dict[str, str] = {}
    for name, probe in checks.items():
        try:
            await asyncio.wait_for(probe(), timeout=_PROBE_TIMEOUT)
            result[name] = "ok"
        except Exception as exc:
            log.warning("readiness probe %s failed: %s", name, exc)
            result[name] = "fail"
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return result
