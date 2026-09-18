from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.config import get_settings
from firewatch.infra.cache import publish_event

log = logging.getLogger(__name__)

_ZONE_HITS = text(
    """
    SELECT z.id AS zone_id, z.name, z.webhook_url, count(*) AS n_hotspots,
           min(h.acquired_at) AS acquired_at,
           ST_AsText(ST_Centroid(ST_Collect(h.geom))) AS centroid_wkt,
           ST_X(ST_Centroid(ST_Collect(h.geom))) AS lon,
           ST_Y(ST_Centroid(ST_Collect(h.geom))) AS lat
    FROM zones z
    JOIN hotspots h ON ST_Intersects(z.geom, h.geom)
    WHERE h.scene_id = :scene_id AND h.code = 1 AND NOT h.persistent
    GROUP BY z.id, z.name, z.webhook_url
    """
)

_INSERT_ALERT = text(
    """
    INSERT INTO alerts (zone_id, scene_id, n_hotspots, acquired_at, centroid)
    VALUES (:zone_id, :scene_id, :n_hotspots, :acquired_at, ST_GeomFromText(:centroid_wkt, 4326))
    RETURNING id
    """
)


async def raise_zone_alerts(session: AsyncSession, scene_id: str) -> list[dict[str, Any]]:
    alerts = []
    for row in (await session.execute(_ZONE_HITS, {"scene_id": scene_id})).mappings():
        alert_id = (
            await session.execute(
                _INSERT_ALERT,
                {
                    "zone_id": row["zone_id"],
                    "scene_id": scene_id,
                    "n_hotspots": row["n_hotspots"],
                    "acquired_at": row["acquired_at"],
                    "centroid_wkt": row["centroid_wkt"],
                },
            )
        ).scalar_one()
        alerts.append(
            {
                "id": alert_id,
                "zone_id": row["zone_id"],
                "zone_name": row["name"],
                "scene_id": scene_id,
                "n_hotspots": row["n_hotspots"],
                "acquired_at": row["acquired_at"].isoformat(),
                "lon": row["lon"],
                "lat": row["lat"],
                "webhook_url": row["webhook_url"],
            }
        )
    return alerts


async def deliver_alerts(alerts: list[dict[str, Any]]) -> None:
    timeout = get_settings().webhook_timeout_seconds
    async with httpx.AsyncClient(timeout=timeout) as client:
        for alert in alerts:
            webhook_url = alert.pop("webhook_url")
            await publish_event("alert", alert)
            if not webhook_url:
                continue
            try:
                response = await client.post(webhook_url, json={"type": "firewatch.alert", **alert})
                response.raise_for_status()
            except httpx.HTTPError:
                log.warning(
                    "Webhook зоны %s не принял алерт %s", alert["zone_id"], alert["id"], exc_info=True
                )
