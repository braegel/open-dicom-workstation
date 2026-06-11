"""Tests for the main window, settings dialog and application entry helpers."""

import socket

import pytest
from pydicom.uid import ImplicitVRLittleEndian
from PySide6.QtCore import QLocale, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDialogButtonBox, QLineEdit, QMenu
from tests.support.factory import make_ct_dataset, make_series

from odw.app import install_translator
from odw.core.config import DEFAULT_VIEWER_SHORTCUTS, AppConfig, load_config
from odw.core.models import PacsNode
from odw.core.transfer import DEFAULT_TRANSFER_SYNTAXES
from odw.ui.main_window import MainWindow
from odw.ui.settings_dialog import SettingsDialog
from odw.ui.shortcuts_dialog import ShortcutsDialog


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


def test_busy_listen_port_degrades_gracefully(qtbot, tmp_path):
    # A second instance (or another PACS tool) may already hold the port:
    # the app must still come up — viewing and C-GET work without a listener.
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("0.0.0.0", 0))
    blocker.listen(1)
    busy_port = blocker.getsockname()[1]
    try:
        config = AppConfig(listen_port=busy_port, storage_dir=tmp_path / "dicom", nodes=[])
        w = MainWindow(config, config_path=tmp_path / "config.toml")
        qtbot.addWidget(w)

        assert not w.scp.is_running
        assert str(busy_port) in w.statusBar().currentMessage()
        assert w.stacked.currentIndex() == 0
        w.close()
    finally:
        blocker.close()


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
    dialog.nodes_table.cellWidget(row, 4).setCurrentText("C-MOVE")
    for i in range(dialog.syntax_list.count()):
        item = dialog.syntax_list.item(i)
        checked = item.data(Qt.ItemDataRole.UserRole) == str(ImplicitVRLittleEndian)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    result = dialog.result_config()

    assert result.local_ae_title == "MYAET"
    assert result.listen_port == 11112
    assert result.storage_dir == tmp_path / "dicom"
    assert result.nodes == [
        PacsNode(name="Existing", ae_title="EXIST", host="10.0.0.1", port=104),
        PacsNode(
            name="Main PACS",
            ae_title="PACS1",
            host="10.0.0.5",
            port=11112,
            retrieve_method="C-MOVE",
        ),
    ]
    assert result.transfer_syntaxes == [str(ImplicitVRLittleEndian)]


def test_settings_dialog_no_syntax_checked_falls_back_to_defaults(qtbot, tmp_path):
    config = AppConfig(storage_dir=tmp_path / "dicom", nodes=[])
    dialog = SettingsDialog(config)
    qtbot.addWidget(dialog)

    for i in range(dialog.syntax_list.count()):
        dialog.syntax_list.item(i).setCheckState(Qt.CheckState.Unchecked)

    assert dialog.result_config().transfer_syntaxes == DEFAULT_TRANSFER_SYNTAXES


def test_install_translator_without_qm_returns_false(qapp):
    assert install_translator(qapp, QLocale("de_DE")) is False


def test_tools_menu_lists_tools_with_shortcuts(window):
    menu = window.findChild(QMenu, "menu_tools")
    assert menu is not None

    zoom_action = window.findChild(QAction, "action_tool_zoom")
    assert zoom_action.text() == "Zoom"
    assert zoom_action.shortcut().toString() == "Z"

    tool_actions = [a for a in menu.actions() if a.objectName().startswith("action_tool_")]
    assert len(tool_actions) == 5
    assert window.findChild(QAction, "action_tool_window").isChecked()


def test_tool_action_switches_viewer_tool(window):
    action = window.findChild(QAction, "action_tool_zoom")

    action.trigger()

    assert window.viewer.active_tool == "zoom"
    assert action.isChecked()


def test_viewer_tool_change_syncs_menu(window):
    window.viewer.set_tool("length")

    assert window.findChild(QAction, "action_tool_length").isChecked()


def test_presets_menu_applies_window(window):
    presets_menu = window.findChild(QMenu, "menu_presets")
    assert presets_menu is not None
    stroke_action = next(a for a in presets_menu.actions() if "Stroke" in a.text())
    assert stroke_action.shortcut().toString() == "6"

    stroke_action.trigger()

    assert window.viewer.window_center == 32.0
    assert window.viewer.window_width == 8.0


def test_shortcuts_dialog_rejects_duplicates(qtbot):
    dialog = ShortcutsDialog(dict(DEFAULT_VIEWER_SHORTCUTS))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.findChild(QLineEdit, "edit_window").setText("Q")
    dialog.findChild(QLineEdit, "edit_zoom").setText("Q")

    dialog.button_box.button(QDialogButtonBox.StandardButton.Ok).click()

    assert dialog.isVisible()
    assert dialog.error_label.text() != ""


def test_shortcuts_dialog_rejects_digits(qtbot):
    dialog = ShortcutsDialog(dict(DEFAULT_VIEWER_SHORTCUTS))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.findChild(QLineEdit, "edit_zoom").setText("5")

    dialog.button_box.button(QDialogButtonBox.StandardButton.Ok).click()

    assert dialog.isVisible()
    assert dialog.error_label.text() != ""


def test_edited_shortcuts_persist_and_apply(qtbot, tmp_path):
    # The shared fixture uses listen_port=0 (ephemeral), which save_config would
    # persist but load_config rejects; this round-trip needs a valid port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]
    config = AppConfig(listen_port=free_port, storage_dir=tmp_path / "dicom", nodes=[])
    window = MainWindow(config, config_path=tmp_path / "config.toml")
    qtbot.addWidget(window)

    dialog = ShortcutsDialog(dict(DEFAULT_VIEWER_SHORTCUTS))
    qtbot.addWidget(dialog)
    dialog.findChild(QLineEdit, "edit_zoom").setText("Y")

    window._apply_shortcuts(dialog.result_shortcuts())

    config = load_config(tmp_path / "config.toml")
    assert config.viewer_shortcuts["zoom"] == "Y"
    assert window.findChild(QAction, "action_tool_zoom").shortcut().toString() == "Y"

    qtbot.keyClick(window.viewer, Qt.Key.Key_Y)
    assert window.viewer.active_tool == "zoom"
    window.close()
