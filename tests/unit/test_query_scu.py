"""Tests for the C-FIND query SCU against an in-process mock PACS."""

import pytest
from pydicom.uid import generate_uid
from tests.conftest import free_port
from tests.support.factory import make_ct_dataset, make_series

from odw.core.models import PacsNode, SeriesQueryResult, StudyQueryResult
from odw.core.net import PacsConnectionError
from odw.core.net.query import QueryScu

TWO_SERIES_STUDY_UID = generate_uid()


@pytest.fixture
def mock_pacs():
    from tests.support.mock_pacs import MockPacs

    pacs = MockPacs()
    # Study 1: DOE^JANE, 20250101, one CT series with 2 instances.
    pacs.add_instances(
        make_series(2, patient_name="DOE^JANE", patient_id="PID001", study_date="20250101")
    )
    # Study 2: DOE^JANE, 20260101, two series (CT x3 + SR x1) in one study.
    ct_series_uid = generate_uid()
    sr_series_uid = generate_uid()
    pacs.add_instances(
        [
            make_ct_dataset(
                study_uid=TWO_SERIES_STUDY_UID,
                series_uid=ct_series_uid,
                instance_number=i,
                patient_name="DOE^JANE",
                patient_id="PID001",
                study_date="20260101",
                modality="CT",
            )
            for i in range(1, 4)
        ]
        + [
            make_ct_dataset(
                study_uid=TWO_SERIES_STUDY_UID,
                series_uid=sr_series_uid,
                instance_number=1,
                patient_name="DOE^JANE",
                patient_id="PID001",
                study_date="20260101",
                modality="SR",
            )
        ]
    )
    # Study 3: ROE^RICHARD, 20260101.
    pacs.add_instances(
        make_series(1, patient_name="ROE^RICHARD", patient_id="PID002", study_date="20260101")
    )
    with pacs:
        yield pacs


@pytest.fixture
def scu(mock_pacs):
    node = PacsNode("test", "MOCKPACS", "127.0.0.1", mock_pacs.port)
    return QueryScu("ODW_TEST", node)


def test_find_studies_by_patient_name_wildcard(scu):
    results = scu.find_studies(patient_name="DOE*")
    assert len(results) == 2
    assert all(isinstance(r, StudyQueryResult) for r in results)
    for r in results:
        assert r.patient_id == "PID001"
        assert r.study_date in ("20250101", "20260101")
        assert r.accession_number == "ACC001"
    assert not any("ROE" in r.patient_name for r in results)


def test_find_studies_by_date(scu):
    results = scu.find_studies(study_date="20250101")
    assert len(results) == 1
    assert results[0].study_date == "20250101"


def test_find_studies_no_match_returns_empty(scu):
    assert scu.find_studies(patient_name="NOBODY*") == []


def test_find_studies_reports_series_and_instance_counts(scu):
    results = scu.find_studies(patient_name="DOE*", study_date="20260101")
    assert len(results) == 1
    study = results[0]
    assert study.num_series == 2
    assert study.num_instances == 4
    assert "CT" in study.modalities
    assert "SR" in study.modalities


def test_find_series_for_study(scu):
    results = scu.find_series(TWO_SERIES_STUDY_UID)
    assert len(results) == 2
    assert all(isinstance(r, SeriesQueryResult) for r in results)
    modalities = {r.modality for r in results}
    assert modalities == {"CT", "SR"}
    by_modality = {r.modality: r for r in results}
    assert by_modality["CT"].num_instances == 3
    assert by_modality["SR"].num_instances == 1


def test_connection_refused_raises_pacs_error():
    node = PacsNode("dead", "NOPACS", "127.0.0.1", free_port())
    scu = QueryScu("ODW_TEST", node)
    with pytest.raises(PacsConnectionError):
        scu.find_studies(patient_name="DOE*")
