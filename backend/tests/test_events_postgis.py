"""Opt-in real PostGIS checks, isolated in transaction-local temporary tables."""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from firewatch.config import get_settings
from firewatch.services.events import associate, detail


@pytest.mark.skipif(not os.getenv("FIREWATCH_POSTGIS_TEST"), reason="Requires local PostGIS")
@pytest.mark.asyncio
async def test_overlapping_scenes_count_each_hectare_once():
    engine = create_async_engine(get_settings().database_url)
    try:
        async with AsyncSession(engine) as session:
            # Temp tables shadow production names only on this connection.
            await session.execute(
                text(
                    "CREATE TEMP TABLE severity_polygons (scene_id text, severity int, geom geometry) ON COMMIT DROP"
                )
            )
            await session.execute(
                text(
                    "CREATE TEMP TABLE scar_landcover (scene_id text, severity int, lc_group text, area_ha float) ON COMMIT DROP"
                )
            )
            await session.execute(
                text("""
                INSERT INTO severity_polygons VALUES
                ('B1',1,ST_Transform(ST_MakeEnvelope(500000,5300000,500100,5300100,32638),4326)),
                ('B2',3,ST_Transform(ST_MakeEnvelope(500050,5300000,500150,5300100,32638),4326))
            """)
            )
            await session.execute(
                text("INSERT INTO scar_landcover VALUES ('B1',1,'other',1),('B2',3,'other',1)")
            )
            scenes = [
                {
                    "id": id,
                    "fire_event_id": "TEST",
                    "date_pre": "2020-01-01",
                    "date_post": "2020-01-03",
                    "epsg": 32638,
                    "area_ha": 1,
                }
                for id in ["B1", "B2"]
            ]
            index = associate([], scenes, [])
            event = index["events"][0]
            assert event["area_ha"] is None
            result = await detail(session, event, index["method"])
            assert result["burn"]["area_ha"] == pytest.approx(1.5)
            assert [s["area_ha"] for s in result["burn"]["by_severity"]] == pytest.approx([0.5, 0, 1])
            assert sum(i["area_ha"] for i in result["restoration"]["items"]) == pytest.approx(1.5)
            single = associate([], scenes[:1], [])
            one = await detail(session, single["events"][0], single["method"])
            assert one["area_ha"] == pytest.approx(1)
            await session.rollback()
    finally:
        await engine.dispose()
