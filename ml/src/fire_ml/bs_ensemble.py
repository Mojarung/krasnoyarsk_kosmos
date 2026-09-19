"""Боевая модель гарей: попиксельный LightGBM, сегментационные сети и бустинг второго уровня поверх них.

Сети подключаются, если установлены torch и segmentation-models-pytorch и лежат веса. Без них модель
работает на одном бустинге: сервису в Docker torch не нужен, а сабмит собирается с полной связкой.
"""

from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
from scipy import ndimage

from fire_ml.bs_features import compute_features
from fire_ml.bs_tensor import N_CHANNELS, chip_tensor
from fire_ml.contract import BsChip, BsPrediction

WEIGHTS = Path(__file__).parent / "weights"
TTA = (0, 1, 4, 5)
# В эталоне нет гари при dNBR ниже 0,06: покрытие 99,97%, а бустинг смотрит только треть пикселей.
CANDIDATE_DNBR = 0.06
GBM_THREADS = 2


class BurnSeverityEnsemble:
    name = "lgbm-pixel-v1"

    def __init__(self, use_cnn: bool = True) -> None:
        config = json.loads((WEIGHTS / "bs_blend.json").read_text(encoding="utf-8"))
        self._features: list[str] = json.loads((WEIGHTS / "bs_lgbm.json").read_text(encoding="utf-8"))[
            "features"
        ]
        self._booster = lgb.Booster(model_file=str(WEIGHTS / "bs_lgbm.txt"))
        self._nets = self._load_nets(config["cnn"]) if use_cnn else []
        self._stack = None
        self._class_weights = np.asarray(config["gbm_only"]["class_weights"], dtype=np.float32)
        if self._nets:
            self._stack_config = json.loads((WEIGHTS / "bs_stack.json").read_text(encoding="utf-8"))
            self._stack = lgb.Booster(model_file=str(WEIGHTS / "bs_stack.txt"))
            self._class_weights = np.asarray(self._stack_config["class_weights"], dtype=np.float32)
            self.name = f"lgbm-{len(self._nets)}net-stack-v1"

    def _load_nets(self, groups: list[dict]) -> list:
        files = [(group, path) for group in groups for path in sorted(WEIGHTS.glob(group["weights_glob"]))]
        if not files:
            return []
        try:
            import segmentation_models_pytorch as smp
            import torch
        except ImportError:
            return []
        self._torch = torch
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        nets = []
        for group, path in files:
            net = smp.create_model(
                group["arch"],
                encoder_name=group["encoder"],
                encoder_weights=None,
                in_channels=N_CHANNELS,
                classes=4,
            )
            net.load_state_dict({k: v.float() for k, v in torch.load(path, map_location="cpu").items()})
            nets.append((group["tag"], net.to(self._device).eval()))
        return nets

    def _cnn_proba(self, chip: BsChip) -> np.ndarray:
        """Среднее по архитектурам от средних по фолдам: так же усреднялись OOF при обучении стекинга."""
        torch = self._torch
        batch = torch.from_numpy(chip_tensor(chip)[None]).to(self._device)
        by_tag: dict[str, list] = {}
        with (
            torch.no_grad(),
            torch.autocast(self._device, dtype=torch.bfloat16, enabled=self._device == "cuda"),
        ):
            for tag, net in self._nets:
                total = torch.zeros((1, 4, *batch.shape[-2:]), device=self._device)
                for k in TTA:
                    view = torch.rot90(batch, k % 4, dims=(-2, -1))
                    view = torch.flip(view, dims=(-1,)) if k >= 4 else view
                    proba = net(view).float().softmax(1)
                    proba = torch.flip(proba, dims=(-1,)) if k >= 4 else proba
                    total += torch.rot90(proba, -(k % 4), dims=(-2, -1))
                by_tag.setdefault(tag, []).append(total[0] / len(TTA))
        per_tag = [torch.stack(items).mean(0) for items in by_tag.values()]
        return torch.stack(per_tag).mean(0).cpu().numpy()

    def predict(self, chip: BsChip) -> BsPrediction:
        features = compute_features(chip)
        candidates = (features["d_nbr"] > CANDIDATE_DNBR) | (features["d_nbr_mean_5"] > CANDIDATE_DNBR)
        severity = np.zeros(candidates.shape, dtype=np.uint8)
        if candidates.any():
            table = np.stack([features[name][candidates] for name in self._features], axis=1)
            proba = self._booster.predict(table, num_threads=GBM_THREADS)
            if self._stack is not None:
                cnn = self._cnn_proba(chip)
                burn = 1.0 - cnn[0]
                context = [
                    ndimage.uniform_filter(burn, window, mode="nearest")
                    for window in self._stack_config["windows"]
                ]
                raw = [features[name] for name in self._stack_config["raw"]]
                layers = np.stack([layer[candidates] for layer in (*cnn, *context, *raw)], axis=1)
                proba = self._stack.predict(np.concatenate([proba, layers], axis=1), num_threads=GBM_THREADS)
            severity[candidates] = (proba * self._class_weights).argmax(1)
        return BsPrediction(severity=severity, dnbr=features["d_nbr"])
