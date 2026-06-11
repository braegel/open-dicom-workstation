"""Query/retrieve dialog: C-FIND a PACS node, retrieve studies via C-GET or C-MOVE."""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

from odw.core.config import AppConfig
from odw.core.models import PacsNode, RetrieveResult, StudyQueryResult
from odw.core.net.query import QueryScu
from odw.core.net.retrieve import RetrieveScu
from odw.core.storage import DicomStore
from odw.ui.workers import run_in_pool


class QueryResultsModel(QAbstractTableModel):
    """Read-only table of C-FIND study results."""

    COLUMNS = (
        "patient_name",
        "patient_id",
        "study_date",
        "description",
        "modalities",
        "num_instances",
    )

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._results: list[StudyQueryResult] = []

    def set_results(self, results: list[StudyQueryResult]) -> None:
        self.beginResetModel()
        self._results = list(results)
        self.endResetModel()

    def study_at(self, row: int) -> StudyQueryResult:
        return self._results[row]

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._results)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        value = getattr(self._results[index.row()], self.COLUMNS[index.column()])
        return "" if value is None else str(value)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            headers = (
                self.tr("Patient Name"),
                self.tr("Patient ID"),
                self.tr("Study Date"),
                self.tr("Description"),
                self.tr("Modalities"),
                self.tr("Images"),
            )
            return headers[section]
        return None


class QueryDialog(QDialog):
    """Search a configured PACS node and retrieve selected studies into the local store."""

    study_retrieved = Signal(str)

    def __init__(self, config: AppConfig, store: DicomStore, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Query PACS"))
        self._config = config
        self._store = store
        # Active worker signals are kept on self so they are not garbage collected.
        self._active_signals = None

        self.node_combo = QComboBox(self)
        self.node_combo.setObjectName("node_combo")
        for node in config.nodes:
            self.node_combo.addItem(node.name, node)

        self.patient_name_edit = QLineEdit(self)
        self.patient_name_edit.setObjectName("patient_name_edit")
        self.study_date_edit = QLineEdit(self)
        self.study_date_edit.setObjectName("study_date_edit")
        self.study_date_edit.setPlaceholderText(self.tr("YYYYMMDD or range, optional"))

        self.search_button = QPushButton(self.tr("Search"), self)
        self.search_button.setObjectName("search_button")

        self.results_model = QueryResultsModel(self)
        self.results_view = QTableView(self)
        self.results_view.setObjectName("results_view")
        self.results_view.setModel(self.results_model)
        self.results_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_view.setSelectionMode(QAbstractItemView.SingleSelection)

        self.get_button = QPushButton(self.tr("Retrieve (C-GET)"), self)
        self.get_button.setObjectName("get_button")
        self.move_button = QPushButton(self.tr("Retrieve (C-MOVE)"), self)
        self.move_button.setObjectName("move_button")

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setObjectName("progress_bar")
        self.progress_bar.hide()
        self.status_label = QLabel(self)
        self.status_label.setObjectName("status_label")

        form = QFormLayout()
        form.addRow(self.tr("PACS node"), self.node_combo)
        form.addRow(self.tr("Patient name"), self.patient_name_edit)
        form.addRow(self.tr("Study date"), self.study_date_edit)

        buttons = QHBoxLayout()
        buttons.addWidget(self.search_button)
        buttons.addStretch()
        buttons.addWidget(self.get_button)
        buttons.addWidget(self.move_button)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.results_view)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)

        self.search_button.clicked.connect(self._on_search)
        self.get_button.clicked.connect(self._on_get)
        self.move_button.clicked.connect(self._on_move)

    # -- helpers ---------------------------------------------------------------

    def _current_node(self) -> PacsNode | None:
        node = self.node_combo.currentData()
        if node is None:
            self.status_label.setText(self.tr("No PACS node configured"))
        return node

    def _selected_study(self) -> StudyQueryResult | None:
        rows = self.results_view.selectionModel().selectedRows()
        if not rows:
            self.status_label.setText(self.tr("Select a study first"))
            return None
        return self.results_model.study_at(rows[0].row())

    def _set_busy(self, busy: bool) -> None:
        for button in (self.search_button, self.get_button, self.move_button):
            button.setEnabled(not busy)

    def _start(self, signals) -> None:
        signals.error.connect(self.status_label.setText)
        signals.finished.connect(self._on_finished)
        self._active_signals = signals

    def _on_finished(self) -> None:
        self._set_busy(False)
        self.progress_bar.hide()

    # -- search ------------------------------------------------------------------

    def _on_search(self) -> None:
        node = self._current_node()
        if node is None:
            return
        self._set_busy(True)
        self.status_label.setText("")
        scu = QueryScu(self._config.local_ae_title, node)
        signals = run_in_pool(
            scu.find_studies,
            patient_name=self.patient_name_edit.text().strip(),
            study_date=self.study_date_edit.text().strip(),
        )
        signals.result.connect(self._on_search_result)
        self._start(signals)

    def _on_search_result(self, results: list[StudyQueryResult]) -> None:
        self.results_model.set_results(results)
        self.status_label.setText(self.tr("Found {n} studies").format(n=len(results)))

    # -- retrieve ----------------------------------------------------------------

    def _on_get(self) -> None:
        node = self._current_node()
        study = self._selected_study()
        if node is None or study is None:
            return
        scu = RetrieveScu(self._config.local_ae_title, node)
        self._start_retrieve(
            run_in_pool(scu.get_study, study.study_uid, self._store, forward_progress=True),
            study.study_uid,
        )

    def _on_move(self) -> None:
        node = self._current_node()
        study = self._selected_study()
        if node is None or study is None:
            return
        scu = RetrieveScu(self._config.local_ae_title, node)
        self._start_retrieve(
            run_in_pool(
                scu.move_study,
                study.study_uid,
                self._config.local_ae_title,
                forward_progress=True,
            ),
            study.study_uid,
        )

    def _start_retrieve(self, signals, study_uid: str) -> None:
        self._set_busy(True)
        self.status_label.setText("")
        self.progress_bar.setRange(0, 0)  # busy until first progress report
        self.progress_bar.show()
        signals.progress.connect(self._on_progress)
        signals.result.connect(lambda result, uid=study_uid: self._on_retrieve_result(uid, result))
        self._start(signals)

    def _on_progress(self, completed: int, remaining: int) -> None:
        total = completed + remaining
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(completed)
        else:
            self.progress_bar.setRange(0, 0)

    def _on_retrieve_result(self, study_uid: str, result: RetrieveResult) -> None:
        self.status_label.setText(self.tr("Retrieved {n} instances").format(n=result.completed))
        self.study_retrieved.emit(study_uid)
