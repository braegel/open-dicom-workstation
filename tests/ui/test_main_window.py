"""Tests for the main window, settings dialog and application entry helpers."""

import pytest
from PySide6.QtCore import QLocale
from tests.support.factory import make_ct_dataset, make_series

from odw.app import install_translator
from odw.core.config import AppConfig
from odw.core.models import PacsNode
from odw.ui.main_window import MainWindow
from odw.ui.settings_dialog import SettingsDialog


@pytest.fixture
def window(qtbot, tmp_path):
    config = AppConfig(
        local_ae_title="ODW",
        listen_port=0,
        storage_dir=tmp_path / "dicom",
        nodes=[],
    )
    w = MainWindow(config, config_path=tmp_path / "config.toml")
    qtbot.addWidget(w)
    yield w
    w.close()


def test_main_window_constructs_and_starts_scp(window):
    assert window.scp.port > 0
    assert window.stacked.currentIndex() == 0
    assert window.browser is window.stacked.currentWidget()
    window.close()


def test_activating_series_opens_viewer(qtbot, window):
    series = make_series(2)
    for ds in series:
        window.store.ingest(ds)
    window.browser.refresh()

    window.browser.series_activated.emit(str(series[0].SeriesInstanceUID))

    qtbot.waitUntil(lambda: window.stacked.currentIndex() == 1, timeout=5000)
    assert window.viewer.current_index == 0


def test_back_action_returns_to_browser(window):
    window.stacked.setCurrentIndex(1)

    window.action_back.trigger()

    assert window.stacked.currentIndex() == 0


def test_scp_ingest_triggers_browser_refresh(qtbot, window):
    assert window.browser.studies_view.model().rowCount() == 0

    record = window.store.ingest(make_ct_dataset())
    window._bridge.notify(record)
    window._bridge.notify(record)  # coalesces into a single refresh

    qtbot.wait(700)
    assert window.browser.studies_view.model().rowCount() == 1


def test_close_event_stops_scp(window):
    window.close()

    with pytest.raises(RuntimeError):
        _ = window.scp.port


def test_settings_dialog_roundtrip(qtbot, tmp_path):
    config = AppConfig(
        local_ae_title="ODW",
        listen_port=11112,
        storage_dir=tmp_path / "dicom",
        nodes=[PacsNode(name="Existing", ae_title="EXIST", host="10.0.0.1", port=104)],
    )
    dialog = SettingsDialog(config)
    qtbot.addWidget(dialog)

    dialog.aet_edit.setText("MYAET")
    dialog.add_node_button.click()
    row = dialog.nodes_table.rowCount() - 1
    for col, value in enumerate(("Main PACS", "PACS1", "10.0.0.5", "11112")):
        dialog.nodes_table.item(row, col).setText(value)

    result = dialog.result_config()

    assert result.local_ae_title == "MYAET"
    assert result.listen_port == 11112
    assert result.storage_dir == tmp_path / "dicom"
    assert result.nodes == [
        PacsNode(name="Existing", ae_title="EXIST", host="10.0.0.1", port=104),
        PacsNode(name="Main PACS", ae_title="PACS1", host="10.0.0.5", port=11112),
    ]


def test_install_translator_without_qm_returns_false(qapp):
    assert install_translator(qapp, QLocale("de_DE")) is False
