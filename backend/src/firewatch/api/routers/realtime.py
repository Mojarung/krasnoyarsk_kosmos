from __future__ import annotations

from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.db.session import get_session
from firewatch.infra.cache import subscribe_events
from firewatch.services.tiles import MAX_ZOOM, cached_tile, clip_geojson

router = APIRouter(prefix="/api/v1", tags=["Карта и события"])
Session = Annotated[AsyncSession, Depends(get_session)]

# Адрес тайла содержит версию данных, поэтому браузеру можно кешировать надолго.
TILE_CACHE = "public, max-age=86400"


@router.get(
    "/stream",
    response_class=EventSourceResponse,
    summary="Поток событий: задания конвейера, новые сцены, алерты",
)
async def stream() -> AsyncIterable[ServerSentEvent]:
    yield ServerSentEvent(data={"ok": True}, event="hello")
    async for event in subscribe_events():
        yield ServerSentEvent(data=event["data"], event=event["event"])


@router.get("/tiles/burns/{z}/{x}/{y}.mvt", summary="Векторные тайлы гарей: слои contours, centers, severity")
async def burn_tile(
    session: Session,
    z: Annotated[int, Path(ge=0, le=MAX_ZOOM)],
    x: Annotated[int, Path(ge=0)],
    y: Annotated[int, Path(ge=0)],
    clip: Annotated[
        str | None,
        Query(max_length=8000, description="Выбранная область: id региона или 'p:lon,lat;...'"),
    ] = None,
) -> Response:
    if x >= 2**z or y >= 2**z:
        raise HTTPException(status_code=404, detail="Тайл вне сетки")
    try:
        area = clip_geojson(clip)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    tile = await cached_tile(session, z, x, y, area)
    return Response(
        tile, media_type="application/vnd.mapbox-vector-tile", headers={"Cache-Control": TILE_CACHE}
    )
