"""Контракт между ML-модулями и сервисом.

Сервис и inference.py работают только с этими типами. Чтобы подключить свою модель,
реализуйте ActiveFireModel / BurnSeverityModel и укажите класс в переменных окружения
FIRE_ML_AF / FIRE_ML_BS в формате "package.module:ClassName".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol, runtime_checkable

import numpy as np

AF_VIIRS_BANDS = ("I1", "I2", "I3", "I4", "I5", "solar_zenith", "sensor_zenith", "valid")
AF_AUX_BANDS = ("landcover", "dem", "t2m", "rh2m", "wind_speed")
BS_S2_BANDS = ("B2", "B3", "B4", "B5", "B6", "B7", "B8A", "B11", "B12", "SCL")
BS_S1_BANDS = ("VV", "VH")
BS_AUX_BANDS = ("dem", "slope", "landcover")


class AfCode(IntEnum):
    NONE = 0
    FIRE = 1
    TECHNOGENIC = 2
    GLINT = 3


@dataclass(frozen=True)
class AfChip:
    chip_id: str
    viirs: np.ndarray
    aux: np.ndarray


@dataclass(frozen=True)
class BsChip:
    chip_id: str
    s2_pre: np.ndarray
    s2_post: np.ndarray
    s1_pre: np.ndarray
    s1_post: np.ndarray
    aux: np.ndarray


@dataclass(frozen=True)
class AfPrediction:
    """fire_mask - ответ по ТЗ (1 = природное горение).

    codes необязателен: попиксельные коды AfCode для всех термоаномалий, включая отсеянные.
    Сервис показывает по ним, что именно и почему отфильтровано.
    """

    fire_mask: np.ndarray
    codes: np.ndarray | None = None
    confidence: np.ndarray | None = None

    def resolved_codes(self) -> np.ndarray:
        if self.codes is not None:
            return self.codes.astype(np.uint8)
        return (self.fire_mask > 0).astype(np.uint8) * AfCode.FIRE


@dataclass(frozen=True)
class BsPrediction:
    """severity: 0 - нет гари, 1..3 - слабая, средняя, сильная степень."""

    severity: np.ndarray
    dnbr: np.ndarray | None = None


@runtime_checkable
class ActiveFireModel(Protocol):
    name: str

    def predict(self, chip: AfChip) -> AfPrediction: ...


@runtime_checkable
class BurnSeverityModel(Protocol):
    name: str

    def predict(self, chip: BsChip) -> BsPrediction: ...
