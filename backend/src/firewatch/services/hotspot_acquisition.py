"""A persisted imagery request for an existing hotspot event, not a forced burn association."""

import uuid
from datetime import date, timedelta

from pyproj import Transformer
from shapely.geometry import MultiPoint, mapping
from shapely.ops import transform
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from firewatch.db.models import Job, Scene
from firewatch.pipeline.acquire import utm_epsg
from firewatch.services import acquisitions, events


async def state(session: AsyncSession, event_id: str) -> dict:
    rows = (
        await session.execute(
            select(Scene, Job)
            .join(Job, Job.scene_id == Scene.id)
            .where(Scene.stats["acquisition"]["origin_event"].astext == event_id)
            .order_by(Job.created_at.desc())
        )
    ).all()
    data = await events.index(session)
    anchor = rows[0][0].stats["acquisition"]["anchor_id"] if rows else None
    event = next(
        (
            e
            for e in data["events"]
            if e["id"] == event_id or (anchor is not None and any(h["id"] == anchor for h in e["hotspots"]))
        ),
        None,
    )
    if not rows:
        return {"status": "idle", "jobs": [], "event_id": event["id"] if event else None}
    request_id = rows[0][0].stats["acquisition"]["request_id"]
    jobs = [
        {
            "id": str(job.id),
            "scene_id": scene.id,
            "status": job.status,
            "stage": job.stage,
            "progress": job.progress,
            "error": job.error,
        }
        for scene, job in rows
        if scene.stats["acquisition"]["request_id"] == request_id
    ]
    if any(j["status"] in {"queued", "running"} for j in jobs):
        status = "running"
    elif any(j["status"] == "failed" for j in jobs):
        status = "failed"
    elif event and event["status"] in {"linked", "ambiguous"}:
        status = "found" if event["status"] == "linked" else "ambiguous"
    else:
        status = "not_found"
    return {"status": status, "jobs": jobs, "event_id": event["id"] if event else None}


async def start(session: AsyncSession, event_id: str, retry: bool = False) -> dict:
    # Serialise concurrent clicks and retries across API processes, without a schema migration.
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"imagery:{event_id}"}
    )
    current = await state(session, event_id)
    if current["status"] != "idle" and not (retry and current["status"] == "failed"):
        return current
    data = await events.index(session)
    event = next((e for e in data["events"] if e["id"] == current["event_id"]), None)
    if not event:
        raise acquisitions.InvalidAcquisitionError("Наблюдение не найдено. Откройте термоточку заново")
    if event["status"] != "hotspot_only":
        if event["status"] == "burn_only":
            raise acquisitions.InvalidAcquisitionError("В этом паспорте нет термоточек для поиска")
        return {
            "status": "found" if event["status"] == "linked" else "ambiguous",
            "jobs": [],
            "event_id": event["id"],
        }
    points = event["hotspots"]
    first = date.fromisoformat(min(h["acquired_at"] for h in points)[:10])
    last = date.fromisoformat(max(h["acquired_at"] for h in points)[:10])
    center = MultiPoint([(h["lon"], h["lat"]) for h in points])
    epsg = utm_epsg(center.centroid.x, center.centroid.y)
    to_utm = Transformer.from_crs(4326, epsg, always_xy=True).transform
    to_wgs = Transformer.from_crs(epsg, 4326, always_xy=True).transform
    # Check cloud coverage near the observations, not averaged over the 10 km chip.
    target = transform(to_wgs, transform(to_utm, center).buffer(500))
    context = {
        "origin_event": event_id,
        "anchor_id": points[0]["id"],
        "request_id": uuid.uuid4().hex,
        "fire_start": first.isoformat(),
        "fire_end": last.isoformat(),
        "target_geometry": mapping(target),
    }
    await acquisitions.request_acquisition(
        session,
        target,
        first - timedelta(days=12),
        last + timedelta(days=8),
        context=context,
    )
    return await state(session, event_id)
