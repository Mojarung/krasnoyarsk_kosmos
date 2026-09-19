from datetime import date

from firewatch.services.events import associate, in_query
from firewatch.services.query import SpatioTemporalQuery


def hot(id=1, day="2020-04-04", lon=44.0, lat=48.0, scene="AF1"):
    return {
        "id": id,
        "scene_id": scene,
        "acquired_at": day + "T09:00:00+00:00",
        "lon": lon,
        "lat": lat,
        "satellite": "SNPP",
        "confidence": 0.9,
    }


def scar(id="BS1", event="FE1"):
    return {
        "id": id,
        "fire_event_id": event,
        "date_pre": "2020-04-01",
        "date_post": "2020-04-09",
        "area_ha": 100.0,
    }


def match(id=1, scene="BS1"):
    return {"hotspot_id": id, "scene_id": scene, "distance_m": 25.0}


def test_neighbors_across_days_are_one_event_but_years_and_distant_fires_are_not():
    hs = [hot(), hot(2, "2020-04-05", lon=44.005), hot(3, "2021-04-04"), hot(4, lon=46)]
    result = associate(hs, [], [])["events"]
    assert len(result) == 3
    assert sorted(e["hotspot_count"] for e in result) == [1, 1, 2]
    assert max(e["observed_days"] for e in result) == 2


def test_temporal_gap_prevents_spatial_chain():
    assert len(associate([hot(), hot(2, "2020-04-07")], [], [])["events"]) == 2


def test_link_joins_sensors_and_preserves_evidence():
    event = associate([hot(), hot(2, "2020-04-05")], [scar()], [match()])["events"][0]
    assert event["id"] == "bs-FE1"
    assert event["status"] == "linked"
    assert event["hotspot_count"] == 2
    assert event["evidence"] == [{"hotspot_id": 1, "distance_m": 25.0}]


def test_multiple_candidates_do_not_force_a_link():
    result = associate([hot()], [scar(), scar("BS2", "FE2")], [match(), match(scene="BS2")])["events"]
    assert len(result) == 3
    af = next(e for e in result if e["hotspot_count"])
    assert af["status"] == "ambiguous"
    assert af["candidate_ids"] == ["bs-FE1", "bs-FE2"]
    assert not af["scene_ids"]


def test_same_catalogue_event_is_not_an_ambiguous_candidate():
    event = associate([hot()], [scar(), scar("BS2")], [match(), match(scene="BS2")])["events"][0]
    assert event["status"] == "linked"
    assert len(event["scene_ids"]) == 2


def test_no_match_is_explicit_not_zero_area():
    result = associate([hot()], [scar()], [])["events"]
    assert {e["status"] for e in result} == {"hotspot_only", "burn_only"}


def test_event_identity_does_not_depend_on_database_id_or_input_order():
    a = associate([hot(), hot(2, "2020-04-05")], [], [])["events"][0]
    b = associate([hot(99, "2020-04-05"), hot(98)], [], [])["events"][0]
    assert a["id"] == b["id"]


def test_query_requires_same_observation_to_match_both_space_and_time():
    event = associate([hot(), hot(2, "2020-04-05", lon=44.005)], [], [])["events"][0]
    query = SpatioTemporalQuery.build(
        geometry=None,
        bbox=(43.999, 47.999, 44.001, 48.001),
        date_from=date(2020, 4, 5),
        date_to=date(2020, 4, 5),
    )
    assert not in_query(event, query, set())


def test_empty_index():
    assert associate([], [], [])["events"] == []
