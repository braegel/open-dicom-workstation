"""Tests for the C-MOVE retrieve SCU delivering to a local Storage SCP."""

import pytest
from tests.support.factory import make_series
from tests.support.mock_pacs import MockPacs

from odw.core.models import PacsNode
from odw.core.net.retrieve import RetrieveScu
from odw.core.net.scp import StorageScp

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


@pytest.fixture
def receiving_store(tmp_path):
    from odw.core.storage import DicomStore

    s = DicomStore(tmp_path / "received")
    yield s
    s.close()


@pytest.fixture
def scp(receiving_store):
    scp = StorageScp("ODW", 0, receiving_store)
    scp.start()
    yield scp
    scp.stop()


def test_move_study_delivers_to_local_scp(mock_pacs, scu, scp, receiving_store):
    mock_pacs.known_destinations["ODW"] = ("127.0.0.1", scp.port)

    result = scu.move_study(STUDY_UID, dest_aet="ODW")

    assert result.completed == 3
    assert result.failed == 0
    records = receiving_store.instances_for_series(SERIES_UID)
    assert len(records) == 3
    assert {r.sop_uid for r in records} == {str(ds.SOPInstanceUID) for ds in SERIES}


def test_move_to_unknown_destination_reports_failure(mock_pacs, scu):
    result = scu.move_study(STUDY_UID, dest_aet="NOWHERE")
    assert result.completed == 0
    assert result.failed > 0 or result.message != ""
