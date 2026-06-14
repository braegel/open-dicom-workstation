"""Tests for the C-GET retrieve SCU against the in-process mock PACS."""

import pytest
from pydicom import dcmread
from pydicom.dataset import Dataset
from pydicom.uid import ImplicitVRLittleEndian, generate_uid
from tests.support.factory import make_series
from tests.support.mock_pacs import MockPacs

from odw.core.models import PacsNode
from odw.core.net import PacsConnectionError
from odw.core.net.retrieve import RetrieveScu

SERIES = make_series(3)
STUDY_UID = str(SERIES[0].StudyInstanceUID)
SERIES_UID = str(SERIES[0].SeriesInstanceUID)


@pytest.fixture
def mock_pacs():
    pacs = MockPacs()
    pacs.add_instances(SERIES)
    with pacs:
        yield pacs


@pytest.fixture
def scu(mock_pacs):
    node = PacsNode("test", "MOCKPACS", "127.0.0.1", mock_pacs.port)
    return RetrieveScu("ODW_TEST", node)


def test_get_study_stores_all_instances(scu, store):
    result = scu.get_study(STUDY_UID, store)
    assert result.completed == 3
    assert result.failed == 0
    records = store.instances_for_series(SERIES_UID)
    assert len(records) == 3
    assert {r.sop_uid for r in records} == {str(ds.SOPInstanceUID) for ds in SERIES}


def test_get_study_progress_callback(scu, store):
    calls: list[tuple[int, int]] = []
    scu.get_study(STUDY_UID, store, on_progress=lambda c, r: calls.append((c, r)))
    assert calls
    completed_counts = [c for c, _ in calls]
    assert completed_counts == sorted(completed_counts)
    last_completed, last_remaining = calls[-1]
    assert last_completed == 3
    assert last_remaining == 0


def test_get_study_with_restricted_transfer_syntaxes(mock_pacs, store):
    node = PacsNode("test", "MOCKPACS", "127.0.0.1", mock_pacs.port)
    scu = RetrieveScu("ODW_TEST", node, transfer_syntaxes=[str(ImplicitVRLittleEndian)])

    result = scu.get_study(STUDY_UID, store)

    assert result.completed == 3
    records = store.instances_for_series(SERIES_UID)
    assert len(records) == 3
    for record in records:
        stored = dcmread(record.path)
        assert stored.file_meta.TransferSyntaxUID == ImplicitVRLittleEndian


def test_get_unknown_study_completes_with_zero(scu, store):
    result = scu.get_study(generate_uid(), store)
    assert result.completed == 0
    assert store.instances_for_series(SERIES_UID) == []


def test_collect_raises_on_empty_status_dataset():
    """A peer that aborts mid-operation yields a status with no Status element.

    The PACS must surface that as a clean connection error rather than an
    opaque AttributeError on ``status.Status``.
    """
    node = PacsNode("test", "PEER", "127.0.0.1", 11112)
    scu = RetrieveScu("ODW_TEST", node)

    def responses():
        yield Dataset(), None

    with pytest.raises(PacsConnectionError):
        scu._collect(responses(), "C-GET", None)
