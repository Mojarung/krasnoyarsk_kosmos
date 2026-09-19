"""Боевая модель гарей: попиксельный LightGBM, сегментационные сети и бустинг второго уровня поверх них.

Сети подключаются, если установлены torch и segmentation-models-pytorch и лежат веса. Без них модель
работает на одном бустинге: сервису в Docker torch не нужен, а сабмит собирается с полной связкой.

Сети грузятся лениво, при первом обращении к cnn_proba. inference.py пользуется этим: видеокарту держит один
процесс, он считает сети пачками, а процессы пула получают готовые вероятности и torch не импортируют.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from importlib.util import find_spec
from pathlib import Path

import lightgbm as lgb
import numpy as np
from scipy import ndimage

from fire_ml.bs_features import compute_features
from fire_ml.bs_tensor import chip_tensor, rule_tensor
from fire_ml.contract import BsChip, BsPrediction

WEIGHTS = Path(__file__).parent / "weights"
# Отражения D4 на инференсе: один проход без отражений. На OOF одной сети четыре отражения давали +0,003 к
# вкладу гарей в Score, но на public-выборке с усреднением десяти сетей вышло наоборот: одно отражение 0,8725,
# два и четыре 0,8704. Десять сетей уже сглаживают вероятности сильнее, чем видел второй уровень на обучении,
# и отражения сглаживают их дальше. Заодно сети считаются вчетверо быстрее. FIRE_ML_BS_TTA="0,4" задаёт набор явно.
TTA = (0,)
# Имена голов сети в порядке выходных каналов после четырёх классов. Пока одна: буфер события.
HEAD_NAMES = ("region",)
# В эталоне нет гари при dNBR ниже 0,06: покрытие 99,97%, а бустинг смотрит только треть пикселей.
CANDIDATE_DNBR = 0.06
GBM_THREADS = 2
N_CLASSES = 4


def cnn_layers(proba: np.ndarray, windows: Sequence[int]) -> list[np.ndarray]:
    """Признаки второго уровня от одной сети. Каналы после четвёртого — головы буфера события (HEAD_NAMES)."""
    layers = [*proba[:N_CLASSES]]
    layers += [ndimage.uniform_filter(1.0 - proba[0], window, mode="nearest") for window in windows]
    for head in proba[N_CLASSES:]:
        layers += [head]
        layers += [ndimage.uniform_filter(head, window, mode="nearest") for window in windows]
    return layers


def rule_layers(rule: np.ndarray) -> list[np.ndarray]:
    """Степень по правилу разметки и запас dNBR над нижним порогом: каналы 0-4 из bs_tensor.rule_tensor."""
    return [rule[:N_CLASSES].argmax(0).astype(np.float32), rule[N_CLASSES]]


class BurnSeverityEnsemble:
    name = "lgbm-pixel-v1"

    def __init__(self, use_cnn: bool = True) -> None:
        config = json.loads((WEIGHTS / "bs_blend.json").read_text(encoding="utf-8"))
        self._features: list[str] = json.loads((WEIGHTS / "bs_lgbm.json").read_text(encoding="utf-8"))[
            "features"
        ]
        self._booster = lgb.Booster(model_file=str(WEIGHTS / "bs_lgbm.txt"))
        self._net_files = self._find_nets(config["cnn"]) if use_cnn else []
        self._nets: list | None = None
        self._stack = None
        self._class_weights = np.asarray(config["gbm_only"]["class_weights"], dtype=np.float32)
        if self._net_files:
            self._stack_config = json.loads((WEIGHTS / "bs_stack.json").read_text(encoding="utf-8"))
            self._stack = lgb.Booster(model_file=str(WEIGHTS / "bs_stack.txt"))
            self._class_weights = np.asarray(self._stack_config["class_weights"], dtype=np.float32)
            self.name = f"lgbm-{len(self._net_files)}net-stack-v1"

    @property
    def has_nets(self) -> bool:
        return bool(self._net_files)

    @staticmethod
    def _find_nets(groups: list[dict]) -> list[tuple[dict, Path]]:
        files = [(group, path) for group in groups for path in sorted(WEIGHTS.glob(group["weights_glob"]))]
        if not files or find_spec("torch") is None or find_spec("segmentation_models_pytorch") is None:
            return []
        return files

    def _load_nets(self) -> list:
        import segmentation_models_pytorch as smp
        import torch

        self._torch = torch
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        override = os.environ.get("FIRE_ML_BS_TTA")
        self._tta = tuple(int(k) for k in override.split(",")) if override else TTA
        nets = []
        for group, path in self._net_files:
            state = {k: v.float() for k, v in torch.load(path, map_location="cpu").items()}
            # Число входных каналов и выходов читается из весов: каналы правила дописываются в конец тензора,
            # поэтому сеть, обученная на более раннем наборе, берёт его начало.
            in_channels = next(v.shape[1] for v in state.values() if v.ndim == 4)
            classes = state["segmentation_head.0.weight"].shape[0]
            net = smp.create_model(
                group["arch"],
                encoder_name=group["encoder"],
                encoder_weights=None,
                in_channels=in_channels,
                classes=classes,
            )
            net.load_state_dict(state)
            net = net.to(self._device).eval()
            if self._device == "cuda":
                net = net.to(memory_format=torch.channels_last)
            nets.append((group["tag"], in_channels, net))
        return nets

    def tensors(self, chip: BsChip) -> np.ndarray:
        """Вход сетей: базовые каналы и каналы правила. Каждая сеть берёт столько первых каналов, на скольких
        обучена."""
        return np.concatenate([chip_tensor(chip), rule_tensor(chip)])

    def cnn_proba(self, tensors: np.ndarray) -> list[dict[str, np.ndarray]]:
        """Вероятности сетей для пачки чипов [B, C, H, W]. По каждой архитектуре среднее по её фолдам:
        второй уровень получает сети отдельными признаками."""
        if self._nets is None:
            self._nets = self._load_nets()
        torch = self._torch
        full = torch.from_numpy(np.ascontiguousarray(tensors)).to(self._device)
        by_tag: dict[str, list] = {}
        with (
            torch.no_grad(),
            torch.autocast(self._device, dtype=torch.bfloat16, enabled=self._device == "cuda"),
        ):
            for tag, in_channels, net in self._nets:
                batch = full[:, :in_channels]
                total = None
                for k in self._tta:
                    view = torch.rot90(batch, k % 4, dims=(-2, -1))
                    view = torch.flip(view, dims=(-1,)) if k >= 4 else view
                    logits = net(view.contiguous()).float()
                    # Выходы после четвёртого: независимые головы (буфер события), у них сигмоида.
                    proba = torch.cat(
                        [logits[:, :N_CLASSES].softmax(1), logits[:, N_CLASSES:].sigmoid()], dim=1
                    )
                    proba = torch.flip(proba, dims=(-1,)) if k >= 4 else proba
                    proba = torch.rot90(proba, -(k % 4), dims=(-2, -1))
                    total = proba if total is None else total + proba
                by_tag.setdefault(tag, []).append(total / len(self._tta))
        mean = {tag: torch.stack(items).mean(0).half().cpu().numpy() for tag, items in by_tag.items()}
        return [{tag: volume[index] for tag, volume in mean.items()} for index in range(len(tensors))]

    def predict(self, chip: BsChip, nets: dict[str, np.ndarray] | None = None) -> BsPrediction:
        """nets: готовые вероятности сетей от cnn_proba. Если не переданы, модель считает их сама."""
        features = compute_features(chip)
        candidates = (features["d_nbr"] > CANDIDATE_DNBR) | (features["d_nbr_mean_5"] > CANDIDATE_DNBR)
        severity = np.zeros(candidates.shape, dtype=np.uint8)
        if candidates.any():
            table = np.stack([features[name][candidates] for name in self._features], axis=1)
            proba = self._booster.predict(table, num_threads=GBM_THREADS)
            if self._stack is not None:
                if nets is None:
                    nets = self.cnn_proba(self.tensors(chip)[None])[0]
                layers = []
                for tag in self._stack_config["cnn_tags"]:
                    layers += cnn_layers(nets[tag].astype(np.float32), self._stack_config["windows"])
                rows, cols = np.mgrid[0 : candidates.shape[0], 0 : candidates.shape[1]].astype(np.float32)
                rows, cols = rows / (candidates.shape[0] - 1) - 0.5, cols / (candidates.shape[1] - 1) - 0.5
                layers += [np.hypot(rows, cols), np.abs(rows), np.abs(cols)]
                if self._stack_config.get("rule", False):
                    layers += rule_layers(rule_tensor(chip))
                layers += [features[name] for name in self._stack_config["raw"]]
                layers = np.stack([layer[candidates] for layer in layers], axis=1)
                proba = self._stack.predict(np.concatenate([proba, layers], axis=1), num_threads=GBM_THREADS)
            severity[candidates] = (proba * self._class_weights).argmax(1)
        return BsPrediction(severity=severity, dnbr=features["d_nbr"])
