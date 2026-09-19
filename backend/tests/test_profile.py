import pytest

from firewatch.services.profile import _deviation, _fire_season, _recurrence_block, _season_block


def season(hotspots_by_month: dict[int, int]) -> list[dict]:
    return _season_block(
        [{"month": m, "hotspots": n, "years": 1, "area_ha": 0.0} for m, n in hotspots_by_month.items()],
        n_years=1,
    )


def test_deviation_compares_a_year_with_the_others() -> None:
    assert _deviation(150.0, [100.0, 100.0]) == pytest.approx(0.5)
    assert _deviation(50.0, [100.0, 100.0]) == pytest.approx(-0.5)


def test_single_year_has_nothing_to_compare_with() -> None:
    assert _deviation(150.0, []) is None


def test_deviation_from_a_quiet_baseline_is_undefined() -> None:
    assert _deviation(10.0, [0.0, 0.0]) is None


def test_season_block_fills_months_without_observations() -> None:
    months = season({7: 100})

    assert len(months) == 12
    assert [m["hotspots"] for m in months if m["month"] != 7] == [0] * 11
    assert months[6]["label"] == "июль"


def test_fire_season_is_the_shortest_run_holding_most_of_the_fires() -> None:
    result = _fire_season(season({4: 5, 5: 40, 6: 45, 7: 5, 8: 5}))

    assert (result["from"], result["to"], result["months"]) == ("май", "июнь", 2)
    assert result["share"] >= 0.8


def test_fire_season_may_wrap_around_the_new_year() -> None:
    result = _fire_season(season({12: 45, 1: 40, 6: 5, 7: 10}))

    assert (result["from"], result["to"]) == ("декабрь", "январь")


def test_territory_that_never_burned_has_no_season() -> None:
    assert _fire_season(season({})) is None


def test_recurrence_counts_cells_that_burned_in_more_than_one_year() -> None:
    block = _recurrence_block([{"years": 1, "cells": 30}, {"years": 3, "cells": 10}], query_ha=10_000.0)

    assert block["touched_cells"] == 40
    assert block["repeat_cells"] == 10
    assert block["repeat_share"] == pytest.approx(0.25)
    assert block["max_years"] == 3
    assert block["touched_ha"] == pytest.approx(40 * block["cell_area_ha"])


def test_untouched_territory_gives_zeroes_not_an_error() -> None:
    block = _recurrence_block([], query_ha=10_000.0)

    assert (block["touched_cells"], block["repeat_cells"], block["max_years"]) == (0, 0, 0)
    assert block["repeat_share"] is None
