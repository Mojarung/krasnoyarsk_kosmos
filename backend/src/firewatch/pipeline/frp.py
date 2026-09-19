"""Мощность излучения пожара, FRP.

Метод MIR-radiance (Wooster et al., 2003): в окне 4 мкм спектральная яркость почти
линейно связана с полной излучаемой мощностью очага, поэтому мощность пиксела считается
по разнице яркости пиксела и окружающего фона:

    FRP = A * sigma / a * (L_f - L_bg)

A - площадь пиксела, sigma - постоянная Стефана-Больцмана, a - коэффициент аппроксимации
L_MIR = a * T^4, свой у каждого сенсора. Тем же методом считаются оперативные продукты
MODIS Collection 6, VIIRS, Meteosat, GOES и Himawari, отличается только a: 3,0e-9 у MODIS,
2,88e-9 у VIIRS (Li et al., 2018, doi:10.1029/2017JD027823).

Яркость восстанавливается из яркостной температуры канала I4 по формуле Планка - это
обратное преобразование к тому, которым яркостная температура получена, потерь нет.
"""

from __future__ import annotations

import numpy as np

SIGMA = 5.670374419e-8
"""Постоянная Стефана-Больцмана, Вт·м⁻²·К⁻⁴."""

VIIRS_A = 2.88e-9
"""Коэффициент сенсора в L_MIR = a·T⁴, Вт·м⁻²·ср⁻¹·мкм⁻¹·К⁻⁴."""

I4_WAVELENGTH_M = 3.74e-6
"""Центральная длина волны канала VIIRS I4."""

I4_SATURATION_K = 367.0
"""Выше этой яркостной температуры канал I4 насыщается, FRP становится оценкой снизу."""

BACKGROUND_WINDOW = 21
BACKGROUND_MIN_SAMPLES = 8
BACKGROUND_MAX_GROWTH = 3

_PLANCK_C1 = 1.1910429723971884e-16
"""2·h·c², Вт·м²·ср⁻¹."""

_PLANCK_C2 = 0.014387768775039337
"""h·c/k, м·К."""


def _radiance_mir(bt_k: np.ndarray | float) -> np.ndarray | float:
    """Спектральная яркость на 3,74 мкм по яркостной температуре, Вт·м⁻²·ср⁻¹·мкм⁻¹."""
    lam = I4_WAVELENGTH_M
    return (_PLANCK_C1 / lam**5) / np.expm1(_PLANCK_C2 / (lam * bt_k)) / 1e6


def _background_bt(bt: np.ndarray, usable: np.ndarray, row: int, col: int) -> float | None:
    """Медиана яркостной температуры фона вокруг пиксела.

    Окно расширяется, пока в нём не наберётся достаточно пикселов без термоаномалий:
    у крупного пожара соседи тоже горят, и в исходном окне фона может не оказаться.
    """
    half = BACKGROUND_WINDOW // 2
    height, width = bt.shape
    for _ in range(BACKGROUND_MAX_GROWTH):
        r0, r1 = max(row - half, 0), min(row + half + 1, height)
        c0, c1 = max(col - half, 0), min(col + half + 1, width)
        window = bt[r0:r1, c0:c1][usable[r0:r1, c0:c1]]
        if window.size >= BACKGROUND_MIN_SAMPLES:
            return float(np.median(window))
        half *= 2
    return float(np.median(window)) if window.size else None


def frp_mw(
    bt_i4: np.ndarray,
    anomaly: np.ndarray,
    valid: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray,
    pixel_area_m2: float,
) -> list[float | None]:
    """Мощность каждой термоаномалии в мегаваттах.

    anomaly - пикселы, отнесённые моделью к любой термоаномалии: они исключаются из фона,
    иначе очаг занижает сам себя. None возвращается, когда фон собрать не из чего.
    """
    usable = valid & ~anomaly & np.isfinite(bt_i4)
    scale = pixel_area_m2 * SIGMA / VIIRS_A / 1e6
    values: list[float | None] = []
    for row, col in zip(rows.tolist(), cols.tolist(), strict=True):
        fire_bt = float(bt_i4[row, col])
        background = _background_bt(bt_i4, usable, row, col)
        if background is None or not np.isfinite(fire_bt):
            values.append(None)
        elif fire_bt <= background:
            values.append(0.0)
        else:
            delta = _radiance_mir(fire_bt) - _radiance_mir(background)
            values.append(round(scale * float(delta), 3))
    return values
