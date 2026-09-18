from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl

from firewatch.services.query import InvalidQueryError, SpatioTemporalQuery

BBox = tuple[float, float, float, float]
VectorFormat = Literal["geojson", "shp", "gpkg", "kml"]
ReportFormat = Literal["json", "csv", "xlsx", "pdf"]
BurnLayer = Literal["contours", "severity"]
HotspotKind = Literal["fire", "technogenic", "glint"]

BBOX_EXAMPLE = "44.0,45.5,46.5,47.5"


class QueryBody(BaseModel):
    """Пространственно-временной запрос: полигон GeoJSON или bbox, плюс интервал дат."""

    geometry: dict[str, Any] | None = Field(
        default=None, description="GeoJSON Polygon или MultiPolygon, WGS 84"
    )
    bbox: BBox | None = Field(default=None, description="west, south, east, north")
    date_from: date
    date_to: date

    def to_query(self) -> SpatioTemporalQuery:
        return _build(self.geometry, self.bbox, self.date_from, self.date_to)


def _build(
    geometry: dict[str, Any] | None, bbox: BBox | None, date_from: date, date_to: date
) -> SpatioTemporalQuery:
    try:
        return SpatioTemporalQuery.build(geometry=geometry, bbox=bbox, date_from=date_from, date_to=date_to)
    except InvalidQueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def parse_bbox(raw: str) -> BBox:
    try:
        west, south, east, north = (float(part) for part in raw.split(","))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="bbox задаётся как west,south,east,north") from exc
    return west, south, east, north


def query_from_params(
    bbox: Annotated[str, Query(description="west,south,east,north в WGS 84", examples=[BBOX_EXAMPLE])],
    date_from: Annotated[date, Query(examples=["2020-04-01"])],
    date_to: Annotated[date, Query(examples=["2020-10-31"])],
) -> SpatioTemporalQuery:
    return _build(None, parse_bbox(bbox), date_from, date_to)


GetQuery = Annotated[SpatioTemporalQuery, Depends(query_from_params)]


class ZoneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    geometry: dict[str, Any]
    webhook_url: HttpUrl | None = None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    context: QueryBody | None = None
