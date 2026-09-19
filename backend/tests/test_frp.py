import numpy as np
import pytest

from firewatch.pipeline.frp import SIGMA, VIIRS_A, _radiance_mir, frp_mw

PIXEL_M2 = 375.0 * 375.0


def scene(fire_bt: float, background_bt: float, size: int = 31) -> tuple[np.ndarray, np.ndarray]:
    bt = np.full((size, size), background_bt, dtype=np.float32)
    anomaly = np.zeros((size, size), dtype=bool)
    centre = size // 2
    bt[centre, centre] = fire_bt
    anomaly[centre, centre] = True
    return bt, anomaly


def valid_like(bt: np.ndarray) -> np.ndarray:
    return np.ones(bt.shape, dtype=bool)


def expected_mw(fire_bt: float, background_bt: float, pixel_m2: float = PIXEL_M2) -> float:
    return pixel_m2 * SIGMA / VIIRS_A * (_radiance_mir(fire_bt) - _radiance_mir(background_bt)) / 1e6


def test_frp_matches_mir_radiance_formula() -> None:
    bt, anomaly = scene(fire_bt=340.0, background_bt=290.0)

    values = frp_mw(bt, anomaly, valid_like(bt), np.array([15]), np.array([15]), PIXEL_M2)

    assert values[0] == pytest.approx(expected_mw(340.0, 290.0), abs=1e-3)


def test_frp_of_a_typical_viirs_pixel_is_units_of_megawatts() -> None:
    bt, anomaly = scene(fire_bt=340.0, background_bt=290.0)

    value = frp_mw(bt, anomaly, valid_like(bt), np.array([15]), np.array([15]), PIXEL_M2)[0]

    assert 1.0 < value < 50.0


def test_hotter_pixel_radiates_more() -> None:
    cool, cool_anomaly = scene(fire_bt=320.0, background_bt=290.0)
    hot, hot_anomaly = scene(fire_bt=360.0, background_bt=290.0)
    row, col = np.array([15]), np.array([15])

    cool_mw = frp_mw(cool, cool_anomaly, valid_like(cool), row, col, PIXEL_M2)[0]
    hot_mw = frp_mw(hot, hot_anomaly, valid_like(hot), row, col, PIXEL_M2)[0]

    assert hot_mw > cool_mw


def test_pixel_no_warmer_than_background_radiates_nothing() -> None:
    bt, anomaly = scene(fire_bt=289.0, background_bt=290.0)

    assert frp_mw(bt, anomaly, valid_like(bt), np.array([15]), np.array([15]), PIXEL_M2) == [0.0]


def test_neighbouring_fire_pixels_are_kept_out_of_the_background() -> None:
    """Иначе крупный пожар занижает сам себя: его же пикселы поднимают фон."""
    bt, anomaly = scene(fire_bt=340.0, background_bt=290.0)
    bt[8:23, 8:23] = 340.0
    anomaly[8:23, 8:23] = True
    row, col = np.array([15]), np.array([15])

    honest = frp_mw(bt, anomaly, valid_like(bt), row, col, PIXEL_M2)[0]
    polluted = frp_mw(bt, np.zeros_like(anomaly), valid_like(bt), row, col, PIXEL_M2)[0]

    assert honest == pytest.approx(expected_mw(340.0, 290.0), abs=1e-3)
    assert polluted == 0.0


def test_background_window_grows_until_it_finds_clear_pixels() -> None:
    bt, anomaly = scene(fire_bt=340.0, background_bt=290.0, size=61)
    anomaly[:51, :51] = True

    value = frp_mw(bt, anomaly, valid_like(bt), np.array([30]), np.array([30]), PIXEL_M2)[0]

    assert value == pytest.approx(expected_mw(340.0, 290.0), abs=1e-3)


def test_pixel_without_usable_background_has_no_frp() -> None:
    bt, anomaly = scene(fire_bt=340.0, background_bt=290.0)

    values = frp_mw(bt, anomaly, np.zeros(bt.shape, dtype=bool), np.array([15]), np.array([15]), PIXEL_M2)

    assert values == [None]


def test_frp_scales_with_pixel_area() -> None:
    bt, anomaly = scene(fire_bt=340.0, background_bt=290.0)
    row, col = np.array([15]), np.array([15])

    small = frp_mw(bt, anomaly, valid_like(bt), row, col, PIXEL_M2)[0]
    large = frp_mw(bt, anomaly, valid_like(bt), row, col, PIXEL_M2 * 4)[0]

    assert large == pytest.approx(small * 4, rel=1e-3)
