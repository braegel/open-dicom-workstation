"""Unit tests for the pure-NumPy pixel pipeline in odw.core.imaging.

apply_window quantization convention: the [0, 1] windowed output is scaled by
255 and truncated via ``astype(np.uint8)`` (no rounding). All expected values
below are hand-computed under that convention.
"""

import numpy as np
import pytest
from tests.support.factory import make_ct_dataset

from odw.core.imaging import (
    UnsupportedImageError,
    apply_window,
    default_window,
    modality_values,
    render_frame,
    repair_mislabeled_pixel_data,
)


class TestModalityValues:
    def test_modality_values_applies_slope_intercept(self) -> None:
        ds = make_ct_dataset(rows=2, cols=2, pixel_fill=0, slope=1.0, intercept=-1024.0)

        values = modality_values(ds)

        assert values.dtype == np.float32
        assert values.shape == (2, 2)
        np.testing.assert_array_equal(values, np.full((2, 2), -1024.0, dtype=np.float32))


class TestApplyWindow:
    def test_apply_window_center_maps_to_midgray(self) -> None:
        # value == center == 40, width = 400:
        # out = (40 - 39.5) / 399 + 0.5 = 0.50125313...
        # 0.50125313... * 255 = 127.81954... -> truncates to 127
        values = np.array([[40.0]], dtype=np.float32)

        result = apply_window(values, center=40.0, width=400.0)

        assert result.dtype == np.uint8
        assert result[0, 0] == 127

    def test_apply_window_clips_below_and_above(self) -> None:
        values = np.array([[-10000.0, 10000.0]], dtype=np.float32)

        result = apply_window(values, center=40.0, width=400.0)

        assert result[0, 0] == 0
        assert result[0, 1] == 255

    def test_apply_window_linear_interior_value(self) -> None:
        # center=0, width=401: out = (100 + 0.5) / 400 + 0.5 = 0.75125
        # 0.75125 * 255 = 191.56875 -> truncates to 191
        values = np.array([[100.0]], dtype=np.float32)

        result = apply_window(values, center=0.0, width=401.0)

        assert result[0, 0] == 191

    def test_apply_window_width_one_no_division_error(self) -> None:
        # width=1 -> binary threshold at center - 0.5 = -0.5
        values = np.array([[-2.0, -0.5, 5.0]], dtype=np.float32)

        result = apply_window(values, center=0.0, width=1.0)

        assert result[0, 0] == 0  # -2.0 < -0.5
        assert result[0, 1] == 255  # -0.5 >= -0.5
        assert result[0, 2] == 255  # 5.0 >= -0.5


class TestDefaultWindow:
    def test_default_window_from_tags(self) -> None:
        ds = make_ct_dataset(window_center=40.0, window_width=400.0)

        assert default_window(ds) == (40.0, 400.0)

    def test_default_window_multivalue_takes_first(self) -> None:
        ds = make_ct_dataset()
        ds.WindowCenter = [40, 80]
        ds.WindowWidth = [400, 2000]

        assert default_window(ds) == (40.0, 400.0)

    def test_default_window_fallback_minmax(self) -> None:
        pixels = np.array([[0, 100], [200, 300]], dtype=np.int16)
        ds = make_ct_dataset(rows=2, cols=2, pixel_fill=pixels, slope=1.0, intercept=0.0)
        del ds.WindowCenter
        del ds.WindowWidth

        center, width = default_window(ds)

        assert center == 150.0  # (0 + 300) / 2
        assert width == 300.0  # max(300 - 0, 1.0)


class TestRenderFrame:
    def test_render_frame_monochrome1_inverted(self) -> None:
        pixels = np.array([[0, 50], [150, 300]], dtype=np.int16)
        kwargs = dict(rows=2, cols=2, pixel_fill=pixels, slope=1.0, intercept=0.0)
        ds_mono2 = make_ct_dataset(photometric="MONOCHROME2", **kwargs)
        ds_mono1 = make_ct_dataset(photometric="MONOCHROME1", **kwargs)

        out2 = render_frame(ds_mono2)
        out1 = render_frame(ds_mono1)

        np.testing.assert_array_equal(
            out1.astype(np.int32) + out2.astype(np.int32),
            np.full((2, 2), 255, dtype=np.int32),
        )

    def test_render_frame_contiguous_uint8(self) -> None:
        ds = make_ct_dataset(rows=4, cols=3, pixel_fill=100)

        result = render_frame(ds)

        assert result.flags["C_CONTIGUOUS"]
        assert result.dtype == np.uint8
        assert result.shape == (4, 3)

    def test_render_frame_rejects_multisample(self) -> None:
        ds = make_ct_dataset(rows=2, cols=2)
        ds.SamplesPerPixel = 3

        with pytest.raises(UnsupportedImageError):
            render_frame(ds)

    def test_render_frame_rejects_multiframe(self) -> None:
        ds = make_ct_dataset(rows=2, cols=2)
        ds.NumberOfFrames = 2

        with pytest.raises(UnsupportedImageError):
            render_frame(ds)


class TestMislabeledPixelData:
    """Some PACS send stored compressed bytes while negotiating a native
    transfer syntax — the file then claims e.g. Implicit VR LE but PixelData
    holds an encapsulated JPEG 2000 stream."""

    def _mislabeled_j2k_dataset(self):
        from pydicom.uid import ImplicitVRLittleEndian, JPEG2000Lossless

        pixels = np.arange(1024, dtype=np.int16).reshape(32, 32)
        ds = make_ct_dataset(rows=32, cols=32, pixel_fill=pixels)
        reference = render_frame(ds)
        ds.compress(JPEG2000Lossless)
        assert ds.file_meta.TransferSyntaxUID == JPEG2000Lossless
        ds.file_meta.TransferSyntaxUID = ImplicitVRLittleEndian  # the PACS lie
        if hasattr(ds, "_pixel_array"):
            ds._pixel_array = None
            ds._pixel_id = {}
        return ds, reference

    def test_repair_detects_and_fixes_j2k(self) -> None:
        from pydicom.uid import JPEG2000Lossless

        ds, _ = self._mislabeled_j2k_dataset()

        assert repair_mislabeled_pixel_data(ds) is True
        assert ds.file_meta.TransferSyntaxUID == JPEG2000Lossless

    def test_repair_leaves_native_data_alone(self) -> None:
        ds = make_ct_dataset(rows=4, cols=4)

        assert repair_mislabeled_pixel_data(ds) is False

    def test_render_frame_repairs_mislabeled_j2k(self) -> None:
        ds, reference = self._mislabeled_j2k_dataset()

        result = render_frame(ds)

        np.testing.assert_array_equal(result, reference)  # lossless round trip

    def test_render_frame_wraps_undecodable_pixel_data(self) -> None:
        ds = make_ct_dataset(rows=16, cols=16)
        ds.PixelData = ds.PixelData[:100]  # truncated/corrupt native data

        with pytest.raises(UnsupportedImageError):
            render_frame(ds)
