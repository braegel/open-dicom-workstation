"""Tests for the synthetic DICOM dataset factory."""

import numpy as np
from pydicom import dcmread, dcmwrite
from pydicom.uid import ExplicitVRLittleEndian
from tests.support.factory import make_ct_dataset, make_series


def test_dataset_roundtrips_through_file(tmp_path):
    ds = make_ct_dataset()
    path = tmp_path / "ct.dcm"
    dcmwrite(path, ds)
    loaded = dcmread(path)
    assert str(loaded.PatientName) == "DOE^JANE"
    arr = loaded.pixel_array
    assert arr.shape == (64, 64)
    assert arr.dtype == np.int16


def test_pixel_fill_int():
    ds = make_ct_dataset(pixel_fill=100)
    assert (ds.pixel_array == 100).all()


def test_pixel_fill_array():
    custom = np.arange(64, dtype=np.int16).reshape(8, 8)
    ds = make_ct_dataset(rows=8, cols=8, pixel_fill=custom)
    np.testing.assert_array_equal(ds.pixel_array, custom)


def test_uids_unique_across_calls():
    a = make_ct_dataset()
    b = make_ct_dataset()
    assert a.StudyInstanceUID != b.StudyInstanceUID
    assert a.SeriesInstanceUID != b.SeriesInstanceUID
    assert a.SOPInstanceUID != b.SOPInstanceUID


def test_explicit_uids_respected():
    study = "1.2.3.4.5"
    series = "1.2.3.4.6"
    sop = "1.2.3.4.7"
    ds = make_ct_dataset(study_uid=study, series_uid=series, sop_uid=sop)
    assert ds.StudyInstanceUID == study
    assert ds.SeriesInstanceUID == series
    assert ds.SOPInstanceUID == sop
    assert ds.file_meta.MediaStorageSOPInstanceUID == sop


def test_make_series_shares_study_and_series():
    series = make_series(5)
    assert len(series) == 5
    assert len({ds.StudyInstanceUID for ds in series}) == 1
    assert len({ds.SeriesInstanceUID for ds in series}) == 1
    assert [ds.InstanceNumber for ds in series] == [1, 2, 3, 4, 5]
    assert len({ds.SOPInstanceUID for ds in series}) == 5


def test_window_and_rescale_tags():
    ds = make_ct_dataset(window_center=50.0, window_width=350.0, slope=2.0, intercept=-1000.0)
    assert ds.WindowCenter == 50.0
    assert ds.WindowWidth == 350.0
    assert ds.RescaleSlope == 2.0
    assert ds.RescaleIntercept == -1000.0


def test_file_meta_transfer_syntax():
    ds = make_ct_dataset()
    assert ds.file_meta.TransferSyntaxUID == ExplicitVRLittleEndian
