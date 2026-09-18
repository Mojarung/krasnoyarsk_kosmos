import numpy as np
import pytest

from fire_ml.rle import decode, encode


def test_encoding_is_one_based_row_major() -> None:
    mask = np.zeros((3, 4), dtype=bool)
    mask[0, 0] = True
    mask[1, 2:4] = True

    assert encode(mask) == "1 1 7 2"


def test_run_continues_across_row_boundary() -> None:
    mask = np.zeros((2, 3), dtype=bool)
    mask[0, 2] = True
    mask[1, 0] = True

    assert encode(mask) == "3 2"


def test_empty_mask_gives_empty_string() -> None:
    assert encode(np.zeros((4, 4), dtype=bool)) == ""


def test_full_mask_is_single_run_within_bounds() -> None:
    assert encode(np.ones((256, 256), dtype=bool)) == "1 65536"


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_round_trip_and_runs_never_touch(seed: int) -> None:
    mask = np.random.default_rng(seed).random((64, 64)) > 0.7

    rle = encode(mask)
    values = [int(v) for v in rle.split()]
    starts, lengths = np.array(values[::2]), np.array(values[1::2])

    assert np.array_equal(decode(rle, mask.shape), mask)
    assert np.all(starts[1:] > starts[:-1] + lengths[:-1])
