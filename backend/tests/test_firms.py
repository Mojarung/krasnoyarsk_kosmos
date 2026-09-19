from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from shapely.geometry import box

from firewatch.api.routers import acquisitions as router
from firewatch.services import acquisitions, firms

AVAILABILITY = """data_id,min_date,max_date
VIIRS_SNPP_SP,2012-01-20,2024-08-31
VIIRS_SNPP_NRT,2024-09-01,2024-12-31
VIIRS_NOAA20_SP,2018-04-01,2024-08-31
VIIRS_NOAA20_NRT,2024-09-01,2024-12-31
VIIRS_NOAA21_NRT,2024-01-17,2024-12-31
"""

DETECTIONS = """latitude,longitude,bright_ti4,acq_date,acq_time,satellite,confidence,bright_ti5,frp,daynight
56.01000,92.85000,341.2,2024-08-16,0732,N20,h,295.1,8.4,D
56.02000,92.86000,329.0,2024-08-16,221,N21,n,290.0,2.1,N
"""


def test_availability_uses_one_best_stream_in_five_day_chunks() -> None:
    parts = firms.plan_requests(
        firms.parse_availability(AVAILABILITY), date(2024, 8, 29), date(2024, 9, 4)
    )

    assert [(part.product, part.date_from, part.days) for part in parts] == [
        ("VIIRS_NOAA20_SP", date(2024, 8, 29), 3),
        ("VIIRS_NOAA20_NRT", date(2024, 9, 1), 4),
    ]


def test_availability_switches_from_archive_fallback_when_noaa20_starts() -> None:
    parts = firms.plan_requests(
        firms.parse_availability(AVAILABILITY), date(2018, 3, 30), date(2018, 4, 3)
    )

    assert [(part.product, part.date_from, part.days) for part in parts] == [
        ("VIIRS_SNPP_SP", date(2018, 3, 30), 2),
        ("VIIRS_NOAA20_SP", date(2018, 4, 1), 3),
    ]


def test_long_period_is_split_without_an_artificial_total_limit() -> None:
    availability = firms.parse_availability(AVAILABILITY)

    parts = firms.plan_requests(availability, date(2024, 1, 1), date(2024, 8, 31))

    assert parts
    assert all(1 <= part.days <= 5 for part in parts)
    assert any(part.date_from == date(2024, 1, 1) for part in parts)
    assert max(part.date_from + timedelta(days=part.days - 1) for part in parts) == date(2024, 8, 31)
    assert {part.product for part in parts} == {"VIIRS_NOAA20_SP"}
    assert len(parts) == 49


@pytest.mark.asyncio
async def test_quota_error_is_actionable_and_does_not_leak_map_key() -> None:
    secret = "secret-map-key"

    async def reject(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="Exceeding allowed transaction limit.")

    async with httpx.AsyncClient(
        base_url="https://firms.example", transport=httpx.MockTransport(reject)
    ) as client:
        with pytest.raises(firms.FirmsError, match="обновляется каждые 10 минут") as error:
            await firms._csv(client, f"/api/area/csv/{secret}/VIIRS_NOAA20_SP/world/5/2024-01-01")

    assert secret not in str(error.value)


@pytest.mark.asyncio
async def test_other_firms_http_errors_are_sanitized() -> None:
    secret = "secret-map-key"

    async def reject(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream unavailable")

    async with httpx.AsyncClient(
        base_url="https://firms.example", transport=httpx.MockTransport(reject)
    ) as client:
        with pytest.raises(firms.FirmsError, match="HTTP 503") as error:
            await firms._csv(client, f"/api/area/csv/{secret}/VIIRS_NOAA20_SP/world/5/2024-01-01")

    assert secret not in str(error.value)


def test_viirs_csv_maps_satellites_confidence_and_night() -> None:
    first, second = firms.parse_detections(DETECTIONS, "VIIRS_NOAA20_SP")

    assert first.satellite == "NOAA20"
    assert first.confidence == 1.0
    assert first.frp_mw == 8.4
    assert first.acquired_at == datetime(2024, 8, 16, 7, 32, tzinfo=UTC)
    assert second.satellite == "NOAA21"
    assert second.confidence == 0.66
    assert second.is_night is True
    assert first.external_id != second.external_id


def test_unexpected_firms_response_has_clear_error() -> None:
    with pytest.raises(firms.FirmsError, match="неожиданный ответ"):
        firms.parse_detections("Invalid MAP_KEY", "VIIRS_SNPP_NRT")


@pytest.mark.asyncio
async def test_large_area_keeps_hotspots_and_skips_only_burns(monkeypatch) -> None:
    hotspot_result = {"status": "ready", "imported": 12, "existing": 0, "products": ["VIIRS_NOAA20_SP"]}
    monkeypatch.setattr(router.firms, "import_hotspots", AsyncMock(return_value=hotspot_result))
    monkeypatch.setattr(
        router.acquisitions,
        "request_acquisition",
        AsyncMock(side_effect=acquisitions.InvalidAcquisitionError("Область не помещается в 4 чипа")),
    )
    body = router.AcquisitionBody(
        geometry=box(92.7, 55.9, 93.2, 56.3).__geo_interface__,
        date_pre=date(2024, 8, 1),
        date_post=date(2024, 8, 20),
    )

    result = await router.create_acquisition(body, SimpleNamespace())

    assert result["hotspots"] == hotspot_result
    assert result["burns"]["status"] == "skipped"
    assert result["jobs"] == []


@pytest.mark.asyncio
async def test_missing_firms_key_does_not_block_burn_queue(monkeypatch) -> None:
    monkeypatch.setattr(
        router.firms,
        "import_hotspots",
        AsyncMock(side_effect=firms.FirmsError("Для загрузки термоточек укажите FIRMS_MAP_KEY")),
    )
    jobs = [{"job_id": "job", "scene_id": "scene"}]
    monkeypatch.setattr(router.acquisitions, "request_acquisition", AsyncMock(return_value=jobs))
    body = router.AcquisitionBody(
        geometry=box(92.80, 55.98, 92.90, 56.05).__geo_interface__,
        date_pre=date(2024, 8, 1),
        date_post=date(2024, 8, 20),
    )

    result = await router.create_acquisition(body, SimpleNamespace())

    assert result["hotspots"]["status"] == "unavailable"
    assert result["burns"] == {"status": "queued", "jobs": 1}
