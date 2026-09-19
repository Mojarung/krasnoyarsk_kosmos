from __future__ import annotations

import os
from importlib import import_module

from fire_ml.contract import ActiveFireModel, BurnSeverityModel

DEFAULT_AF = "fire_ml.af_gbm:GbmActiveFire"
DEFAULT_BS = "fire_ml.bs_ensemble:BurnSeverityEnsemble"


def _load(entrypoint: str) -> object:
    module_name, _, attr = entrypoint.partition(":")
    if not attr:
        raise ValueError(f"Ожидается 'package.module:ClassName', получено: {entrypoint!r}")
    return getattr(import_module(module_name), attr)()


def load_af_model() -> ActiveFireModel:
    model = _load(os.environ.get("FIRE_ML_AF", DEFAULT_AF))
    if not isinstance(model, ActiveFireModel):
        raise TypeError(f"{type(model).__name__} не реализует ActiveFireModel")
    return model


def load_bs_model() -> BurnSeverityModel:
    model = _load(os.environ.get("FIRE_ML_BS", DEFAULT_BS))
    if not isinstance(model, BurnSeverityModel):
        raise TypeError(f"{type(model).__name__} не реализует BurnSeverityModel")
    return model
