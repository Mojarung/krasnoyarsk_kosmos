import asyncio

import pytest

from firewatch.services import tiles


@pytest.mark.asyncio
async def test_interactive_tile_rendering_has_a_shared_limit(monkeypatch):
    active = peak = 0

    async def render(*args):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return b"tile"

    async def cache(prefix, payload, producer, **kwargs):
        return await producer()

    monkeypatch.setattr(tiles, "_render_gate", asyncio.Semaphore(4))
    monkeypatch.setattr(tiles, "cached", cache)
    monkeypatch.setattr(tiles, "render_tile", render)
    results = await asyncio.gather(*(tiles.cached_tile(None, 10, x, 10) for x in range(16)))
    assert results == [b"tile"] * 16
    assert peak == 4


@pytest.mark.asyncio
async def test_warm_limit_is_shared_between_region_requests(monkeypatch):
    active = peak = 0

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    async def tile(*args):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.001)
        active -= 1
        return b"tile"

    monkeypatch.setattr(tiles, "_warm_gate", asyncio.Semaphore(tiles.WARM_CONCURRENCY))
    monkeypatch.setattr(tiles, "SessionFactory", Session)
    monkeypatch.setattr(tiles, "cached_tile", tile)
    await asyncio.gather(*(tiles.warm_tiles([(lon, 48)]) for lon in [42, 44, 46]))
    assert peak == tiles.WARM_CONCURRENCY
