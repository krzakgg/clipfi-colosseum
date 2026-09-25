from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    status,
)
from pydantic import BaseModel

from tracking.auth import require_service_token
from tracking.links import (
    CODE_RE,
    EXTERNAL_ID_RE,
    Link,
    LinkExists,
    LinkInput,
    LinkOwnerMismatch,
    bounded_utc,
    generate_code,
)
from tracking.stats import Granularity, GroupBy, Totals

router = APIRouter(prefix="/internal", dependencies=[Depends(require_service_token)])

MAX_SERIES_POINTS = 10_000
_STEP = {Granularity.minute: timedelta(minutes=1), Granularity.hour: timedelta(hours=1), Granularity.day: timedelta(days=1)}
_CREATE_ATTEMPTS = 3


class TotalsOut(BaseModel):
    raw: int
    unique: int


class LinkOut(BaseModel):
    id: int
    code: str
    campaign_id: str
    creator_id: str
    target_url: str
    platform: str | None
    active: bool
    starts_at: datetime | None
    ends_at: datetime | None
    created_at: datetime
    updated_at: datetime
    totals: TotalsOut | None = None

    @classmethod
    def from_link(cls, link: Link, totals: Totals | None = None) -> "LinkOut":
        out = cls.model_validate(link, from_attributes=True)
        if totals is not None:
            out.totals = TotalsOut(raw=totals.raw, unique=totals.unique)
        return out


class PointOut(BaseModel):
    bucket: datetime
    raw: int
    unique: int
    group: str | None = None


class SeriesOut(BaseModel):
    granularity: Granularity
    start: datetime
    end: datetime
    points: list[PointOut]


class RefererOut(BaseModel):
    host: str | None
    clicks: int


class TimeRange(BaseModel):
    start: datetime
    end: datetime
    granularity: Granularity


def _window(start: datetime, end: datetime | None) -> tuple[datetime, datetime]:
    try:
        start = bounded_utc(start if start.tzinfo else start.replace(tzinfo=UTC))
        end = bounded_utc(end if end.tzinfo else end.replace(tzinfo=UTC)) if end else datetime.now(UTC)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"'from'/'to' {exc}") from None
    if end <= start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "'to' must be after 'from'")
    return start, end


def time_range(
    start: Annotated[datetime, Query(alias="from")],
    end: Annotated[datetime | None, Query(alias="to")] = None,
    granularity: Granularity = Granularity.hour,
) -> TimeRange:
    start, end = _window(start, end)
    if (end - start) / _STEP[granularity] > MAX_SERIES_POINTS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"range too wide for granularity={granularity.value}; at most {MAX_SERIES_POINTS} points",
        )
    return TimeRange(start=start, end=end, granularity=granularity)


def _series(window: TimeRange, points) -> SeriesOut:
    return SeriesOut(
        granularity=window.granularity,
        start=window.start,
        end=window.end,
        points=[PointOut.model_validate(p, from_attributes=True) for p in points],
    )


def _valid_code(code: str) -> str:
    if not CODE_RE.fullmatch(code):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "code must match ^[A-Za-z0-9_-]{4,64}$")
    return code


CodePath = Annotated[str, Depends(_valid_code)]
CampaignPath = Annotated[str, Path(pattern=EXTERNAL_ID_RE.pattern)]


@router.post("/links", status_code=status.HTTP_201_CREATED, response_model=LinkOut)
async def create_link(data: LinkInput, request: Request) -> LinkOut:
    deps = request.app.state.deps
    for _ in range(_CREATE_ATTEMPTS):
        try:
            return LinkOut.from_link(await deps.links.insert(generate_code(), data))
        except LinkExists:
            continue
    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "could not allocate a unique code")


@router.put("/links/{code}", response_model=LinkOut)
async def upsert_link(code: CodePath, data: LinkInput, request: Request) -> LinkOut:
    try:
        return LinkOut.from_link(await request.app.state.deps.links.upsert(code, data))
    except LinkOwnerMismatch:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "campaign_id and creator_id of an existing link cannot change"
        ) from None


@router.get("/links/{code}", response_model=LinkOut)
async def get_link(code: CodePath, request: Request) -> LinkOut:
    deps = request.app.state.deps
    link = await deps.links.get_by_code(code)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return LinkOut.from_link(link, await deps.stats.link_totals(link.id))


@router.delete("/links/{code}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_link(code: CodePath, request: Request) -> Response:
    if await request.app.state.deps.links.deactivate(code) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/links/{code}/stats", response_model=SeriesOut)
async def link_stats(code: CodePath, request: Request, window: Annotated[TimeRange, Depends(time_range)]) -> SeriesOut:
    deps = request.app.state.deps
    link = await deps.links.get_by_code(code)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return _series(window, await deps.stats.link_series(link.id, window.start, window.end, window.granularity))


@router.get("/campaigns/{campaign_id}/links", response_model=list[LinkOut])
async def campaign_links(campaign_id: CampaignPath, request: Request) -> list[LinkOut]:
    rows = await request.app.state.deps.stats.campaign_links(campaign_id)
    return [LinkOut.from_link(link, totals) for link, totals in rows]


@router.get("/campaigns/{campaign_id}/stats", response_model=SeriesOut)
async def campaign_stats(
    campaign_id: CampaignPath,
    request: Request,
    window: Annotated[TimeRange, Depends(time_range)],
    group_by: GroupBy | None = None,
) -> SeriesOut:
    points = await request.app.state.deps.stats.campaign_series(
        campaign_id, window.start, window.end, window.granularity, group_by
    )
    return _series(window, points)


@router.get("/campaigns/{campaign_id}/referers", response_model=list[RefererOut])
async def campaign_referers(
    campaign_id: CampaignPath,
    request: Request,
    start: Annotated[datetime, Query(alias="from")],
    end: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[RefererOut]:
    start, end = _window(start, end)
    rows = await request.app.state.deps.stats.campaign_referers(campaign_id, start, end, limit)
    return [RefererOut(host=r.host, clicks=r.clicks) for r in rows]
