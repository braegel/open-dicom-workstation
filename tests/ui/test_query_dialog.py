"""Tests for the PACS query/retrieve dialog."""

import pytest
from PySide6.QtCore import Qt
from tests.conftest import free_port
from tests.support.factory import make_ct_dataset, make_series
from tests.support.mock_pacs import MockPacs

from odw.core.config import AppConfig
from odw.core.models import PacsNode
from odw.core.net.scp import StorageScp
from odw.ui.query_dialog import QueryDialog


@pytest.fixture
def mock_pacs():
    """MockPacs preloaded with a 3-instance DOE^JANE study and one ROE^RICHARD study."""
    doe_series = make_series(3)
    pacs = MockPacs()
    pacs.add_instances(doe_series)
    pacs.add_instances([make_ct_dataset(patient_name="ROE^RICHARD", patient_id="PID002")])
    pacs.doe_study_uid = str(doe_series[0].StudyInstanceUID)
    with pacs:
        yield pacs


def _config_for(pacs: MockPacs, storage_dir, retrieve_method: str = "C-GET") -> AppConfig:
    node = PacsNode(
        name="Mock PACS",
        ae_title=pacs.aet,
        host="127.0.0.1",
        port=pacs.port,
        retrieve_method=retrieve_method,
    )
    return AppConfig(local_ae_title="ODW", listen_port=0, storage_dir=storage_dir, nodes=[node])


def _make_dialog(qtbot, config, store) -> QueryDialog:
    dialog = QueryDialog(config, store)
    qtbot.addWidget(dialog)
    return dialog


def _search(qtbot, dialog: QueryDialog, pattern: str, expected_rows: int = 1) -> None:
    dialog.patient_name_edit.setText(pattern)
    qtbot.mouseClick(dialog.search_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: dialog.results_model.rowCount() == expected_rows, timeout=5000)


def test_search_populates_results(qtbot, store, tmp_path, mock_pacs):
    dialog = _make_dialog(qtbot, _config_for(mock_pacs, tmp_path / "dicom"), store)

    _search(qtbot, dialog, "DOE*")

    assert dialog.results_model.rowCount() == 1
    assert dialog.results_model.study_at(0).study_uid == mock_pacs.doe_study_uid


def test_search_error_sets_status_not_exception(qtbot, store, tmp_path):
    node = PacsNode(name="Dead PACS", ae_title="NOWHERE", host="127.0.0.1", port=free_port())
    config = AppConfig(
        local_ae_title="ODW", listen_port=0, storage_dir=tmp_path / "dicom", nodes=[node]
    )
    dialog = _make_dialog(qtbot, config, store)

    dialog.patient_name_edit.setText("DOE*")
    qtbot.mouseClick(dialog.search_button, Qt.LeftButton)

    qtbot.waitUntil(lambda: dialog.status_label.text() != "", timeout=10000)
    qtbot.waitUntil(lambda: dialog.search_button.isEnabled(), timeout=10000)
    assert dialog.isEnabled()
    assert dialog.results_model.rowCount() == 0


def test_retrieve_get_ingests_study(qtbot, store, tmp_path, mock_pacs):
    config = _config_for(mock_pacs, tmp_path / "dicom", retrieve_method="C-GET")
    dialog = _make_dialog(qtbot, config, store)
    _search(qtbot, dialog, "DOE*")
    dialog.results_view.selectRow(0)

    with qtbot.waitSignal(dialog.study_retrieved, timeout=10000) as blocker:
        qtbot.mouseClick(dialog.retrieve_button, Qt.LeftButton)

    assert blocker.args == [mock_pacs.doe_study_uid]
    qtbot.waitUntil(
        lambda: mock_pacs.doe_study_uid in {s.study_uid for s in store.studies()},
        timeout=10000,
    )


def test_retrieve_move_ingests_study(qtbot, store, tmp_path, mock_pacs):
    config = _config_for(mock_pacs, tmp_path / "dicom", retrieve_method="C-MOVE")
    scp = StorageScp(config.local_ae_title, 0, store)
    scp.start()
    mock_pacs.known_destinations[config.local_ae_title] = ("127.0.0.1", scp.port)
    try:
        dialog = _make_dialog(qtbot, config, store)
        _search(qtbot, dialog, "DOE*")
        dialog.results_view.selectRow(0)

        with qtbot.waitSignal(dialog.study_retrieved, timeout=10000) as blocker:
            qtbot.mouseClick(dialog.retrieve_button, Qt.LeftButton)

        assert blocker.args == [mock_pacs.doe_study_uid]
        qtbot.waitUntil(
            lambda: mock_pacs.doe_study_uid in {s.study_uid for s in store.studies()},
            timeout=10000,
        )
    finally:
        scp.stop()
