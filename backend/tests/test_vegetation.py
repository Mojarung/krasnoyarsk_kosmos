import io
from datetime import date

import numpy as np
import pytest
from PIL import Image
from pyproj import Transformer
from shapely.geometry import box, mapping
from shapely.ops import transform

from firewatch.services import vegetation as v


def geom(side=1000):
    return mapping(
        transform(
            Transformer.from_crs(32638, 4326, always_xy=True).transform,
            box(400000, 5400000, 400000 + side, 5400000 + side),
        )
    )


def test_years_and_incomplete_season():
    assert v.years_for("2020-10-10", date(2026, 9, 19)) == list(range(2019, 2027))
    assert v.years_for("2020-10-10", date(2026, 7, 15))[-1] == 2025
    assert v.years_for("2017-04-10", date(2026, 9, 19))[0] == 2017
    with pytest.raises(ValueError):
        v.years_for("2030-01-01", date(2026, 9, 19))


def test_grid_is_metric_and_bounded():
    grid = v.make_grid(geom(), 32638)
    assert grid["mask"].sum() == 2500
    assert grid["transform"].a == 20 and grid["transform"].e == -20
    assert grid["mask"].sum() * 0.04 == 100
    with pytest.raises(ValueError, match="протяжённая"):
        v.make_grid(geom(50000), 32638)


def test_reflectance_offset_and_nodata():
    raw = np.array([0, 2000, 6000], dtype=np.uint16)
    result = v.reflectance(raw, {"scale": 0.0001, "offset": -0.1, "nodata": 0})
    assert np.isnan(result[0])
    np.testing.assert_allclose(result[1:], [0.1, 0.5], atol=1e-7)
    # Applying no offset would change NDVI from 2/3 to 1/2.
    assert (result[2] - result[1]) / (result[2] + result[1]) == pytest.approx(2 / 3)


def test_pc_coefficients_use_product_metadata():
    xml = b'<root><BOA_QUANTIFICATION_VALUE>10000</BOA_QUANTIFICATION_VALUE><BOA_ADD_OFFSET band_id="3">-1000</BOA_ADD_OFFSET><BOA_ADD_OFFSET band_id="7">-900</BOA_ADD_OFFSET><BOA_ADD_OFFSET band_id="12">-800</BOA_ADD_OFFSET></root>'
    assert v.pc_coefficients(xml) == {
        "red": (0.0001, -0.1),
        "nir": (0.0001, -0.09),
        "swir22": (0.0001, -0.08),
    }


@pytest.mark.parametrize(
    "href",
    [
        "http://127.0.0.1/x.tif",
        "https://example.com/x.tif",
        f"https://{v.EARTH_HOST}.example.com/x.tif",
        f"https://u:p@{v.EARTH_HOST}/x.tif",
        f"https://{v.EARTH_HOST}:8000/x.tif",
    ],
)
def test_asset_origin_allowlist(href):
    with pytest.raises(ValueError):
        v.asset_url(href)


def sample(value, valid=None):
    return {
        "ndvi": np.full((10, 10), value),
        "valid": np.ones((10, 10), bool) if valid is None else valid,
        "rgb": np.zeros((10, 10, 3), dtype=np.uint8),
    }


def test_common_pixels_and_no_claim_below_quality_threshold():
    mask = np.ones((10, 10), bool)
    valid = mask.copy()
    valid[:3] = False
    stats, rgb = v.compare(sample(0.2), sample(0.5, valid), mask)
    assert stats["delta_ndvi"] is None and stats["common_share"] == 0.7
    assert stats["compared_ha"] == 2.8
    assert rgb.shape == (10, 10, 3)
    assert Image.open(io.BytesIO(v.webp(rgb))).size == (10, 10)
    valid[2] = True
    stats, _ = v.compare(sample(0.2), sample(0.5, valid), mask)
    assert stats["delta_ndvi"] == 0.3 and stats["common_share"] == 0.8
    # Values from unobserved pixels may never affect the paired statistic.
    frame = sample(0.5, valid)
    frame["ndvi"][~valid] = -0.9
    stats, _ = v.compare(sample(0.2), frame, mask)
    assert stats["delta_ndvi"] == 0.3


def test_empty_common_mask_and_union_mask():
    mask = np.ones((10, 10), bool)
    stats, rgb = v.compare(sample(0.1), sample(0.7, ~mask), mask)
    assert stats["current_ndvi"] is None and stats["compared_ha"] == 0
    assert np.isfinite(rgb).all()


def test_cache_identity_includes_geometry_season_and_version():
    assert v.fingerprint({"a": 1, "b": 2}, [2020]) == v.fingerprint({"b": 2, "a": 1}, [2020])
    assert v.fingerprint({"a": 1}, [2020]) != v.fingerprint({"a": 1}, [2020, 2021])


def test_rgb_and_scl_do_not_require_spectral_metadata():
    assets = {k: {"href": f"https://{v.EARTH_HOST}/{k}.tif"} for k in v.KEYS}
    for k in ("red", "nir", "swir22"):
        assets[k]["raster:bands"] = [{"scale": 0.0001, "offset": -0.1}]
    result = v.prepare_assets({"provider": "earth", "assets": assets})
    assert result["visual"]["band"] == result["scl"]["band"] == {}
    assert result["red"]["band"]["offset"] == -0.1


@pytest.mark.parametrize("failure", ["catalog", "download", "clouds", "empty"])
def test_fallback_after_primary_failure_or_poor_coverage(monkeypatch, failure):
    seen = []
    grid = {"mask": np.ones((10, 10), bool)}

    def candidates(grid, year, provider):
        seen.append(provider)
        if provider == "earth":
            if failure == "catalog":
                raise RuntimeError("unavailable")
            if failure == "empty":
                return []
        return [{"id": provider, "provider": provider}]

    def read(grid, item):
        if item["provider"] == "earth":
            if failure == "download":
                raise RuntimeError("unavailable")
            return sample(0.3, np.zeros((10, 10), bool))
        return sample(0.5)

    monkeypatch.setattr(v, "candidates", candidates)
    monkeypatch.setattr(v, "read_frame", read)
    _frame, item, share = v.acquire_year(grid, 2022)
    assert seen == ["earth", "planetary"]
    assert item["provider"] == "planetary" and share == 1


def test_catalog_empty_is_not_a_download_error(monkeypatch):
    monkeypatch.setattr(v, "candidates", lambda *a: [])
    assert v.acquire_year({"mask": np.ones((10, 10), bool)}, 2022)[0] is None

    def fail(*a):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(v, "candidates", fail)
    with pytest.raises(RuntimeError, match="временно недоступен"):
        v.acquire_year({"mask": np.ones((10, 10), bool)}, 2022)


@pytest.mark.asyncio
async def test_stale_worker_requires_expired_lease(monkeypatch):
    from datetime import UTC, datetime, timedelta

    from firewatch.api.routers import vegetation as router

    report = {
        "id": "job",
        "status": "running",
        "updated_at": (datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
    }

    async def exists(*args):
        return True

    monkeypatch.setattr(router.redis, "exists", exists)
    assert not await router.stalled(report)

    async def absent(*args):
        return False

    monkeypatch.setattr(router.redis, "exists", absent)
    assert await router.stalled(report)
    report["status"] = "ready"
    assert not await router.stalled(report)


@pytest.mark.asyncio
@pytest.mark.parametrize("observation_day", ["06-30", "07-15"])
async def test_worker_latest_first_baseline_then_history_and_resumable_cache(monkeypatch, observation_day):
    source = {"geometry": geom(100), "epsg": 32638, "date_from": "2020-10-01", "date_to": "2020-11-01"}
    report = {"id": "job", "status": "queued", "source": source, "years": [2019, 2020, 2021], "frames": []}
    store, loaded = {}, []
    monkeypatch.setattr(v.s3, "put_bytes", lambda key, body, mime: store.__setitem__(key, body))
    monkeypatch.setattr(v.s3, "get_bytes", lambda key: store[key])
    monkeypatch.setattr(v.s3, "exists", lambda key: key in store)

    async def set_lock(*a, **kw):
        return True

    async def unlock(*a):
        pass

    monkeypatch.setattr(v.redis, "set", set_lock)
    monkeypatch.setattr(v, "unlock", unlock)
    monkeypatch.setattr(
        v,
        "candidates",
        lambda grid, year, provider: [
            {
                "id": str(year),
                "provider": provider,
                "properties": {
                    "datetime": f"{year}-{'06-30' if year == 2019 else observation_day}T00:00:00Z"
                },
            }
        ],
    )

    def read(grid, item):
        loaded.append(item["id"])
        mask = grid["mask"]
        return {
            "ndvi": np.full(mask.shape, 0.5),
            "nbr": np.full(mask.shape, 0.3),
            "valid": mask,
            "rgb": np.zeros((*mask.shape, 3), dtype=np.uint8),
        }

    monkeypatch.setattr(v, "read_frame", read)
    v.save_report(report)
    await v.process("job")
    result = v.read_report("job")
    assert loaded == ["2021", "2019", "2020"]
    assert result["status"] == "ready"
    assert [f["role"] for f in result["frames"]] == ["before", "before", "after"]
    assert result["frames"][-1]["comparison"]["delta_ndvi"] == (0 if observation_day == "06-30" else None)
    assert "source" not in v.public(result)
    await v.process("job")
    assert len(loaded) == 3  # persisted result, no satellite re-download
    result["status"] = "partial"
    result["frames"][1] = {"year": 2020, "status": "error"}
    v.save_report(result)
    await v.process("job")
    assert loaded == ["2021", "2019", "2020", "2020"]
    assert v.read_report("job")["status"] == "ready"
