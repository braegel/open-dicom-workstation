"""Measurement geometry: length labels, ROI masks and ROI statistics.

No Qt imports here — this module must stay usable from scripts and tests
without a GUI toolkit (enforced by tests/unit/test_core_is_qt_free.py).
Points are (x=column, y=row) in image pixel coordinates; a pixel (r, c)
belongs to a region iff its center (x=c, y=r) is inside the shape.
"""

import math
from dataclasses import dataclass

import numpy as np

__all__ = [
    "RoiStats",
    "ellipse_mask",
    "length_label",
    "polygon_mask",
    "roi_stats",
]


@dataclass(frozen=True)
class RoiStats:
    count: int
    median: float
    std: float  # population std, ddof=0


def length_label(
    p1: tuple[float, float],
    p2: tuple[float, float],
    pixel_spacing: tuple[float, float] | None,
) -> str:
    """Distance between two points as a display label.

    With DICOM PixelSpacing (row_spacing_mm, col_spacing_mm) the result is in
    millimetres; without spacing it falls back to pixels.
    """
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    if pixel_spacing is None:
        return f"{math.hypot(dx, dy):.1f} px"
    row_spacing, col_spacing = pixel_spacing
    return f"{math.hypot(dx * col_spacing, dy * row_spacing):.1f} mm"


def polygon_mask(shape: tuple[int, int], vertices: list[tuple[float, float]]) -> np.ndarray:
    """Boolean (rows, cols) mask of pixel centers inside the polygon (even-odd rule)."""
    rows, cols = shape
    mask = np.zeros((rows, cols), dtype=bool)
    if len(vertices) < 3:
        return mask

    xs = np.array([v[0] for v in vertices], dtype=np.float64)
    ys = np.array([v[1] for v in vertices], dtype=np.float64)
    xs_next = np.roll(xs, -1)
    ys_next = np.roll(ys, -1)
    x_centers = np.arange(cols, dtype=np.float64)

    for r in range(rows):
        y = float(r)
        # Edges whose y-span straddles this scanline (even-odd half-open rule).
        straddles = (ys > y) != (ys_next > y)
        if not straddles.any():
            continue
        t = (y - ys[straddles]) / (ys_next[straddles] - ys[straddles])
        crossings_x = xs[straddles] + t * (xs_next[straddles] - xs[straddles])
        # A center is inside iff an odd number of crossings lie to its right.
        counts = (crossings_x[:, None] > x_centers[None, :]).sum(axis=0)
        mask[r] = counts % 2 == 1
    return mask


def ellipse_mask(
    shape: tuple[int, int], center: tuple[float, float], rx: float, ry: float
) -> np.ndarray:
    """Boolean (rows, cols) mask of pixel centers inside the axis-aligned ellipse."""
    rows, cols = shape
    if rx <= 0.0 or ry <= 0.0:
        return np.zeros((rows, cols), dtype=bool)
    cx, cy = center
    x = np.arange(cols, dtype=np.float64)[None, :]
    y = np.arange(rows, dtype=np.float64)[:, None]
    inside: np.ndarray = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0
    return inside


def roi_stats(values: np.ndarray, mask: np.ndarray) -> RoiStats:
    """Median and population std (ddof=0) of values selected by the mask."""
    selected = values[mask]
    if selected.size == 0:
        return RoiStats(count=0, median=math.nan, std=math.nan)
    return RoiStats(
        count=int(selected.size),
        median=float(np.median(selected)),
        std=float(np.std(selected)),
    )
