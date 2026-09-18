from __future__ import annotations

import asyncio
import csv
import io
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.api.schemas import BurnLayer, GetQuery, HotspotKind, QueryBody, ReportFormat, VectorFormat
from firewatch.db.session import get_session
from firewatch.infra.cache import cached
from firewatch.services import query as q
from firewatch.services.export import (
    REPORT_FORMATS,
    VECTOR_FORMATS,
    ExportUnavailableError,
    export_report,
    export_vector,
)
from firewatch.services.report import build_report
from firewatch.services.tiles import warm_tiles

router = APIRouter(prefix="/api/v1", tags=["Анализ территории"])
Session = Annotated[AsyncSession, Depends(get_session)]
Kinds = Annotated[
    list[HotspotKind] | None, Query(description="Фильтр по типу термоточки. По умолчанию все типы")
]

_background: set[asyncio.Task[None]] = set()


def _keep(task: asyncio.Task[None]) -> None:
    """Держит ссылку на фоновую задачу, иначе сборщик мусора может снять её до завершения."""
    _background.add(task)
    task.add_done_callback(_background.discard)


def _download(body: bytes, media_type: str, filename: str) -> Response:
    return Response(
        body, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


def _stem(query: q.SpatioTemporalQuery, name: str) -> str:
    return f"{name}_{query.date_from:%Y%m%d}_{query.date_to:%Y%m%d}"


async def _hotspots(
    session: AsyncSession, query: q.SpatioTemporalQuery, kinds: list[str] | None, fmt: str
) -> Any:
    collection = await cached("hotspots", query.cache_key, lambda: q.fetch_hotspots(session, query))
    if kinds:
        collection = {
            **collection,
            "features": [f for f in collection["features"] if f["properties"]["kind"] in kinds],
        }
    if fmt == "geojson":
        return collection
    buffer = io.StringIO()
    rows = [
        {"lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1], **f["properties"]}
        for f in collection["features"]
    ]
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]) if rows else ["lon", "lat"])
    writer.writeheader()
    writer.writerows(rows)
    return _download(
        ("﻿" + buffer.getvalue()).encode(), "text/csv; charset=utf-8", f"{_stem(query, 'hotspots')}.csv"
    )


async def _burns(session: AsyncSession, query: q.SpatioTemporalQuery, layer: str, fmt: str) -> Any:
    fetch = q.fetch_burn_areas if layer == "contours" else q.fetch_severity_polygons
    if layer == "contours":
        collection = await cached("burn_areas", query.cache_key, lambda: fetch(session, query))
    else:
        collection = await fetch(session, query)
    if fmt == "geojson" and layer == "contours":
        return collection
    name = f"burn_{layer}"
    try:
        body = await asyncio.to_thread(export_vector, collection, fmt, name)
    except ExportUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    media_type, extension = VECTOR_FORMATS[fmt]
    return _download(body, media_type, f"{_stem(query, name)}.{extension}")


async def _report(session: AsyncSession, query: q.SpatioTemporalQuery, fmt: str) -> Any:
    report = await cached("report", query.cache_key, lambda: build_report(session, query))
    _keep(asyncio.create_task(warm_tiles([(b["lon"], b["lat"]) for b in report["burn"]["largest"]])))
    if fmt == "json":
        return report
    try:
        body = await asyncio.to_thread(export_report, report, fmt)
    except ExportUnavailableError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    media_type, extension = REPORT_FORMATS[fmt]
    return _download(body, media_type, f"{_stem(query, 'report')}.{extension}")


@router.post("/query", summary="Всё по запросу одним вызовом: термоточки, контуры гарей, справка")
async def run_query(
    body: QueryBody,
    session: Session,
    contours: bool = Query(
        True, description="Вернуть контуры гарей. Карта интерфейса берёт их из векторных тайлов"
    ),
) -> dict[str, Any]:
    query = body.to_query()
    result = {
        "hotspots": await _hotspots(session, query, None, "geojson"),
        "report": await _report(session, query, "json"),
    }
    if contours:
        result["burn_areas"] = await _burns(session, query, "contours", "geojson")
    return result


@router.get("/hotspots", summary="Термоточки по bbox и периоду")
async def get_hotspots(
    query: GetQuery,
    session: Session,
    kind: Kinds = None,
    format: str = Query("geojson", pattern="^(geojson|csv)$"),
) -> Any:
    return await _hotspots(session, query, kind, format)


@router.post("/hotspots", summary="Термоточки по полигону и периоду")
async def post_hotspots(
    body: QueryBody,
    session: Session,
    kind: Kinds = None,
    format: str = Query("geojson", pattern="^(geojson|csv)$"),
) -> Any:
    return await _hotspots(session, body.to_query(), kind, format)


@router.get(
    "/burns", summary="Контуры гарей по bbox и периоду, выгрузка в GeoJSON, Shapefile, GeoPackage, KML"
)
async def get_burns(
    query: GetQuery, session: Session, layer: BurnLayer = "contours", format: VectorFormat = "geojson"
) -> Any:
    return await _burns(session, query, layer, format)


@router.post("/burns", summary="Контуры гарей по полигону и периоду")
async def post_burns(
    body: QueryBody, session: Session, layer: BurnLayer = "contours", format: VectorFormat = "geojson"
) -> Any:
    return await _burns(session, body.to_query(), layer, format)


@router.get("/report", summary="Аналитическая справка по bbox и периоду: JSON, CSV, XLSX, PDF")
async def get_report(query: GetQuery, session: Session, format: ReportFormat = "json") -> Any:
    return await _report(session, query, format)


@router.post("/report", summary="Аналитическая справка по полигону и периоду")
async def post_report(body: QueryBody, session: Session, format: ReportFormat = "json") -> Any:
    return await _report(session, body.to_query(), format)
