from datetime import date

import pytest

from firewatch.agent.fallback import parse_request
from firewatch.services.query import InvalidQueryError, SpatioTemporalQuery
from firewatch.services.restoration import build_plan

DATA_RANGE = (date(2019, 4, 1), date(2024, 11, 2))


def build(**overrides):
    params = {
        "geometry": None,
        "bbox": (44.0, 45.5, 46.5, 47.5),
        "date_from": date(2020, 4, 1),
        "date_to": date(2020, 10, 31),
    }
    return SpatioTemporalQuery.build(**(params | overrides))


def test_bbox_becomes_closed_polygon() -> None:
    query = build()

    assert query.geometry["type"] == "Polygon"
    assert query.geometry["coordinates"][0][0] == query.geometry["coordinates"][0][-1]


@pytest.mark.parametrize(
    "overrides",
    [
        {"date_from": date(2021, 1, 1)},
        {"bbox": None},
        {"bbox": (46.5, 45.5, 44.0, 47.5)},
        {"bbox": (384000.0, 5280000.0, 480000.0, 5376000.0)},
        {"geometry": {"type": "Point", "coordinates": [45.0, 46.0]}},
        {"geometry": {"type": "Polygon"}},
    ],
)
def test_invalid_query_is_rejected(overrides) -> None:
    with pytest.raises(InvalidQueryError):
        build(**overrides)


def test_self_intersecting_polygon_is_repaired() -> None:
    bowtie = {"type": "Polygon", "coordinates": [[[44, 45], [46, 47], [46, 45], [44, 47], [44, 45]]]}

    query = build(geometry=bowtie)

    assert query.geometry["type"] in ("Polygon", "MultiPolygon")


def test_agent_parses_region_month_and_year() -> None:
    parsed = parse_request("Покажи гари в Калмыкии за июль 2023", DATA_RANGE)

    assert parsed.region.id == "kalmykia"
    assert (parsed.date_from, parsed.date_to) == (date(2023, 7, 1), date(2023, 7, 31))


def test_agent_year_without_month_means_fire_season() -> None:
    parsed = parse_request("что горело в ростовской области в 2020-2021 годах", DATA_RANGE)

    assert parsed.region.id == "rostov"
    assert (parsed.date_from, parsed.date_to) == (date(2020, 4, 1), date(2021, 10, 31))


def test_agent_does_not_take_years_word_for_summer() -> None:
    parsed = parse_request("сколько сгорело за 5 лет под Астраханью", DATA_RANGE)

    assert parsed.region.id == "astrakhan"
    assert (parsed.date_from, parsed.date_to) == DATA_RANGE
    assert not parsed.period_recognized


def test_agent_falls_back_to_whole_aoi() -> None:
    parsed = parse_request("привет", DATA_RANGE)

    assert parsed.region.id == "aoi"
    assert not parsed.region_recognized


def test_restoration_plan_routes_severe_forest_to_planting() -> None:
    plan = build_plan({(3, "forest"): 10.0, (1, "grass"): 40.0, (2, "crop"): 5.0})

    by_action = {item["action"]: item for item in plan["items"]}
    assert by_action["planting"]["area_ha"] == 10.0
    assert by_action["planting"]["counts_as_damage"]
    assert plan["damage_area_ha"] == 10.0
    assert plan["natural_area_ha"] == 40.0
    assert plan["total_cost"] == sum(item["cost"] for item in plan["items"])
