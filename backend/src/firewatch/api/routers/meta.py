from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.config import get_settings
from firewatch.db.session import get_session
from firewatch.domain.catalog import SEVERITY_COLORS, SEVERITY_LABELS
from firewatch.infra.cache import DATA_VERSION_KEY, cached, redis
from firewatch.pipeline.ingest import STAGE_MESSAGES, STAGES
from firewatch.services import metrics

router = APIRouter(tags=["Служебное"])
Session = Annotated[AsyncSession, Depends(get_session)]

_EXTENT = text(
    """
    SELECT (SELECT count(*) FROM scenes WHERE status = 'ready' AND kind = 'af') AS af_scenes,
           (SELECT count(*) FROM scenes WHERE status = 'ready' AND kind = 'bs') AS bs_scenes,
           (SELECT count(*) FROM scenes WHERE status IN ('queued', 'processing')) AS pending_scenes,
           (SELECT count(*) FROM hotspots) AS hotspots,
           (SELECT count(*) FROM persistent_sources) AS persistent_sources,
           (SELECT coalesce(sum(area_ha), 0) FROM burn_areas) AS burn_ha,
           (SELECT least(min(acquired_at)::date, (SELECT min(date_pre) FROM scenes)) FROM scenes) AS date_min,
           (SELECT greatest(max(acquired_at)::date, (SELECT max(date_post) FROM scenes)) FROM scenes) AS date_max,
           (SELECT array_agg(DISTINCT model_name) FROM scenes WHERE model_name IS NOT NULL) AS models
    """
)

_TIMELINE = text(
    """
    SELECT day, sum(fire) AS fire, sum(filtered) AS filtered, sum(burn_ha) AS burn_ha FROM (
        SELECT acquired_at::date AS day,
               count(*) FILTER (WHERE code = 1 AND NOT persistent) AS fire,
               count(*) FILTER (WHERE code <> 1 OR persistent) AS filtered, 0::float AS burn_ha
        FROM hotspots GROUP BY 1
        UNION ALL
        SELECT date_post, 0, 0, sum(area_ha) FROM burn_areas GROUP BY 1
    ) t GROUP BY day ORDER BY day
    """
)

_SOURCES = text(
    """
    SELECT ST_X(geom) AS lon, ST_Y(geom) AS lat, n_detections, n_days, n_years, n_passes, first_seen, last_seen
    FROM persistent_sources ORDER BY n_days DESC
    """
)


@lru_cache
def _asset(name: str) -> dict[str, Any]:
    return json.loads(resources.files("firewatch.assets").joinpath(name).read_text("utf-8"))


@router.get("/health", summary="Проверка готовности")
async def health(session: Session) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/api/v1/meta", summary="Границы мониторинга, регионы, охват данных, легенда")
async def meta(session: Session) -> dict[str, Any]:
    row = (await session.execute(_EXTENT)).mappings().one()
    return {
        "aoi": _asset("aoi.geojson")["features"][0],
        "regions": _asset("regions.geojson"),
        "data": {
            **{
                k: row[k]
                for k in ("af_scenes", "bs_scenes", "pending_scenes", "hotspots", "persistent_sources")
            },
            "burn_ha": round(row["burn_ha"], 1),
            "date_min": row["date_min"].isoformat() if row["date_min"] else None,
            "date_max": row["date_max"].isoformat() if row["date_max"] else None,
            "models": row["models"] or [],
        },
        "severity": [
            {
                "severity": k,
                "label": SEVERITY_LABELS[k],
                "color": "#{:02x}{:02x}{:02x}".format(*SEVERITY_COLORS[k]),
            }
            for k in (1, 2, 3)
        ],
        "pipeline": [{"stage": s, "label": STAGE_MESSAGES.get(s, "В очереди RabbitMQ")} for s in STAGES],
        "agent": {"llm": get_settings().llm_enabled, "model": get_settings().llm_model or None},
        "tiles_version": int(await redis.get(DATA_VERSION_KEY) or 0),
    }


@router.get("/api/v1/timeline", summary="Активность по дням за весь охват данных")
async def timeline(session: Session) -> list[dict[str, Any]]:
    async def produce() -> list[dict[str, Any]]:
        rows = (await session.execute(_TIMELINE)).mappings()
        return [
            {
                "day": r["day"].isoformat(),
                "fire": int(r["fire"]),
                "filtered": int(r["filtered"]),
                "burn_ha": round(r["burn_ha"], 1),
            }
            for r in rows
        ]

    return await cached("timeline", "all", produce)


@router.get(
    "/api/v1/technogenic/sources", summary="Постоянные источники тепла, найденные по истории детекций"
)
async def technogenic_sources(session: Session) -> dict[str, Any]:
    async def produce() -> dict[str, Any]:
        rows = (await session.execute(_SOURCES)).mappings()
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(r["lon"], 6), round(r["lat"], 6)]},
                "properties": {
                    "n_detections": r["n_detections"],
                    "n_days": r["n_days"],
                    "n_years": r["n_years"],
                    "n_passes": r["n_passes"],
                    "first_seen": r["first_seen"].isoformat(),
                    "last_seen": r["last_seen"].isoformat(),
                },
            }
            for r in rows
        ]
        return {"type": "FeatureCollection", "features": features}

    return await cached("sources", "all", produce)


@router.get(
    "/api/v1/metrics/pipeline", summary="Производительность конвейера: время на сцену, пропускная способность"
)
async def pipeline_metrics(session: Session) -> dict[str, Any]:
    return await metrics.fetch_pipeline_metrics(session)


@router.get("/api/v1/metrics/quality", summary="Метрика соревнования по всем сценам с эталонной маской")
async def quality_metrics(session: Session) -> dict[str, Any] | None:
    async def produce() -> dict[str, Any] | None:
        rows = await session.execute(
            text(
                "SELECT kind, stats -> 'quality' AS quality FROM scenes WHERE status = 'ready' AND stats ? 'quality'"
            )
        )
        return metrics.score_from_scenes([dict(r) for r in rows.mappings()])

    return await cached("quality", "all", produce)
