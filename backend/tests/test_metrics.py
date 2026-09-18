import pytest

from firewatch.services.metrics import score_from_scenes


def confusion(tp: int, fp: int, fn: int) -> dict[str, int]:
    return {"tp": tp, "fp": fp, "fn": fn}


def af(tp: int, fp: int, fn: int) -> dict:
    return {"kind": "af", "quality": {"fire": confusion(tp, fp, fn)}}


def bs(burn: dict, severity: list[dict]) -> dict:
    return {"kind": "bs", "quality": {"burn": burn, "severity": severity}}


def test_score_is_micro_averaged_over_scenes() -> None:
    rows = [
        af(8, 2, 0),
        af(0, 0, 2),
        bs(confusion(50, 25, 25), [confusion(10, 5, 5), confusion(20, 10, 10), confusion(0, 0, 10)]),
    ]

    result = score_from_scenes(rows)

    assert result is not None
    assert result["f1_af"] == pytest.approx(2 * 8 / (2 * 8 + 2 + 2))
    assert result["iou_burn"] == pytest.approx(0.5)
    assert result["iou_severity"] == [0.5, 0.5, 0.0]
    assert result["score"] == pytest.approx(0.35 * 0.8 + 0.35 * 0.5 + 0.30 * (1.0 / 3), abs=1e-4)


def test_class_absent_everywhere_counts_as_one() -> None:
    rows = [af(0, 0, 0), bs(confusion(0, 0, 0), [confusion(0, 0, 0)] * 3)]

    result = score_from_scenes(rows)

    assert result is not None
    assert (result["f1_af"], result["iou_burn"], result["miou_sev"], result["score"]) == (1.0, 1.0, 1.0, 1.0)


def test_score_needs_both_modules() -> None:
    result = score_from_scenes([af(5, 1, 1)])

    assert result is not None
    assert result["score"] is None
    assert result["iou_burn"] is None


def test_no_reference_scenes_gives_none() -> None:
    assert score_from_scenes([]) is None
