from copy import deepcopy
from unittest.mock import AsyncMock

import numpy as np
import pytest
from pyproj import Transformer
from shapely.geometry import box, mapping, shape
from shapely.ops import transform, unary_union

from firewatch.services import vegetation
from firewatch.services import work_map as wm


def scene(id="one", day="2020-07-01", severity=3, geom=None):
    geom = geom if geom is not None else box(500000, 5300000, 500100, 5300100)
    wgs = transform(Transformer.from_crs(32638, 4326, always_xy=True).transform, geom)
    return {
        "id": id,
        "epsg": 32638,
        "date_post": day,
        "processed_at": "stamp",
        "aux": id,
        "polygons": [{"severity": severity, "geometry": mapping(wgs)}],
    }


@pytest.mark.parametrize(
    "code,severity,action",
    [
        (10, 3, "planting"),
        (10, 2, "assisted"),
        (30, 1, "natural"),
        (40, 3, "agro"),
        (30, 3, "erosion"),
        (80, 3, "none"),
        (0, 3, "unknown"),
    ],
)
def test_published_pixels_and_rules(monkeypatch, code, severity, action):
    monkeypatch.setattr(wm, "landcover", lambda scene, grid: np.full(grid["mask"].shape, code))
    result = wm.calculate({"scenes": [scene(severity=severity)]})
    assert result["area_ha"] == pytest.approx(1, abs=1e-6)
    assert {f["properties"]["action"] for f in result["map"]["features"]} == {action}
    assert sum(f["properties"]["area_ha"] for f in result["map"]["features"]) == pytest.approx(
        result["area_ha"]
    )


def test_latest_scene_owns_overlap_and_nodata_is_not_replaced_by_old_cover(monkeypatch):
    monkeypatch.setattr(wm, "landcover", lambda s, g: np.full(g["mask"].shape, 0 if s["id"] == "new" else 10))
    result = wm.calculate({"scenes": [scene("old", severity=1), scene("new", "2020-07-02")]})
    assert result["area_ha"] == pytest.approx(1, abs=1e-6)
    assert result["totals"][0]["action"] == "unknown"


def test_equal_dates_have_stable_precedence_and_geometry_is_clipped(monkeypatch):
    monkeypatch.setattr(wm, "landcover", lambda s, g: np.full(g["mask"].shape, 10))
    narrow = box(500005, 5300005, 500095, 5300095)
    first, second = scene("a", severity=3, geom=narrow), scene("b", severity=1, geom=narrow)
    result = wm.calculate({"scenes": [second, first]})
    assert result["totals"][0]["action"] == "planting"
    original = shape(first["polygons"][0]["geometry"])
    union = unary_union([shape(f["geometry"]) for f in result["map"]["features"]])
    assert union.difference(original.buffer(1e-10)).area < 1e-12
    assert result["area_ha"] <= 0.810001


def test_fingerprint_changes_with_processing_and_rules(monkeypatch):
    data = {"event_id": "bs-test", "scenes": [scene()]}
    previous = wm.fingerprint(data)
    data["scenes"][0]["processed_at"] = "new-stamp"
    assert wm.fingerprint(data) != previous
    previous = wm.fingerprint(data)
    config = wm.rules()
    config["rules"]["forest"]["3"] = "assisted"
    monkeypatch.setattr(wm, "rules", lambda: config)
    assert wm.fingerprint(data) != previous


@pytest.mark.asyncio
async def test_repeated_start_reuses_job(monkeypatch):
    stored = {}
    data = {"event_id": "bs-test", "scenes": [scene()]}
    monkeypatch.setattr(wm, "source", AsyncMock(return_value=data))
    monkeypatch.setattr(wm.redis, "set", AsyncMock(return_value=True))
    monkeypatch.setattr(wm, "unlock", AsyncMock())
    monkeypatch.setattr(wm, "read", lambda job: deepcopy(stored.get(job)))

    def save(report):
        report["updated_at"] = wm.now()
        stored[report["id"]] = deepcopy(report)

    monkeypatch.setattr(wm, "save", save)
    publish = AsyncMock()
    monkeypatch.setattr(wm.broker, "publish", publish)
    first = await wm.request(None, "bs-test", True)
    second = await wm.request(None, "bs-test", True)
    assert first["id"] == second["id"]
    publish.assert_awaited_once()
    assert "source" not in second


def test_comparison_georeference_matches_common_grid():
    s = scene()
    source = {"geometry": s["polygons"][0]["geometry"], "epsg": 32638}
    grid = vegetation.make_grid(source["geometry"], source["epsg"])
    geo = vegetation.public({"source": source})["georef"]
    assert (geo["width"], geo["height"]) == (grid["width"], grid["height"])
    lon, lat = geo["corners"][0]
    x, y = Transformer.from_crs(4326, 32638, always_xy=True).transform(lon, lat)
    assert (x, y) == pytest.approx(grid["transform"] @ (0, 0), abs=1e-6)
