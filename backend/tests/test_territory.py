import json

import pytest
from shapely.geometry import box, mapping

from firewatch.services import territory


def _aoi() -> dict:
    return territory._asset("aoi.geojson")["features"][0]["geometry"]


def _region(region_id: str) -> dict:
    features = territory._asset("regions.geojson")["features"]
    return next(f["geometry"] for f in features if f["properties"]["id"] == region_id)


def test_whole_monitoring_area_is_named_by_its_own_name() -> None:
    place = territory.describe(_aoi())

    assert place["kind"] == "aoi"
    assert place["name"] == "Нижнее Поволжье и Подонье"


def test_subject_boundary_is_recognised_as_that_subject() -> None:
    place = territory.describe(_region("rostov"))

    assert place["kind"] == "region"
    assert place["name"] == "Ростовская область"
    assert place["subjects"][0]["whole"]


def test_polygon_inside_one_subject_is_named_after_it() -> None:
    patch = {
        "type": "Polygon",
        "coordinates": [[[44.5, 45.5], [46.0, 45.6], [46.2, 46.5], [44.7, 46.4], [44.5, 45.5]]],
    }

    place = territory.describe(patch)

    assert place["kind"] == "polygon"
    assert place["name"] == "Участок в Республике Калмыкия"
    assert place["subjects"][0]["share_of_query"] == pytest.approx(1.0, abs=0.01)


def test_rectangle_is_told_apart_from_a_drawn_polygon() -> None:
    assert territory.describe(mapping(box(41.0, 47.5, 43.5, 49.5)))["kind"] == "bbox"


def test_query_outside_the_monitoring_area_says_so_instead_of_naming_a_subject() -> None:
    place = territory.describe(mapping(box(36.5, 55.3, 38.2, 56.2)))

    assert place["subjects"] == []
    assert place["monitoring_area"]["covered_share"] == 0.0
    assert place["name"] == "Участок вне территории мониторинга"


def test_coverage_share_is_honest_when_the_query_sticks_out() -> None:
    """Прямоугольник шире границы мониторинга: за её пределами данных нет, и
    справка обязана сказать, какая доля запроса осталась без покрытия."""
    place = territory.describe(mapping(box(38.3, 44.6, 48.0, 52.7)))

    assert 0.6 < place["monitoring_area"]["covered_share"] < 0.8
    assert place["area_km2"] > place["monitoring_area"]["covered_km2"]


def test_area_is_geodesic_not_degrees() -> None:
    """Градус долготы на широте 48° примерно вдвое короче градуса широты.
    Площадь, посчитанная по плоским координатам, была бы завышена вдвое."""
    square = territory.describe(mapping(box(44.0, 47.5, 45.0, 48.5)))

    assert square["area_km2"] == pytest.approx(8_300, rel=0.05)


def test_subject_shares_of_a_cross_border_rectangle_sum_to_the_query() -> None:
    place = territory.describe(mapping(box(41.0, 47.5, 43.5, 49.5)))

    assert {s["id"] for s in place["subjects"]} == {"rostov", "volgograd"}
    assert sum(s["share_of_query"] for s in place["subjects"]) == pytest.approx(1.0, abs=0.02)


def test_map_outlines_carry_every_subject_with_a_label_point() -> None:
    outlines = territory.map_outlines()

    assert outlines["aoi"] and all(len(ring) >= 4 for ring in outlines["aoi"])
    assert len(outlines["regions"]) == 5
    for region in outlines["regions"]:
        assert region["rings"]
        assert len(region["label_at"]) == 2
        assert region["short"] and " " not in region["short"]


def test_describe_survives_a_round_trip_through_json() -> None:
    """Паспорт территории уезжает в JSON, CSV и XLSX: в нём не должно быть
    типов, которые json не сериализует."""
    place = territory.describe(mapping(box(41.0, 47.5, 43.5, 49.5)))

    assert json.loads(json.dumps(place, ensure_ascii=False)) == place
