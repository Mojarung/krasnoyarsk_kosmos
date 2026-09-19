"""Боевая модель гарей: попиксельный LightGBM и U-Net, смешанные по вероятностям.

U-Net подключается, если установлены torch и segmentation-models-pytorch и лежат веса. Без них модель
работает на одном бустинге: сервису в Docker torch не нужен, а сабмит собирается с полной связкой.
"""

from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np

from fire_ml.bs_features import compute_features
from fire_ml.bs_tensor import N_CHANNELS, chip_tensor
from fire_ml.contract import BsChip, BsPrediction

WEIGHTS = Path(__file__).parent / "weights"
TTA = (0, 1, 4, 5)


class BurnSeverityEnsemble:
    name = "lgbm-unet-blend-v1"

    def __init__(self, use_cnn: bool = True) -> None:
        config = json.loads((WEIGHTS / "bs_blend.json").read_text(encoding="utf-8"))
        self._features: list[str] = json.loads((WEIGHTS / "bs_lgbm.json").read_text(encoding="utf-8"))[
            "features"
        ]
        self._booster = lgb.Booster(model_file=str(WEIGHTS / "bs_lgbm.txt"))
        self._nets = self._load_nets(config) if use_cnn else []
        blend = config["with_cnn"] if self._nets else config["gbm_only"]
        self._cnn_share: float = blend["cnn_share"]
        self._class_weights = np.asarray(blend["class_weights"], dtype=np.float32).reshape(4, 1, 1)
        if self._nets:
            self.name = f"{self.name}+{len(self._nets)}net"

    def _load_nets(self, config: dict) -> list:
        files = sorted(WEIGHTS.glob(config["cnn"]["weights_glob"]))
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
        for path in files:
            net = smp.create_model(
                config["cnn"]["arch"],
                encoder_name=config["cnn"]["encoder"],
                encoder_weights=None,
                in_channels=N_CHANNELS,
                classes=4,
            )
            net.load_state_dict({k: v.float() for k, v in torch.load(path, map_location="cpu").items()})
            nets.append(net.to(self._device).eval())
        return nets

    def _gbm_proba(self, chip: BsChip) -> np.ndarray:
        features = compute_features(chip)
        height, width = features["d_nbr"].shape
        table = np.stack([features[name].ravel() for name in self._features], axis=1)
        return self._booster.predict(table, num_threads=1).T.reshape(4, height, width).astype(np.float32)

    def _cnn_proba(self, chip: BsChip) -> np.ndarray:
        torch = self._torch
        batch = torch.from_numpy(chip_tensor(chip)[None]).to(self._device)
        total = torch.zeros((1, 4, *batch.shape[-2:]), device=self._device)
        with (
            torch.no_grad(),
            torch.autocast(self._device, dtype=torch.bfloat16, enabled=self._device == "cuda"),
        ):
            for net in self._nets:
                for k in TTA:
                    view = torch.rot90(batch, k % 4, dims=(-2, -1))
                    view = torch.flip(view, dims=(-1,)) if k >= 4 else view
                    proba = net(view).float().softmax(1)
                    proba = torch.flip(proba, dims=(-1,)) if k >= 4 else proba
                    total += torch.rot90(proba, -(k % 4), dims=(-2, -1))
        return (total[0] / (len(self._nets) * len(TTA))).cpu().numpy()

    def predict(self, chip: BsChip) -> BsPrediction:
        proba = self._gbm_proba(chip)
        if self._nets:
            proba = self._cnn_share * self._cnn_proba(chip) + (1.0 - self._cnn_share) * proba
        severity = (proba * self._class_weights).argmax(0).astype(np.uint8)
        features_dnbr = (chip.s2_pre[6].astype(np.float32) - chip.s2_pre[8]) / np.maximum(
            chip.s2_pre[6].astype(np.float32) + chip.s2_pre[8], 1.0
        ) - (chip.s2_post[6].astype(np.float32) - chip.s2_post[8]) / np.maximum(
            chip.s2_post[6].astype(np.float32) + chip.s2_post[8], 1.0
        )
        return BsPrediction(severity=severity, dnbr=features_dnbr.astype(np.float32))
