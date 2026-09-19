"""U-Net для гарей: GroupKFold по событиям, CE + Dice, аугментации D4, OOF-вероятности с TTA.

Запуск: python research/bs/train_cnn.py <tag> <arch> <encoder> <epochs> [folds]
"""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import segmentation_models_pytorch as smp
import torch
from sklearn.model_selection import GroupKFold
from torch import nn

from fire_ml.bs_tensor import N_CHANNELS, chip_tensor
from fire_ml.io import chip_paths, load_bs_chip

BS = Path("DATA/fire-train-renamed/train/bs")
OUT = Path("research/bs/results")
WEIGHTS = Path("research/bs/weights")
CACHE = OUT / "cnn_cache.npz"
N_FOLDS = 5
BATCH = 8
LR = float(os.environ.get("BS_LR", "5e-4"))
SEED = int(os.environ.get("BS_SEED", "17"))
IGNORE = 255
VALID_EVERY = 10


def load_all(chip_ids: list[str]) -> tuple[np.ndarray, np.ndarray]:
    if CACHE.exists():
        data = np.load(CACHE)
        return data["x"], data["y"]

    def one(chip_id: str) -> tuple[np.ndarray, np.ndarray]:
        paths = chip_paths(BS, chip_id, "bs")
        with rasterio.open(paths["mask"]) as ds:
            mask = ds.read(1)
        return chip_tensor(load_bs_chip(chip_id, paths)).astype(np.float16), mask

    with ThreadPoolExecutor(8) as pool:
        parts = list(pool.map(one, chip_ids))
    x, y = np.stack([p[0] for p in parts]), np.stack([p[1] for p in parts])
    np.savez(CACHE, x=x, y=y)
    return x, y


def to_device(block: np.ndarray | torch.Tensor) -> torch.Tensor:
    """Батч уезжает на GPU в fp16 и приводится к float32 уже там: конвертация на CPU держала GPU на 3-5%."""
    tensor = block if isinstance(block, torch.Tensor) else torch.from_numpy(np.ascontiguousarray(block))
    return tensor.cuda().float()


def d4(x: torch.Tensor, k: int) -> torch.Tensor:
    x = torch.rot90(x, k % 4, dims=(-2, -1))
    return torch.flip(x, dims=(-1,)) if k >= 4 else x


def d4_inverse(x: torch.Tensor, k: int) -> torch.Tensor:
    x = torch.flip(x, dims=(-1,)) if k >= 4 else x
    return torch.rot90(x, -(k % 4), dims=(-2, -1))


def build(arch: str, encoder: str) -> nn.Module:
    return smp.create_model(
        arch, encoder_name=encoder, encoder_weights="imagenet", in_channels=N_CHANNELS, classes=4
    )


@torch.no_grad()
def predict(model: nn.Module, x: np.ndarray, tta: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6, 7)) -> np.ndarray:
    model.eval()
    out = np.zeros((len(x), 4, *x.shape[-2:]), dtype=np.float16)
    for start in range(0, len(x), BATCH):
        batch = to_device(x[start : start + BATCH])
        total = torch.zeros((len(batch), 4, *batch.shape[-2:]), device="cuda")
        for k in tta:
            with torch.autocast("cuda", dtype=torch.bfloat16):
                logits = model(d4(batch, k))
            total += d4_inverse(logits.float().softmax(1), k)
        out[start : start + BATCH] = (total / len(tta)).cpu().numpy().astype(np.float16)
    return out


def case_metrics(y: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    keep = y != IGNORE
    y, pred = y[keep], pred[keep]
    iou_burn = ((y > 0) & (pred > 0)).sum() / max(((y > 0) | (pred > 0)).sum(), 1)
    per_class = [((y == c) & (pred == c)).sum() / max(((y == c) | (pred == c)).sum(), 1) for c in (1, 2, 3)]
    return {
        "iou_burn": round(float(iou_burn), 4),
        "miou_sev": round(float(np.mean(per_class)), 4),
        "iou_sev": [round(float(v), 4) for v in per_class],
    }


def train_fold(
    x: np.ndarray,
    y: np.ndarray,
    train_idx: np.ndarray,
    valid_idx: np.ndarray,
    arch: str,
    encoder: str,
    epochs: int,
    seed: int,
    fold: int,
) -> nn.Module:
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    model = build(arch, encoder).cuda().to(memory_format=torch.channels_last)
    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=1e-4)
    steps = epochs * (len(train_idx) // BATCH)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(optimizer, max_lr=LR, total_steps=steps, pct_start=0.1)
    ce = nn.CrossEntropyLoss(ignore_index=IGNORE)
    y_gpu = torch.from_numpy(y).cuda()
    dice = smp.losses.DiceLoss("multiclass", ignore_index=IGNORE)
    started = time.time()
    for epoch in range(1, epochs + 1):
        model.train()
        order = rng.permutation(train_idx)
        losses = []
        for start in range(0, len(order) - BATCH + 1, BATCH):
            ids = np.sort(order[start : start + BATCH])
            k = int(rng.integers(8))
            batch = d4(to_device(x[ids]), k).contiguous(memory_format=torch.channels_last)
            target = d4(y_gpu[ids].long(), k).contiguous()
            with torch.autocast("cuda", dtype=torch.bfloat16):
                logits = model(batch)
            loss = ce(logits.float(), target) + dice(logits.float(), target)
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            scheduler.step()
            losses.append(loss.item())
        elapsed = time.time() - started
        line = f"fold {fold} epoch {epoch:>3}/{epochs} loss {np.mean(losses):.4f} lr {scheduler.get_last_lr()[0]:.1e} {elapsed:.0f}s, осталось ~{elapsed / epoch * (epochs - epoch):.0f}s"
        if epoch % VALID_EVERY == 0 and epoch < epochs:
            line += f" | valid {case_metrics(y[valid_idx], predict(model, x[valid_idx], tta=(0,)).argmax(1))}"
        print(line, flush=True)
    return model


def main() -> None:
    tag, arch, encoder, epochs = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    folds_to_run = [int(v) for v in sys.argv[5].split(",")] if len(sys.argv) > 5 else list(range(N_FOLDS))
    WEIGHTS.mkdir(parents=True, exist_ok=True)
    meta = pd.read_csv(BS / "meta.csv")
    x, y = load_all(meta.chip_id.tolist())
    print("data", x.shape, y.shape, flush=True)
    x_gpu = torch.from_numpy(x)
    oof_path = OUT / f"oof_cnn_{tag}.npy"
    oof = np.load(oof_path) if oof_path.exists() else np.zeros((len(x), 4, *x.shape[-2:]), dtype=np.float16)
    report = {}
    for fold, (train_idx, valid_idx) in enumerate(GroupKFold(N_FOLDS).split(y, groups=meta.fire_event_id)):
        if fold not in folds_to_run:
            continue
        started = time.time()
        model = train_fold(x_gpu, y, train_idx, valid_idx, arch, encoder, epochs, SEED + fold, fold)
        oof[valid_idx] = predict(model, x_gpu[valid_idx])
        torch.save(model.state_dict(), WEIGHTS / f"{tag}_fold{fold}.pt")
        report[f"fold{fold}"] = case_metrics(y[valid_idx], oof[valid_idx].argmax(1))
        print(
            f"=== fold {fold} готов за {time.time() - started:.0f}s, TTA x8:",
            report[f"fold{fold}"],
            flush=True,
        )
        np.save(oof_path, oof)
    if len(folds_to_run) == N_FOLDS:
        report["oof"] = case_metrics(y, oof.argmax(1))
        print("OOF", report["oof"], flush=True)
    (OUT / f"cnn_{tag}.json").write_text(
        json.dumps({"arch": arch, "encoder": encoder, "epochs": epochs, **report}, indent=1), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
