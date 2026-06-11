"""Tests for measurement geometry: lengths, ROI masks and ROI statistics."""

import math

import numpy as np
import pytest

from odw.core.measure import (
    RoiStats,
    ellipse_mask,
    length_label,
    polygon_mask,
    roi_stats,
)


class TestLengthLabel:
    def test_pixels_without_spacing_345_triangle(self) -> None:
        assert length_label((0.0, 0.0), (3.0, 4.0), None) == "5.0 px"

    def test_millimetres_with_anisotropic_spacing(self) -> None:
        # dx = 4 px, dy = 3 px; PixelSpacing = (row=1.0 mm, col=0.5 mm)
        # mm = hypot(4 * 0.5, 3 * 1.0) = hypot(2.0, 3.0) = 3.6056 -> "3.6 mm"
        assert length_label((0.0, 0.0), (4.0, 3.0), (1.0, 0.5)) == "3.6 mm"

    def test_zero_length(self) -> None:
        assert length_label((1.0, 1.0), (1.0, 1.0), None) == "0.0 px"


class TestPolygonMask:
    def test_axis_aligned_square(self) -> None:
        # Square from (0.5, 0.5) to (2.5, 2.5): pixel centers (x, y) with
        # x in {1, 2} and y in {1, 2} are inside -> pixels (1,1),(1,2),(2,1),(2,2).
        vertices = [(0.5, 0.5), (2.5, 0.5), (2.5, 2.5), (0.5, 2.5)]

        mask = polygon_mask((4, 4), vertices)

        expected = np.zeros((4, 4), dtype=bool)
        expected[1:3, 1:3] = True
        assert mask.dtype == np.bool_
        np.testing.assert_array_equal(mask, expected)

    def test_triangle_inside_and_outside_pixels(self) -> None:
        # Right triangle (0,0), (4,0), (0,4): interior is x + y < 4 (x, y > 0).
        vertices = [(0.0, 0.0), (4.0, 0.0), (0.0, 4.0)]

        mask = polygon_mask((5, 5), vertices)

        assert mask[1, 1]  # pixel center (x=1, y=1): 1 + 1 < 4 -> inside
        assert not mask[3, 3]  # pixel center (x=3, y=3): 3 + 3 > 4 -> outside

    @pytest.mark.parametrize(
        "vertices",
        [[], [(1.0, 1.0)], [(0.0, 0.0), (3.0, 3.0)]],
    )
    def test_degenerate_polygon_is_all_false(self, vertices: list[tuple[float, float]]) -> None:
        mask = polygon_mask((4, 4), vertices)

        assert mask.shape == (4, 4)
        assert not mask.any()


class TestEllipseMask:
    def test_circle_radius_1_5_in_5x5(self) -> None:
        # Distances from center (2, 2): center 0, edge neighbours 1,
        # diagonal neighbours sqrt(2) ~ 1.414 -> all <= 1.5; pixels two
        # steps away are at distance >= 2 -> outside. Result: 3x3 block.
        mask = ellipse_mask((5, 5), (2.0, 2.0), 1.5, 1.5)

        expected = np.zeros((5, 5), dtype=bool)
        expected[1:4, 1:4] = True
        assert mask.dtype == np.bool_
        np.testing.assert_array_equal(mask, expected)

    def test_anisotropic_ellipse(self) -> None:
        # rx=2, ry=0.5 at (2, 2): only row 2 with |x - 2| <= 2 is inside.
        mask = ellipse_mask((5, 5), (2.0, 2.0), 2.0, 0.5)

        expected = np.zeros((5, 5), dtype=bool)
        expected[2, 0:5] = True
        np.testing.assert_array_equal(mask, expected)

    @pytest.mark.parametrize(("rx", "ry"), [(0.0, 1.0), (1.0, 0.0), (-1.0, 1.0)])
    def test_non_positive_radius_is_all_false(self, rx: float, ry: float) -> None:
        mask = ellipse_mask((5, 5), (2.0, 2.0), rx, ry)

        assert mask.shape == (5, 5)
        assert not mask.any()


class TestRoiStats:
    def test_median_and_population_std(self) -> None:
        values = np.array([[1.0, 2.0], [3.0, 100.0]])
        mask = np.array([[True, True], [True, False]])

        stats = roi_stats(values, mask)

        assert stats == RoiStats(count=3, median=2.0, std=pytest.approx(math.sqrt(2.0 / 3.0)))

    def test_empty_mask_yields_nan(self) -> None:
        values = np.array([[1.0, 2.0], [3.0, 4.0]])
        mask = np.zeros((2, 2), dtype=bool)

        stats = roi_stats(values, mask)

        assert stats.count == 0
        assert math.isnan(stats.median)
        assert math.isnan(stats.std)
