"""Tests for the local DICOM store and its SQLite index."""

import threading

from pydicom import dcmread
from tests.support.factory import make_ct_dataset, make_series

from odw.core.storage import DicomStore


def test_ingest_writes_file_at_canonical_path(store, tmp_path):
    ds = make_ct_dataset()
    store.ingest(ds)

    expected = (
        tmp_path / "dicom" / ds.StudyInstanceUID / ds.SeriesInstanceUID / f"{ds.SOPInstanceUID}.dcm"
    )
    assert expected.is_file()
    reread = dcmread(expected)
    assert str(reread.PatientName) == "DOE^JANE"


def test_ingest_creates_index_rows(store):
    ds = make_ct_dataset()
    store.ingest(ds)

    studies = store.studies()
    assert len(studies) == 1
    study = studies[0]
    assert study.study_uid == ds.StudyInstanceUID
    assert study.patient_name == "DOE^JANE"
    assert study.study_date == "20260101"
    assert study.modalities == "CT"

    series = store.series_for_study(study.study_uid)
    assert len(series) == 1
    assert series[0].series_uid == ds.SeriesInstanceUID
    assert series[0].num_instances == 1

    instances = store.instances_for_series(series[0].series_uid)
    assert len(instances) == 1
    assert instances[0].sop_uid == ds.SOPInstanceUID
    assert instances[0].path.is_absolute()
    assert instances[0].path.is_file()


def test_ingest_duplicate_sop_is_idempotent(store):
    ds = make_ct_dataset()
    first = store.ingest(ds)
    second = store.ingest(ds)

    assert second.sop_uid == first.sop_uid
    assert second.path == first.path
    instances = store.instances_for_series(ds.SeriesInstanceUID)
    assert len(instances) == 1


def test_two_series_same_study_share_study_row(store):
    study_uid = "1.2.3.4.5"
    a = make_ct_dataset(study_uid=study_uid, series_uid="1.2.3.4.5.1")
    b = make_ct_dataset(study_uid=study_uid, series_uid="1.2.3.4.5.2")
    store.ingest(a)
    store.ingest(b)

    assert len(store.studies()) == 1
    assert len(store.series_for_study(study_uid)) == 2


def test_instances_sorted_by_instance_number(store):
    study_uid = "1.2.3.4.6"
    series_uid = "1.2.3.4.6.1"
    for num in (3, 1, 2):
        store.ingest(
            make_ct_dataset(study_uid=study_uid, series_uid=series_uid, instance_number=num)
        )

    instances = store.instances_for_series(series_uid)
    assert [inst.instance_number for inst in instances] == [1, 2, 3]


def test_modalities_aggregate(store):
    study_uid = "1.2.3.4.7"
    store.ingest(make_ct_dataset(study_uid=study_uid, series_uid="1.2.3.4.7.1"))
    store.ingest(make_ct_dataset(study_uid=study_uid, series_uid="1.2.3.4.7.2", modality="SR"))

    (study,) = store.studies()
    assert study.modalities == "CT, SR"


def test_studies_sorted_newest_first(store):
    old = make_ct_dataset(study_date="20240101")
    new = make_ct_dataset(study_date="20260101")
    store.ingest(old)
    store.ingest(new)

    studies = store.studies()
    assert [s.study_date for s in studies] == ["20260101", "20240101"]


def test_index_reopens_existing_db(store, tmp_path):
    ds = make_ct_dataset()
    store.ingest(ds)
    store.close()

    reopened = DicomStore(tmp_path / "dicom")
    try:
        studies = reopened.studies()
        assert len(studies) == 1
        assert studies[0].study_uid == ds.StudyInstanceUID
        instances = reopened.instances_for_series(ds.SeriesInstanceUID)
        assert len(instances) == 1
        assert instances[0].path.is_file()
    finally:
        reopened.close()


def test_load_series_datasets_ordered(store):
    series = make_series(3)
    series_uid = series[0].SeriesInstanceUID
    for ds in reversed(series):
        store.ingest(ds)

    datasets = store.load_series_datasets(series_uid)
    assert [int(ds.InstanceNumber) for ds in datasets] == [1, 2, 3]
    assert datasets[0].pixel_array.shape == (64, 64)


def test_concurrent_ingest_from_thread(store):
    ds = make_ct_dataset()
    errors: list[Exception] = []

    def worker():
        try:
            store.ingest(ds)
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    # main thread reads concurrently
    store.studies()
    thread.join()

    assert errors == []
    instances = store.instances_for_series(ds.SeriesInstanceUID)
    assert len(instances) == 1
