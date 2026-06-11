"""Pure NumPy pixel pipeline: modality rescale, VOI windowing, photometric handling.

No Qt imports here — this module must stay usable from scripts and tests
without a GUI toolkit (enforced by tests/unit/test_core_is_qt_free.py).
"""

import numpy as np
from pydicom.dataset import Dataset
from pydicom.uid import (
    JPEG2000,
    UID,
    JPEG2000Lossless,
    JPEGBaseline8Bit,
    JPEGLosslessSV1,
    JPEGLSLossless,
)

__all__ = [
    "UnsupportedImageError",
    "apply_window",
    "default_window",
    "modality_values",
    "render_frame",
    "repair_mislabeled_pixel_data",
]

# Little-endian encoding of the DICOM item tag (FFFE,E000) that opens the
# basic offset table of encapsulated pixel data.
_ENCAPSULATION_ITEM_TAG = b"\xfe\xff\x00\xe0"


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


def _sniff_codestream_syntax(fragment: bytes, ds: Dataset) -> UID | None:
    """Guess the real transfer syntax from the first pixel data fragment."""
    if fragment.startswith(b"\xff\x4f\xff\x51"):  # JPEG 2000 codestream SOC marker
        lossy = str(ds.get("LossyImageCompression", "")) == "01"
        return JPEG2000 if lossy else JPEG2000Lossless
    if fragment.startswith(b"\xff\xd8\xff\xf7"):  # JPEG-LS SOI + SOF55
        return JPEGLSLossless
    if fragment.startswith(b"\xff\xd8"):  # plain JPEG SOI
        return JPEGBaseline8Bit if int(ds.get("BitsAllocated", 8)) <= 8 else JPEGLosslessSV1
    return None


def repair_mislabeled_pixel_data(ds: Dataset) -> bool:
    """Fix datasets whose transfer syntax claims native pixel data while the
    PixelData element actually holds an encapsulated compressed stream.

    Some PACS send their stored compressed bytes verbatim even when the
    association negotiated a native transfer syntax. Returns True if the
    dataset's transfer syntax was corrected in place.
    """
    meta = getattr(ds, "file_meta", None)
    ts = getattr(meta, "TransferSyntaxUID", None) if meta is not None else None
    if ts is None or ts.is_encapsulated:
        return False
    raw = ds.get("PixelData")
    if not isinstance(raw, bytes) or not raw.startswith(_ENCAPSULATION_ITEM_TAG):
        return False
    # Skip the basic offset table item, then read the first fragment's payload.
    offset_table_length = int.from_bytes(raw[4:8], "little")
    fragment_start = 8 + offset_table_length
    if raw[fragment_start : fragment_start + 4] != _ENCAPSULATION_ITEM_TAG:
        return False
    fragment = raw[fragment_start + 8 : fragment_start + 24]
    real_syntax = _sniff_codestream_syntax(fragment, ds)
    if real_syntax is None:
        return False
    ds.file_meta.TransferSyntaxUID = real_syntax
    return True


def _decoded_modality_values(ds: Dataset) -> np.ndarray:
    """modality_values with mislabeled-transfer-syntax repair and error wrapping."""
    try:
        return modality_values(ds)
    except Exception as exc:
        if repair_mislabeled_pixel_data(ds):
            try:
                return modality_values(ds)
            except Exception as repaired_exc:
                raise UnsupportedImageError(
                    f"Pixel data could not be decoded: {repaired_exc}"
                ) from repaired_exc
        raise UnsupportedImageError(f"Pixel data could not be decoded: {exc}") from exc


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

    values = _decoded_modality_values(ds)
    if center is None or width is None:
        tag_center = getattr(ds, "WindowCenter", None)
        tag_width = getattr(ds, "WindowWidth", None)
        if tag_center is not None and tag_width is not None:
            default_center, default_width = _scalar(tag_center), _scalar(tag_width)
        else:
            mn, mx = float(values.min()), float(values.max())
            default_center, default_width = (mn + mx) / 2.0, max(mx - mn, 1.0)
        center = default_center if center is None else center
        width = default_width if width is None else width

    out = apply_window(values, center, width)
    if str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2")) == "MONOCHROME1":
        out = 255 - out
    return np.ascontiguousarray(out)
