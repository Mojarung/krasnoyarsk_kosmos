from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from shapely.geometry import Point, shape

from firewatch.services import response as rp


def _cluster(**overrides: object) -> rp.FireCluster:
    values: dict[str, object] = {
        "day": date(2024, 8, 16),
        "last_seen": datetime(2024, 8, 16, 10, 30, tzinfo=UTC),
        "lon": 45.0,
        "lat": 47.0,
        "hotspots": 6,
        "prev_hotspots": 0,
        "frp_mw": 60.0,
        "frp_max_mw": 25.0,
        "landcover": "grass",
        "wind_speed": 5.0,
        "rh2m": 20.0,
        "t2m": 305.0,
        "is_night": False,
        "hull_m2": 400_000.0,
    }
    return rp.FireCluster(**(values | overrides))  # type: ignore[arg-type]


def test_grass_front_runs_at_fifth_of_wind_speed_in_dry_air() -> None:
    assert rp.spread_rate_kmh("grass", 5.0, 20.0) == pytest.approx(3.6)


def test_forest_front_is_twice_slower_than_grass() -> None:
    assert rp.spread_rate_kmh("forest", 5.0, 20.0) == pytest.approx(1.8)


def test_humid_air_damps_front_to_floor_factor() -> None:
    assert rp.spread_rate_kmh("grass", 5.0, 80.0) == pytest.approx(3.6 * 0.15)


def test_spread_rate_is_unknown_without_wind() -> None:
    assert rp.spread_rate_kmh("grass", None, 20.0) is None


def test_calm_air_keeps_minimal_creeping_rate() -> None:
    assert rp.spread_rate_kmh("forest", 0.0, 20.0) == pytest.approx(0.05)


def test_ellipse_stretches_downwind_and_keeps_origin_inside() -> None:
    # Ветер дует с запада (270), фронт уходит на восток.
    ellipse = shape(rp.spread_ellipse(45.0, 47.0, heading_deg=90.0, head_km=6.0, radius_m=300.0, wind_ms=6.0))
    west, _, east, _ = ellipse.bounds
    assert ellipse.contains(Point(45.0, 47.0))
    assert (east - 45.0) > 5 * (45.0 - west)


def test_heading_is_opposite_to_wind_direction() -> None:
    assert rp.heading_from_wind(270.0) == pytest.approx(90.0)
    assert rp.heading_from_wind(10.0) == pytest.approx(190.0)


def test_threatened_settlement_raises_priority_level() -> None:
    calm = rp.priority(_cluster(), ros_kmh=3.6, exposure=0.0)
    exposed = rp.priority(_cluster(), ros_kmh=3.6, exposure=1.0)
    assert exposed["score"] - calm["score"] == pytest.approx(15, abs=0.1)


def test_strong_growing_forest_fire_in_wind_is_critical() -> None:
    cluster = _cluster(
        landcover="forest",
        hotspots=30,
        prev_hotspots=10,
        frp_mw=900.0,
        frp_max_mw=180.0,
        wind_speed=11.0,
        rh2m=15.0,
    )
    assert rp.priority(cluster, ros_kmh=4.0, exposure=1.0)["level"] == "critical"


def test_single_weak_pixel_in_humid_calm_is_observation_only() -> None:
    cluster = _cluster(hotspots=1, prev_hotspots=3, frp_mw=2.0, frp_max_mw=2.0, wind_speed=1.0, rh2m=70.0)
    assert rp.priority(cluster, ros_kmh=0.1, exposure=0.0)["level"] == "low"


@pytest.mark.parametrize(
    ("overrides", "ros", "expected"),
    [
        ({"landcover": "grass", "wind_speed": 2.0}, 0.5, "grass_direct"),
        ({"landcover": "crop"}, 3.6, "grass_indirect"),
        ({"landcover": "forest", "frp_max_mw": 20.0, "wind_speed": 3.0}, 1.0, "forest_direct"),
        ({"landcover": "forest", "frp_max_mw": 150.0}, 1.0, "forest_indirect"),
        ({"landcover": "shrub", "wind_speed": 9.0}, 1.0, "forest_indirect"),
        ({"landcover": "wetland"}, 1.0, "wetland"),
    ],
)
def test_method_follows_fuel_and_intensity(overrides: dict[str, object], ros: float, expected: str) -> None:
    assert rp.choose_method(_cluster(**overrides), ros) == expected


def test_card_names_threatened_settlement_with_arrival_horizon() -> None:
    context = rp.GeoContext(
        settlements=[rp.Place(name="Хутор Степной", kind="village", lon=45.06, lat=47.0)],
        fire_stations=[rp.Place(name="ПЧ-12", kind="fire_station", lon=44.8, lat=47.0)],
        water=[],
        road_km=0.4,
    )
    card = rp.build_card(_cluster(), wind_dir_deg=270.0, context=context)

    threatened = card["threats"][0]
    assert threatened["name"] == "Хутор Степной"
    assert threatened["horizon_h"] == 3
    assert card["steps"][0].startswith("Под угрозой Хутор Степной")
    assert card["arrival"]["station"] == "ПЧ-12"
    assert card["arrival"]["eta_min"] == pytest.approx(15.2 * 1.4 / 50 * 60, rel=0.05)


def test_card_without_osm_context_degrades_gracefully() -> None:
    card = rp.build_card(_cluster(), wind_dir_deg=None, context=None)

    assert card["spread"]["ellipses"] == []
    assert card["spread"]["rate_kmh"] == pytest.approx(3.6)
    assert card["threats"] is None
    assert card["arrival"] is None
    assert card["method"]["key"] == "grass_indirect"


def test_remote_fire_gets_aviation_note() -> None:
    context = rp.GeoContext(settlements=[], fire_stations=[], water=[], road_km=7.5)
    card = rp.build_card(_cluster(landcover="forest"), wind_dir_deg=180.0, context=context)
    assert any("по воздуху" in step for step in card["steps"])


def test_overpass_answer_is_split_between_fires_by_their_radii() -> None:
    from firewatch.infra import geodata

    points = [(45.0, 47.0, 10.0), (40.0, 50.0, 10.0)]
    elements = [
        {"type": "node", "lon": 45.05, "lat": 47.0, "tags": {"place": "village", "name": "Ближнее"}},
        {"type": "node", "lon": 40.02, "lat": 50.0, "tags": {"place": "town", "name": "Дальнее"}},
        {
            "type": "way",
            "center": {"lon": 45.2, "lat": 47.0},
            "tags": {"amenity": "fire_station", "name": "ПЧ-3"},
        },
        {
            "type": "way",
            "geometry": [{"lon": 45.0, "lat": 47.01}, {"lon": 45.1, "lat": 47.01}],
        },
    ]

    first, second = geodata.parse_overpass(points, elements)

    assert [p["name"] for p in first["settlements"]] == ["Ближнее"]
    assert [p["name"] for p in second["settlements"]] == ["Дальнее"]
    assert first["fire_stations"][0]["name"] == "ПЧ-3" and second["fire_stations"] == []
    assert first["road_km"] == pytest.approx(1.11, abs=0.02)
    assert second["road_km"] == geodata.ROAD_RADIUS_M / 1000.0


def test_one_overpass_query_covers_every_fire() -> None:
    from firewatch.infra import geodata

    query = geodata.overpass_query([(45.0, 47.0, 10.0), (40.0, 50.0, 25.0)], timeout=30)

    assert query.count("[place~") == 2
    assert "(around:10000,47.0,45.0)" in query and "(around:25000,50.0,40.0)" in query
