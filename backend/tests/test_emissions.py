import pytest

from firewatch.services.emissions import build_estimate, load_factors


def test_burned_biomass_is_area_by_load_by_completeness() -> None:
    spec = load_factors()
    load = spec["fuel"]["forest"]["load_t_ha"]
    completeness = spec["combustion_completeness"]["3"]

    estimate = build_estimate({(3, "forest"): 100.0})

    assert estimate["dry_matter_t"] == pytest.approx(100.0 * load * completeness, rel=1e-6)


def test_emission_follows_the_factor_of_its_land_cover() -> None:
    spec = load_factors()
    factor = spec["factors"]["forest"]["co2"]
    estimate = build_estimate({(3, "forest"): 100.0})

    co2 = next(s["tonnes"] for s in estimate["species"] if s["key"] == "co2")

    assert co2 == pytest.approx(estimate["dry_matter_t"] * factor / 1000.0, rel=1e-3)


def test_severe_burn_releases_more_than_light_one_on_equal_area() -> None:
    light = build_estimate({(1, "forest"): 100.0})
    severe = build_estimate({(3, "forest"): 100.0})

    assert severe["dry_matter_t"] > light["dry_matter_t"]


def test_forest_releases_more_than_steppe_on_equal_area() -> None:
    forest = build_estimate({(2, "forest"): 100.0})
    steppe = build_estimate({(2, "grass"): 100.0})

    assert forest["dry_matter_t"] > steppe["dry_matter_t"]


def test_co2_equivalent_counts_methane_by_its_warming_potential() -> None:
    spec = load_factors()
    gwp = {s["key"]: s["gwp100"] for s in spec["species"]}
    estimate = build_estimate({(2, "forest"): 250.0})

    by_key = {s["key"]: s["tonnes"] for s in estimate["species"]}

    assert estimate["co2e_t"] == pytest.approx(sum(by_key[key] * gwp[key] for key in by_key), rel=1e-3)
    assert estimate["co2e_t"] > by_key["co2"]


def test_unknown_land_cover_falls_back_to_the_default_fuel() -> None:
    estimate = build_estimate({(2, "other"): 10.0})

    assert estimate["dry_matter_t"] > 0
    assert [row["landcover"] for row in estimate["by_landcover"]] == ["other"]


def test_empty_query_gives_zeroes_not_an_error() -> None:
    estimate = build_estimate({})

    assert estimate["dry_matter_t"] == 0.0
    assert estimate["co2e_t"] == 0.0
    assert all(s["tonnes"] == 0.0 for s in estimate["species"])
    assert estimate["by_landcover"] == []


def test_shares_by_land_cover_sum_to_one() -> None:
    estimate = build_estimate({(2, "forest"): 40.0, (3, "grass"): 60.0, (1, "crop"): 25.0})

    assert sum(row["share"] for row in estimate["by_landcover"]) == pytest.approx(1.0, abs=1e-3)
