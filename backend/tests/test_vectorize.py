import numpy as np
import pytest
from affine import Affine

from firewatch.pipeline.vectorize import vectorize_severity

PIXEL_M = 20.0
PIXEL_HA = 0.04
TRANSFORM = Affine(PIXEL_M, 0.0, 491520.0, 0.0, -PIXEL_M, 5386240.0)


def make_mask() -> np.ndarray:
    mask = np.zeros((64, 64), dtype=np.uint8)
    mask[4:20, 4:20] = 1
    mask[8:14, 8:14] = 3
    mask[30:40, 30:50] = 2
    mask[40, 50] = 1
    return mask


def test_vector_area_equals_pixel_area_per_severity() -> None:
    mask = make_mask()

    _, severity_shapes = vectorize_severity(mask, TRANSFORM)

    for klass in (1, 2, 3):
        vector_ha = sum(s.area_ha for s in severity_shapes if s.severity == klass)
        assert vector_ha == pytest.approx((mask == klass).sum() * PIXEL_HA)


def test_diagonal_neighbours_belong_to_one_burn_contour() -> None:
    mask = make_mask()

    burn_shapes, severity_shapes = vectorize_severity(mask, TRANSFORM)

    assert len(burn_shapes) == 2
    diagonal = next(b for b in burn_shapes if b.severity_ha[1] > 0)
    assert diagonal.area_ha == pytest.approx((200 + 1) * PIXEL_HA)
    assert {s.burn_label for s in severity_shapes} == {b.label for b in burn_shapes}


def test_contour_severity_split_sums_to_contour_area() -> None:
    burn_shapes, _ = vectorize_severity(make_mask(), TRANSFORM)

    for burn in burn_shapes:
        assert sum(burn.severity_ha) == pytest.approx(burn.area_ha)
        assert burn.geom_utm.is_valid


def test_empty_mask_gives_no_shapes() -> None:
    assert vectorize_severity(np.zeros((16, 16), dtype=np.uint8), TRANSFORM) == ([], [])


def test_min_polygon_filter_drops_single_pixels() -> None:
    _, severity_shapes = vectorize_severity(make_mask(), TRANSFORM, min_polygon_px=2)

    assert all(s.area_ha >= 2 * PIXEL_HA for s in severity_shapes)
