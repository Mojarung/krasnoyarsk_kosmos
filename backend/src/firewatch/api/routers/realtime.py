from __future__ import annotations

from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.db.session import get_session
from firewatch.infra.cache import cached, subscribe_events
from firewatch.services.tiles import MAX_ZOOM, render_tile

router = APIRouter(prefix="/api/v1", tags=["Карта и события"])
Session = Annotated[AsyncSession, Depends(get_session)]

TILE_CACHE = "public, max-age=60"


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
) -> Response:
    if x >= 2**z or y >= 2**z:
        raise HTTPException(status_code=404, detail="Тайл вне сетки")
    tile = await cached("tile", [z, x, y], lambda: render_tile(session, z, x, y), binary=True)
    return Response(
        tile, media_type="application/vnd.mapbox-vector-tile", headers={"Cache-Control": TILE_CACHE}
    )
