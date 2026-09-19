from __future__ import annotations

import random
from datetime import UTC, date, datetime

import numpy as np
import pytest
from affine import Affine
from shapely.geometry import Point, box

from firewatch.infra import stac
from firewatch.pipeline import acquire as aq
from firewatch.services import acquisitions as acq


def _item(**overrides: object) -> stac.S2Item:
    values: dict[str, object] = {
        "id": "S2A_38UMU_20240816_0_L2A",
        "acquired": datetime(2024, 8, 16, 8, 6, tzinfo=UTC),
        "cloud_cover": 5.0,
        "epsg": 32638,
        "footprint": box(44.0, 47.0, 46.0, 49.0),
        "assets": {},
        "boa_offset": 0,
        "tile": "MGRS-38UMU",
        "origin": (399960.0, 5400000.0),
    }
    return stac.S2Item(**(values | overrides))  # type: ignore[arg-type]


def test_utm_zone_follows_longitude_and_hemisphere() -> None:
    assert aq.utm_epsg(44.9, 48.5) == 32638
    assert aq.utm_epsg(37.6, 55.7) == 32637
    assert aq.utm_epsg(-58.4, -34.6) == 32721


def test_small_area_becomes_one_chip_on_twenty_metre_grid() -> None:
    grids = aq.plan_grids(Point(44.9, 48.5).buffer(0.01), max_chips=4)

    assert len(grids) == 1
    west, south, east, north = grids[0].bounds
    assert (east - west, north - south) == (aq.CHIP_M, aq.CHIP_M)
    assert west % aq.GSD_M == 0 and north % aq.GSD_M == 0
    assert grids[0].footprint_wgs84().contains(Point(44.9, 48.5))


def test_two_by_two_chip_area_fits_the_budget() -> None:
    grids = aq.plan_grids(box(44.80, 48.42, 45.05, 48.58), max_chips=4)
    assert len(grids) == 4


def test_area_larger_than_budget_is_rejected_not_cropped() -> None:
    with pytest.raises(aq.AreaTooLargeError, match="не помещается"):
        aq.plan_grids(box(44.0, 48.0, 45.0, 48.6), max_chips=4)


def test_continent_sized_area_is_rejected_immediately() -> None:
    with pytest.raises(aq.AreaTooLargeError):
        aq.plan_grids(box(20.0, 40.0, 80.0, 70.0), max_chips=4)


def test_neighbour_chips_share_an_edge_without_gaps() -> None:
    left, right = aq.plan_grids(box(44.80, 48.48, 45.02, 48.52), max_chips=2)
    assert left.bounds[2] == right.bounds[0]


def test_chip_snaps_to_cog_block_lattice_of_the_tile() -> None:
    grid = aq.ChipGrid(epsg=32638, transform=Affine(20.0, 0.0, 491520.0, 0.0, -20.0, 5386240.0))

    snapped = aq.snap_to_blocks(grid, _item())

    west, _, _, north = snapped.bounds
    assert (west - 399960.0) % aq.CHIP_M == 0
    assert (5400000.0 - north) % aq.CHIP_M == 0
    assert abs(west - 491520.0) <= aq.CHIP_M / 2 and abs(north - 5386240.0) <= aq.CHIP_M / 2


def test_chip_is_not_snapped_to_a_tile_from_another_utm_zone() -> None:
    grid = aq.ChipGrid(epsg=32638, transform=Affine(20.0, 0.0, 491520.0, 0.0, -20.0, 5386240.0))
    assert aq.snap_to_blocks(grid, _item(epsg=32637)) == grid


def test_flat_terrain_has_zero_slope_and_ramp_has_known_angle() -> None:
    flat = np.full((16, 16), 120.0)
    ramp = np.tile(np.arange(16, dtype=np.float32) * 20.0, (16, 1))

    assert aq.slope_degrees(flat, 20.0).max() == 0.0
    assert aq.slope_degrees(ramp, 20.0)[8, 8] == pytest.approx(45.0, abs=0.1)


def test_worldcover_tile_name_uses_three_degree_south_west_corner() -> None:
    assert aq.worldcover_tiles((44.8, 48.4, 44.95, 48.5)) == [aq.WORLDCOVER_URL.format(tile="N48E042")]


def test_chip_across_tile_border_needs_both_worldcover_tiles() -> None:
    assert len(aq.worldcover_tiles((44.95, 48.4, 45.05, 48.5))) == 2


def test_ranking_prefers_full_coverage_then_native_zone_then_clear_sky() -> None:
    area = box(44.8, 48.4, 44.95, 48.5)
    partial = _item(id="partial", footprint=box(44.9, 48.0, 46.0, 49.0), cloud_cover=0.0)
    foreign = _item(id="foreign", epsg=32637, cloud_cover=0.0)
    cloudy = _item(id="cloudy", cloud_cover=60.0)
    clear = _item(id="clear", cloud_cover=4.0)

    ranked = stac.rank_items([partial, foreign, cloudy, clear], area, date(2024, 8, 16), 32638)

    assert [item.id for item in ranked] == ["clear", "cloudy", "foreign"]


def test_ranking_keeps_the_tile_of_the_post_image() -> None:
    area = box(44.8, 48.4, 44.95, 48.5)
    other = _item(id="other", tile="MGRS-38ULU", cloud_cover=0.0)
    same = _item(id="same", cloud_cover=30.0)

    ranked = stac.rank_items([other, same], area, date(2024, 8, 16), 32638, tile="MGRS-38UMU")

    assert ranked[0].id == "same"


def test_new_baseline_without_applied_offset_is_shifted_back() -> None:
    feature = {
        "id": "x",
        "geometry": box(0, 0, 1, 1).__geo_interface__,
        "properties": {
            "datetime": "2024-08-16T08:06:48Z",
            "s2:processing_baseline": "05.11",
            "earthsearch:boa_offset_applied": False,
            "proj:code": "EPSG:32638",
        },
        "assets": {
            "nir08": {"href": "s3://bucket/key/B8A.tif", "proj:transform": [20, 0, 399960, 0, -20, 5400000]}
        },
    }

    item = stac.parse_s2_item(feature)

    assert item.boa_offset == 1000
    assert item.epsg == 32638
    assert item.origin == (399960.0, 5400000.0)
    assert item.assets["nir08"] == "https://bucket.s3.amazonaws.com/key/B8A.tif"


def test_dates_too_close_or_too_fresh_are_rejected() -> None:
    today = date(2026, 9, 19)
    with pytest.raises(acq.InvalidAcquisitionError, match="от 5 до 120"):
        acq.validate_dates(date(2026, 8, 1), date(2026, 8, 3), today)
    with pytest.raises(acq.InvalidAcquisitionError, match="не позже"):
        acq.validate_dates(date(2026, 8, 20), date(2026, 9, 18), today)
    acq.validate_dates(date(2026, 8, 1), date(2026, 9, 1), today)


def test_random_point_falls_inside_area_of_interest() -> None:
    point = acq.random_point(random.Random(7))
    assert acq._aoi().contains(point)


def test_chip_square_is_one_chip_wide_around_the_point() -> None:
    square = acq.chip_square(44.9, 48.5)
    assert square.contains(Point(44.9, 48.5))
    assert len(aq.plan_grids(square, max_chips=4)) == 1


def test_fire_dates_exclude_same_day_and_wrong_side(monkeypatch):
    grid = aq.plan_grids(Point(44.9, 48.5).buffer(0.001), 1)[0]
    items = [_item(id=str(day), acquired=datetime(2024, 8, day, tzinfo=UTC)) for day in (14, 15, 16)]
    monkeypatch.setattr(stac, "search_s2", lambda *args: items)
    monkeypatch.setattr(aq, "read_scl", lambda *args: np.full((512, 512), 4))
    assert aq.pick_item(grid, date(2024, 8, 15), 15, 3, before=date(2024, 8, 15))[0].id == "14"
    assert aq.pick_item(grid, date(2024, 8, 15), 15, 3, after=date(2024, 8, 15))[0].id == "16"
    with pytest.raises(stac.NoImageryError):
        aq.pick_item(grid, date(2024, 8, 15), 15, 3, after=date(2024, 8, 17))


def test_fire_quality_checks_hotspot_not_average_tile(monkeypatch, tmp_path):
    grid = aq.plan_grids(Point(44.9, 48.5).buffer(0.001), 1)[0]
    # Almost all of the image is clear, but the hotspot itself is obscured.
    scl = np.full((512, 512), 4)
    scl[200:312, 200:312] = 9
    calls = []

    def pick(grid, target, *args, **kwargs):
        calls.append(kwargs)
        return _item(acquired=datetime.combine(target, datetime.min.time(), UTC)), scl

    monkeypatch.setattr(aq, "pick_item", pick)
    monkeypatch.setattr(aq, "snap_to_blocks", lambda *args: pytest.fail("Must not shift the target"))
    with pytest.raises(stac.NoImageryError, match="Недостаточно ясных"):
        aq.assemble_chip(
            grid,
            date(2024, 8, 1),
            date(2024, 8, 20),
            tmp_path,
            days=15,
            candidates=3,
            fire_context={
                "fire_start": "2024-08-10",
                "fire_end": "2024-08-12",
                "target_geometry": Point(44.9, 48.5).buffer(0.001).__geo_interface__,
            },
        )
    assert calls[0]["after"] == date(2024, 8, 12)
    assert calls[1]["before"] == date(2024, 8, 10)


def test_pick_prefers_clear_hotspot_even_if_rest_of_tile_cloudy(monkeypatch):
    grid = aq.plan_grids(Point(44.9, 48.5).buffer(0.001), 1)[0]
    items = [_item(id="cloudy_point"), _item(id="clear_point")]
    mask = np.zeros((512, 512), bool)
    mask[250:260, 250:260] = True

    def scl(item, grid):
        result = np.full((512, 512), 4 if item.id == "cloudy_point" else 9)
        result[mask] = 9 if item.id == "cloudy_point" else 4
        return result

    monkeypatch.setattr(stac, "search_s2", lambda *args: items)
    monkeypatch.setattr(aq, "read_scl", scl)
    assert aq.pick_item(grid, date(2024, 8, 16), 15, 3, mask=mask)[0].id == "clear_point"
