"""Main window: study browser, slice viewer, query/retrieve and settings."""

from pathlib import Path

from pydicom.dataset import Dataset
from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QMainWindow, QStackedWidget

from odw.core.config import AppConfig, save_config
from odw.core.net.scp import StorageScp
from odw.core.storage import DicomStore
from odw.ui.query_dialog import QueryDialog
from odw.ui.scp_bridge import ScpBridge
from odw.ui.settings_dialog import SettingsDialog
from odw.ui.study_browser import StudyBrowser
from odw.ui.viewer import ViewerWidget
from odw.ui.workers import WorkerSignals, run_in_pool

_BROWSER_PAGE = 0
_VIEWER_PAGE = 1
_REFRESH_DELAY_MS = 500


class MainWindow(QMainWindow):
    """Top-level window wiring store, storage SCP, browser, viewer and dialogs."""

    def __init__(self, config: AppConfig, config_path: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle(self.tr("Open DICOM Workstation"))
        self._config = config
        self._config_path = config_path
        # Active worker signals are kept on self so they are not garbage collected.
        self._load_signals: WorkerSignals | None = None

        self._store = DicomStore(config.storage_dir)

        self._browser = StudyBrowser(self._store)
        self._viewer = ViewerWidget()
        self._stacked = QStackedWidget(self)
        self._stacked.addWidget(self._browser)
        self._stacked.addWidget(self._viewer)
        self.setCentralWidget(self._stacked)
        self._browser.series_activated.connect(self._open_series)

        # Coalesce bursts of stored instances into one browser refresh.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(_REFRESH_DELAY_MS)
        self._refresh_timer.timeout.connect(self._browser.refresh)

        self._bridge = ScpBridge(self)
        self._bridge.instance_stored.connect(self._on_instance_stored)
        self._scp = StorageScp(
            config.local_ae_title,
            config.listen_port,
            self._store,
            on_instance=self._bridge.notify,
        )
        self._scp.start()

        toolbar = self.addToolBar(self.tr("Main"))
        toolbar.setObjectName("main_toolbar")
        self.action_query = toolbar.addAction(self.tr("Query PACS…"), self._open_query_dialog)
        self.action_query.setObjectName("action_query")
        self.action_settings = toolbar.addAction(self.tr("Settings…"), self._open_settings_dialog)
        self.action_settings.setObjectName("action_settings")
        self.action_back = toolbar.addAction(self.tr("Back to studies"), self._show_browser)
        self.action_back.setObjectName("action_back")
        self.action_back.setVisible(False)

        self.statusBar()

    # -- read-only state for tests / callers -----------------------------------

    @property
    def browser(self) -> StudyBrowser:
        return self._browser

    @property
    def viewer(self) -> ViewerWidget:
        return self._viewer

    @property
    def stacked(self) -> QStackedWidget:
        return self._stacked

    @property
    def scp(self) -> StorageScp:
        return self._scp

    @property
    def store(self) -> DicomStore:
        return self._store

    # -- SCP ingest -> throttled browser refresh -------------------------------

    def _on_instance_stored(self, _record: object) -> None:
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    # -- page switching ----------------------------------------------------------

    def _open_series(self, series_uid: str) -> None:
        signals = run_in_pool(self._store.load_series_datasets, series_uid)
        signals.result.connect(self._show_series)
        signals.error.connect(self.statusBar().showMessage)
        self._load_signals = signals

    def _show_series(self, datasets: list[Dataset]) -> None:
        self._viewer.load_series(datasets)
        self._stacked.setCurrentIndex(_VIEWER_PAGE)
        self.action_back.setVisible(True)

    def _show_browser(self) -> None:
        self._stacked.setCurrentIndex(_BROWSER_PAGE)
        self.action_back.setVisible(False)

    # -- dialogs -------------------------------------------------------------------

    def _open_query_dialog(self) -> None:
        dialog = QueryDialog(self._config, self._store, self)
        dialog.study_retrieved.connect(lambda _uid: self._browser.refresh())
        dialog.exec()

    def _open_settings_dialog(self) -> None:
        dialog = SettingsDialog(self._config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            save_config(dialog.result_config(), self._config_path)
            self.statusBar().showMessage(self.tr("Restart to apply network settings"))

    # -- lifecycle -------------------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        self._scp.stop()
        self._store.close()
        super().closeEvent(event)
