from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class Scene(Base):
    __tablename__ = "scenes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(2), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    source: Mapped[str] = mapped_column(String(16), default="seed")
    epsg: Mapped[int | None] = mapped_column(Integer)
    footprint: Mapped[Any | None] = mapped_column(Geometry("POLYGON", srid=4326))
    corners: Mapped[list[list[float]] | None] = mapped_column(JSONB)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    gsd: Mapped[float | None] = mapped_column(Float)
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    satellite: Mapped[str | None] = mapped_column(String(16))
    date_pre: Mapped[date | None] = mapped_column(Date)
    date_post: Mapped[date | None] = mapped_column(Date, index=True)
    s1_date_pre: Mapped[date | None] = mapped_column(Date)
    s1_date_post: Mapped[date | None] = mapped_column(Date)
    fire_event_id: Mapped[str | None] = mapped_column(String(32))
    valid_frac: Mapped[float | None] = mapped_column(Float)
    cloud_frac: Mapped[float | None] = mapped_column(Float)
    model_name: Mapped[str | None] = mapped_column(String(64))
    files: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    quicklooks: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    stats: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Hotspot(Base):
    __tablename__ = "hotspots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    geom: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326))
    epsg: Mapped[int] = mapped_column(Integer)
    x_utm: Mapped[int] = mapped_column(Integer)
    y_utm: Mapped[int] = mapped_column(Integer)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    satellite: Mapped[str | None] = mapped_column(String(16))
    code: Mapped[int] = mapped_column(SmallInteger)
    persistent: Mapped[bool] = mapped_column(Boolean, default=False)
    bt_i4: Mapped[float] = mapped_column(Float)
    bt_i5: Mapped[float] = mapped_column(Float)
    frp_mw: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    landcover: Mapped[int] = mapped_column(SmallInteger)
    is_night: Mapped[bool] = mapped_column(Boolean)
    t2m: Mapped[float | None] = mapped_column(Float)
    rh2m: Mapped[float | None] = mapped_column(Float)
    wind_speed: Mapped[float | None] = mapped_column(Float)


class PersistentSource(Base):
    __tablename__ = "persistent_sources"

    epsg: Mapped[int] = mapped_column(Integer, primary_key=True)
    x_utm: Mapped[int] = mapped_column(Integer, primary_key=True)
    y_utm: Mapped[int] = mapped_column(Integer, primary_key=True)
    geom: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326))
    n_detections: Mapped[int] = mapped_column(Integer)
    n_days: Mapped[int] = mapped_column(Integer)
    n_years: Mapped[int] = mapped_column(Integer)
    n_passes: Mapped[int] = mapped_column(Integer)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BurnArea(Base):
    __tablename__ = "burn_areas"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    fire_event_id: Mapped[str | None] = mapped_column(String(32))
    geom: Mapped[Any] = mapped_column(Geometry("MULTIPOLYGON", srid=4326))
    epsg: Mapped[int] = mapped_column(Integer)
    area_ha: Mapped[float] = mapped_column(Float)
    sev1_ha: Mapped[float] = mapped_column(Float)
    sev2_ha: Mapped[float] = mapped_column(Float)
    sev3_ha: Mapped[float] = mapped_column(Float)
    date_pre: Mapped[date] = mapped_column(Date)
    date_post: Mapped[date] = mapped_column(Date, index=True)


class SeverityPolygon(Base):
    __tablename__ = "severity_polygons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    burn_area_id: Mapped[int] = mapped_column(ForeignKey("burn_areas.id", ondelete="CASCADE"), index=True)
    severity: Mapped[int] = mapped_column(SmallInteger)
    geom: Mapped[Any] = mapped_column(Geometry("POLYGON", srid=4326))
    epsg: Mapped[int] = mapped_column(Integer)
    area_ha: Mapped[float] = mapped_column(Float)
    date_post: Mapped[date] = mapped_column(Date, index=True)


class ScarLandcover(Base):
    __tablename__ = "scar_landcover"

    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), primary_key=True)
    severity: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    lc_group: Mapped[str] = mapped_column(String(16), primary_key=True)
    area_ha: Mapped[float] = mapped_column(Float)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(24), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120))
    geom: Mapped[Any] = mapped_column(Geometry("GEOMETRY", srid=4326))
    webhook_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"), index=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"))
    n_hotspots: Mapped[int] = mapped_column(Integer)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    centroid: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
