from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from firewatch.services import hotspot_acquisition as service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "job_status,event_status,expected",
    [
        ("queued", "hotspot_only", "running"),
        ("running", "hotspot_only", "running"),
        ("failed", "hotspot_only", "failed"),
        ("done", "hotspot_only", "not_found"),
        ("done", "linked", "found"),
        ("done", "ambiguous", "ambiguous"),
    ],
)
async def test_status_resolves_original_hotspot_after_event_id_changes(
    monkeypatch, job_status, event_status, expected
):
    scene = SimpleNamespace(id="scene", stats={"acquisition": {"anchor_id": 7, "request_id": "request"}})
    job = SimpleNamespace(id="job", status=job_status, stage=job_status, progress=0, error=None)
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(all=lambda: [(scene, job)])))
    monkeypatch.setattr(
        service.events,
        "index",
        AsyncMock(
            return_value={"events": [{"id": "new-id", "status": event_status, "hotspots": [{"id": 7}]}]}
        ),
    )
    result = await service.state(session, "old-id")
    assert result["status"] == expected
    assert result["event_id"] == "new-id"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "found", "not_found", "ambiguous"])
async def test_existing_request_is_not_duplicated_even_with_retry(monkeypatch, status):
    session = SimpleNamespace(execute=AsyncMock())
    current = {"status": status, "jobs": [{"id": "existing"}]}
    monkeypatch.setattr(service, "state", AsyncMock(return_value=current))
    create = AsyncMock()
    monkeypatch.setattr(service.acquisitions, "request_acquisition", create)
    assert await service.start(session, "event", retry=True) == current
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_event_cannot_start_download(monkeypatch):
    session = SimpleNamespace(execute=AsyncMock())
    monkeypatch.setattr(service, "state", AsyncMock(return_value={"status": "idle", "event_id": None}))
    monkeypatch.setattr(service.events, "index", AsyncMock(return_value={"events": []}))
    with pytest.raises(service.acquisitions.InvalidAcquisitionError, match="не найдено"):
        await service.start(session, "missing")
