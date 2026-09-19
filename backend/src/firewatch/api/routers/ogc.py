"""OGC API - Features, Part 1: Core. Подключается в QGIS как слой WFS / OGC API Features по адресу /ogc."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.api.schemas import parse_bbox
from firewatch.db.session import get_session

router = APIRouter(prefix="/ogc", tags=["OGC API Features"])
Session = Annotated[AsyncSession, Depends(get_session)]

GEOJSON = "application/geo+json"
CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
CONFORMANCE = [
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30",
]
MAX_LIMIT = 10_000


@dataclass(frozen=True)
class Collection:
    id: str
    title: str
    description: str
    source: str
    properties: str
    time_start: str
    time_end: str


COLLECTIONS = {
    c.id: c
    for c in (
        Collection(
            id="hotspots",
            title="Термоточки",
            description="Термоаномалии VIIRS 375 м. kind: fire - природный пожар, technogenic - техногенный источник, glint - блик",
            source="hotspots t",
            properties="""jsonb_build_object('kind', CASE WHEN t.code = 3 THEN 'glint' WHEN t.code = 2 OR t.persistent
                THEN 'technogenic' ELSE 'fire' END, 'acquired_at', t.acquired_at, 'satellite', t.satellite,
                'bt_i4', round(t.bt_i4::numeric, 1), 'bt_i5', round(t.bt_i5::numeric, 1),
                'frp_mw', round(t.frp_mw::numeric, 2),
                'confidence', round(t.confidence::numeric, 2), 'scene_id', t.scene_id)""",
            time_start="t.acquired_at",
            time_end="t.acquired_at",
        ),
        Collection(
            id="burn_contours",
            title="Контуры гарей",
            description="Контуры пройденной огнём площади с разбивкой площади по степеням поражения, га",
            source="burn_areas t",
            properties="""jsonb_build_object('contour_id', t.id, 'scene_id', t.scene_id, 'fire_event_id', t.fire_event_id,
                'area_ha', round(t.area_ha::numeric, 2), 'sev1_ha', round(t.sev1_ha::numeric, 2),
                'sev2_ha', round(t.sev2_ha::numeric, 2), 'sev3_ha', round(t.sev3_ha::numeric, 2),
                'date_pre', t.date_pre, 'date_post', t.date_post, 'area_crs', 'EPSG:' || t.epsg)""",
            time_start="t.date_pre",
            time_end="t.date_post",
        ),
        Collection(
            id="burn_severity",
            title="Степени поражения",
            description="Полигоны степеней поражения: 1 - слабая, 2 - средняя, 3 - сильная",
            source="severity_polygons t",
            properties="""jsonb_build_object('polygon_id', t.id, 'contour_id', t.burn_area_id, 'scene_id', t.scene_id,
                'severity', t.severity, 'area_ha', round(t.area_ha::numeric, 3), 'date_post', t.date_post,
                'area_crs', 'EPSG:' || t.epsg)""",
            time_start="t.date_post",
            time_end="t.date_post",
        ),
    )
}


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/") + "/ogc"


def _link(href: str, rel: str, media_type: str, title: str) -> dict[str, str]:
    return {"href": href, "rel": rel, "type": media_type, "title": title}


def _collection_json(collection: Collection, base: str) -> dict[str, Any]:
    return {
        "id": collection.id,
        "title": collection.title,
        "description": collection.description,
        "itemType": "feature",
        "crs": [CRS84],
        "extent": {"spatial": {"bbox": [[38.3, 44.6, 48.0, 52.7]], "crs": CRS84}},
        "links": [
            _link(f"{base}/collections/{collection.id}", "self", "application/json", collection.title),
            _link(
                f"{base}/collections/{collection.id}/items", "items", GEOJSON, f"{collection.title}: объекты"
            ),
        ],
    }


def _get(collection_id: str) -> Collection:
    if collection_id not in COLLECTIONS:
        raise HTTPException(status_code=404, detail=f"Коллекция {collection_id} не найдена")
    return COLLECTIONS[collection_id]


def _parse_instant(value: str) -> datetime | None:
    if value in ("", ".."):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Некорректное значение datetime: {value}") from exc


def _parse_datetime(raw: str | None) -> tuple[datetime | None, datetime | None]:
    if not raw:
        return None, None
    if "/" not in raw:
        instant = _parse_instant(raw)
        return instant, instant
    start, _, end = raw.partition("/")
    return _parse_instant(start), _parse_instant(end)


@router.get("", summary="Точка входа OGC API")
async def landing(request: Request) -> dict[str, Any]:
    base = _base(request)
    return {
        "title": "Мониторинг природных пожаров",
        "description": "Термоточки и контуры гарей по стандарту OGC API - Features",
        "links": [
            _link(base, "self", "application/json", "Эта страница"),
            _link(f"{base}/conformance", "conformance", "application/json", "Классы соответствия"),
            _link(f"{base}/collections", "data", "application/json", "Коллекции"),
            _link(
                f"{str(request.base_url).rstrip('/')}/openapi.json",
                "service-desc",
                "application/vnd.oai.openapi+json;version=3.0",
                "OpenAPI",
            ),
        ],
    }


@router.get("/conformance", summary="Классы соответствия")
async def conformance() -> dict[str, list[str]]:
    return {"conformsTo": CONFORMANCE}


@router.get("/collections", summary="Коллекции")
async def collections(request: Request) -> dict[str, Any]:
    base = _base(request)
    return {
        "links": [_link(f"{base}/collections", "self", "application/json", "Коллекции")],
        "collections": [_collection_json(c, base) for c in COLLECTIONS.values()],
    }


@router.get("/collections/{collection_id}", summary="Описание коллекции")
async def collection(collection_id: str, request: Request) -> dict[str, Any]:
    return _collection_json(_get(collection_id), _base(request))


@router.get("/collections/{collection_id}/items", summary="Объекты коллекции: bbox, datetime, limit, offset")
async def items(
    collection_id: str,
    request: Request,
    session: Session,
    bbox: str | None = None,
    datetime_: Annotated[str | None, Query(alias="datetime")] = None,
    limit: int = Query(1000, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> JSONResponse:
    spec = _get(collection_id)
    start, end = _parse_datetime(datetime_)
    where, params = ["TRUE"], {"limit": limit, "offset": offset}
    if bbox:
        west, south, east, north = parse_bbox(bbox)
        where.append("t.geom && ST_MakeEnvelope(:west, :south, :east, :north, 4326)")
        params |= {"west": west, "south": south, "east": east, "north": north}
    if start:
        where.append(f"{spec.time_end} >= :start")
        params["start"] = start
    if end:
        where.append(f"{spec.time_start} <= :end")
        params["end"] = end
    condition = " AND ".join(where)

    matched = (
        await session.execute(text(f"SELECT count(*) FROM {spec.source} WHERE {condition}"), params)
    ).scalar_one()
    rows = await session.execute(
        text(
            f"SELECT t.id, ST_AsGeoJSON(t.geom, 7) AS geometry, {spec.properties} AS properties "
            f"FROM {spec.source} WHERE {condition} ORDER BY t.id LIMIT :limit OFFSET :offset"
        ),
        params,
    )
    features = [
        {
            "type": "Feature",
            "id": r["id"],
            "geometry": json.loads(r["geometry"]),
            "properties": r["properties"],
        }
        for r in rows.mappings()
    ]

    self_url = str(request.url)
    links = [_link(self_url, "self", GEOJSON, "Эта страница")]
    if offset + len(features) < matched:
        links.append(
            _link(
                str(request.url.include_query_params(offset=offset + limit)),
                "next",
                GEOJSON,
                "Следующая страница",
            )
        )
    body = {
        "type": "FeatureCollection",
        "numberMatched": matched,
        "numberReturned": len(features),
        "timeStamp": datetime.now().astimezone().isoformat(timespec="seconds"),
        "links": links,
        "features": features,
    }
    return JSONResponse(json.loads(json.dumps(body, default=str)), media_type=GEOJSON)


@router.get("/collections/{collection_id}/items/{feature_id}", summary="Один объект")
async def item(collection_id: str, feature_id: int, session: Session) -> JSONResponse:
    spec = _get(collection_id)
    row = (
        (
            await session.execute(
                text(
                    f"SELECT t.id, ST_AsGeoJSON(t.geom, 7) AS geometry, {spec.properties} AS properties FROM {spec.source} WHERE t.id = :id"
                ),
                {"id": feature_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Объект не найден")
    feature = {
        "type": "Feature",
        "id": row["id"],
        "geometry": json.loads(row["geometry"]),
        "properties": row["properties"],
    }
    return JSONResponse(json.loads(json.dumps(feature, default=str)), media_type=GEOJSON)
