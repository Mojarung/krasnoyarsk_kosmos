"""RLE по правилам соревнования: нумерация с единицы, построчно слева направо и сверху вниз,
пары «начало длина» по возрастанию, серии не пересекаются и не соприкасаются."""

from __future__ import annotations

import numpy as np


def encode(mask: np.ndarray) -> str:
    flat = np.asarray(mask, dtype=bool).ravel()
    if not flat.any():
        return ""
    padded = np.concatenate([[False], flat, [False]])
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    starts, ends = edges[::2], edges[1::2]
    return " ".join(f"{start + 1} {end - start}" for start, end in zip(starts, ends, strict=True))


def decode(rle: str, shape: tuple[int, int]) -> np.ndarray:
    flat = np.zeros(shape[0] * shape[1], dtype=bool)
    if rle:
        values = [int(v) for v in rle.split()]
        for start, length in zip(values[::2], values[1::2], strict=True):
            flat[start - 1 : start - 1 + length] = True
    return flat.reshape(shape)
