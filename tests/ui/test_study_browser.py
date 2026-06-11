"""Tests for the study browser widget and its table models."""

from PySide6.QtCore import Qt
from tests.support.factory import make_ct_dataset

from odw.ui.study_browser import StudyBrowser, StudyTableModel

PATIENT_NAME_COLUMN = 0


def test_model_lists_ingested_studies(store):
    store.ingest(make_ct_dataset(patient_name="DOE^JANE", patient_id="PID001"))
    store.ingest(make_ct_dataset(patient_name="ROE^RICHARD", patient_id="PID002"))

    model = StudyTableModel(store)

    assert model.rowCount() == 2
    names = {
        model.data(model.index(row, PATIENT_NAME_COLUMN), Qt.DisplayRole)
        for row in range(model.rowCount())
    }
    assert names == {"DOE^JANE", "ROE^RICHARD"}
    for col in range(model.columnCount()):
        header = model.headerData(col, Qt.Horizontal, Qt.DisplayRole)
        assert isinstance(header, str)
        assert header.strip()


def test_refresh_picks_up_new_ingest(store):
    model = StudyTableModel(store)
    assert model.rowCount() == 0

    store.ingest(make_ct_dataset())
    model.refresh()

    assert model.rowCount() == 1


def _ingest_study_with_two_series(store) -> tuple[str, list[str]]:
    study_uid = "1.2.826.0.1.3680043.8.498.1000"
    series_uids = [
        "1.2.826.0.1.3680043.8.498.1001",
        "1.2.826.0.1.3680043.8.498.1002",
    ]
    for series_uid in series_uids:
        store.ingest(make_ct_dataset(study_uid=study_uid, series_uid=series_uid))
    return study_uid, series_uids


def test_selecting_study_shows_its_series(qtbot, store):
    _ingest_study_with_two_series(store)

    browser = StudyBrowser(store)
    qtbot.addWidget(browser)

    browser.studies_view.selectRow(0)

    assert browser.series_view.model().rowCount() == 2


def test_double_click_series_emits_series_activated(qtbot, store):
    _, series_uids = _ingest_study_with_two_series(store)

    browser = StudyBrowser(store)
    qtbot.addWidget(browser)
    browser.studies_view.selectRow(0)

    series_model = browser.series_view.model()
    index = series_model.index(0, 0)
    with qtbot.waitSignal(browser.series_activated, timeout=5000) as blocker:
        browser.series_view.activated.emit(index)

    assert blocker.args[0] in series_uids
    assert blocker.args[0] == series_model.series_at(0).series_uid
