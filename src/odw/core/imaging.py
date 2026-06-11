"""Pure NumPy pixel pipeline: modality rescale, VOI windowing, photometric handling.

No Qt imports here — this module must stay usable from scripts and tests
without a GUI toolkit (enforced by tests/unit/test_core_is_qt_free.py).
"""

import numpy as np
from pydicom.dataset import Dataset

__all__ = [
    "UnsupportedImageError",
    "apply_window",
    "default_window",
    "modality_values",
    "render_frame",
]


class UnsupportedImageError(Exception):
    """Raised when a dataset's image format is not supported for rendering."""


def _scalar(value: object) -> float:
    """Coerce a DICOM tag value to float, taking the first element of a MultiValue."""
    try:
        return float(value)  # type: ignore[arg-type]
    except TypeError:
        return float(value[0])  # type: ignore[index]


def modality_values(ds: Dataset) -> np.ndarray:
    """Stored pixel values mapped to modality units (e.g. Hounsfield) as float32."""
    slope = float(getattr(ds, "RescaleSlope", 1.0))
    intercept = float(getattr(ds, "RescaleIntercept", 0.0))
    return ds.pixel_array.astype(np.float32) * slope + intercept


def default_window(ds: Dataset) -> tuple[float, float]:
    """(center, width) from WindowCenter/WindowWidth, or derived from the data range."""
    center = getattr(ds, "WindowCenter", None)
    width = getattr(ds, "WindowWidth", None)
    if center is None or width is None:
        values = modality_values(ds)
        mn = float(values.min())
        mx = float(values.max())
        return ((mn + mx) / 2.0, max(mx - mn, 1.0))
    return (_scalar(center), _scalar(width))


def apply_window(values: np.ndarray, center: float, width: float) -> np.ndarray:
    """Linear VOI LUT (DICOM PS3.3 C.11.2.1.2.1) mapped to uint8 via truncation."""
    w = max(float(width), 1.0)
    if w == 1.0:
        out = (values >= center - 0.5).astype(np.float32)
    else:
        out = np.clip((values - (center - 0.5)) / (w - 1.0) + 0.5, 0.0, 1.0)
    return (out * 255.0).astype(np.uint8)


def render_frame(
    ds: Dataset, center: float | None = None, width: float | None = None
) -> np.ndarray:
    """Render a single grayscale frame to a C-contiguous uint8 2-D array."""
    if int(getattr(ds, "SamplesPerPixel", 1)) != 1:
        raise UnsupportedImageError(
            f"SamplesPerPixel={ds.SamplesPerPixel} is not supported (expected 1)"
        )
    if int(getattr(ds, "NumberOfFrames", 1)) > 1:
        raise UnsupportedImageError(
            f"NumberOfFrames={ds.NumberOfFrames} is not supported (expected single frame)"
        )

    if center is None or width is None:
        default_center, default_width = default_window(ds)
        center = default_center if center is None else center
        width = default_width if width is None else width

    out = apply_window(modality_values(ds), center, width)
    if str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2")) == "MONOCHROME1":
        out = 255 - out
    return np.ascontiguousarray(out)
