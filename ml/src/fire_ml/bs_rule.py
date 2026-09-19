"""Правило эталонной разметки гарей, восстановленное по постановке и обучающей выборке.

Постановка кейса (рис. 6) задаёт пороги dNBR по типу покрова. На train они воспроизводят степень внутри
эталонного контура на 92,3%, а после медианного фильтра 3×3 по dNBR на 97,1%: эталон считался по
сглаженному индексу. Сам контур правилом не восстановить: эталон обрезан буфером вокруг события пожара,
поэтому правило идёт в модель как признак, а положение буфера предсказывает сеть.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

# ESA WorldCover: 10 лес, 20 кустарник, 30 травы, 40 пашня, 90 болото и пойма. Границы классов 1, 2, 3.
THRESHOLDS: dict[int, tuple[float, float, float]] = {
    10: (0.100, 0.270, 0.660),
    20: (0.100, 0.270, 0.660),
    30: (0.062, 0.204, 0.386),
    40: (0.070, 0.177, 0.380),
    90: (0.075, 0.331, 0.677),
}
MEDIAN_WINDOW = 3
# Застройка, голый грунт, вода: гари в эталоне там нет, порог недостижим.
NO_BURN_THRESHOLD = 9.0
# Нет данных, дефект, тень облака, вода, плотное облако, снег. Облако средней вероятности (8) и перистые (10)
# эталон не исключает: доля гари среди кандидатов там 0,83-0,96, как на чистых пикселях.
SCL_EXCLUDED = (0, 1, 3, 6, 9, 11)
# Выше этого NBR «после» гари в эталоне почти нет: доля падает с 0,83 до 0,27 ровно на 0,22.
NBR_POST_MAX = 0.22


def smooth_dnbr(dnbr: np.ndarray) -> np.ndarray:
    return ndimage.median_filter(dnbr, MEDIAN_WINDOW, mode="nearest")


def lower_threshold(landcover: np.ndarray) -> np.ndarray:
    low = np.full(landcover.shape, NO_BURN_THRESHOLD, dtype=np.float32)
    for cls, (first, _, _) in THRESHOLDS.items():
        low[landcover == cls] = first
    return low


def rule_classes(dnbr: np.ndarray, landcover: np.ndarray) -> np.ndarray:
    """Степень 0-3 по порогам покрова. dnbr подаётся уже сглаженным, если нужен эталонный вариант."""
    severity = np.zeros(dnbr.shape, dtype=np.uint8)
    for cls, bounds in THRESHOLDS.items():
        where = landcover == cls
        values = dnbr[where]
        severity[where] = sum((values >= bound).astype(np.uint8) for bound in bounds)
    return severity


def excluded(scl_pre: np.ndarray, scl_post: np.ndarray, nbr_post: np.ndarray) -> np.ndarray:
    """Где эталон гари не ставит при любом dNBR: доля гари среди кандидатов внутри буфера падает до 0-15%."""
    bad_scl = np.isin(scl_pre, SCL_EXCLUDED) | np.isin(scl_post, SCL_EXCLUDED)
    return bad_scl | (nbr_post > NBR_POST_MAX)


def label_rule(
    nbr_pre: np.ndarray,
    nbr_post: np.ndarray,
    landcover: np.ndarray,
    scl_pre: np.ndarray,
    scl_post: np.ndarray,
) -> np.ndarray:
    """Эталонная степень в предположении, что пиксель лежит внутри буфера события."""
    severity = rule_classes(smooth_dnbr(nbr_pre - nbr_post), landcover)
    severity[excluded(scl_pre, scl_post, nbr_post)] = 0
    return severity
