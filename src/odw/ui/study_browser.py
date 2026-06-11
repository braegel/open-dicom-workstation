"""Study browser: table of local studies plus the series of the selected study."""

from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    Qt,
    Signal,
)
from PySide6.QtWidgets import QAbstractItemView, QTableView, QVBoxLayout, QWidget

from odw.core.models import SeriesRecord, StudyRecord
from odw.core.storage import DicomStore


def _format_study_date(raw: str) -> str:
    """Render a DICOM DA string like ``20260101`` as ``2026-01-01``."""
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return raw


class StudyTableModel(QAbstractTableModel):
    """Read-only table of the studies in a :class:`DicomStore`."""

    COLUMNS = ("patient_name", "patient_id", "study_date", "description", "modalities")

    def __init__(self, store: DicomStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._studies: list[StudyRecord] = store.studies()

    def refresh(self) -> None:
        self.beginResetModel()
        self._studies = self._store.studies()
        self.endResetModel()

    def study_at(self, row: int) -> StudyRecord:
        return self._studies[row]

    def rowCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),  # noqa: B008
    ) -> int:
        return 0 if parent.isValid() else len(self._studies)

    def columnCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),  # noqa: B008
    ) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        value = getattr(self._studies[index.row()], self.COLUMNS[index.column()])
        if self.COLUMNS[index.column()] == "study_date":
            return _format_study_date(value)
        return value

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            headers = (
                self.tr("Patient Name"),
                self.tr("Patient ID"),
                self.tr("Study Date"),
                self.tr("Description"),
                self.tr("Modalities"),
            )
            return headers[section]
        return None


class SeriesTableModel(QAbstractTableModel):
    """Read-only table of the series belonging to one study."""

    COLUMNS = ("series_number", "modality", "description", "num_instances")

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._series: list[SeriesRecord] = []

    def set_series(self, series: list[SeriesRecord]) -> None:
        self.beginResetModel()
        self._series = list(series)
        self.endResetModel()

    def series_at(self, row: int) -> SeriesRecord:
        return self._series[row]

    def rowCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),  # noqa: B008
    ) -> int:
        return 0 if parent.isValid() else len(self._series)

    def columnCount(
        self,
        parent: QModelIndex | QPersistentModelIndex = QModelIndex(),  # noqa: B008
    ) -> int:
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        value = getattr(self._series[index.row()], self.COLUMNS[index.column()])
        return "" if value is None else str(value)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            headers = (
                self.tr("Series #"),
                self.tr("Modality"),
                self.tr("Description"),
                self.tr("Images"),
            )
            return headers[section]
        return None


def _configure_view(view: QTableView) -> None:
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setSortingEnabled(False)


class StudyBrowser(QWidget):
    """Browse local studies; double-clicking a series emits ``series_activated``."""

    series_activated = Signal(str)

    def __init__(self, store: DicomStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = store

        self._study_model = StudyTableModel(store, self)
        self._series_model = SeriesTableModel(self)

        self.studies_view = QTableView(self)
        self.studies_view.setModel(self._study_model)
        _configure_view(self.studies_view)

        self.series_view = QTableView(self)
        self.series_view.setModel(self._series_model)
        _configure_view(self.series_view)

        layout = QVBoxLayout(self)
        layout.addWidget(self.studies_view)
        layout.addWidget(self.series_view)

        self.studies_view.selectionModel().currentRowChanged.connect(self._on_study_selected)
        self.series_view.activated.connect(self._on_series_activated)

    def refresh(self) -> None:
        self._study_model.refresh()
        self._series_model.set_series([])

    def _on_study_selected(self, current: QModelIndex, _previous: QModelIndex) -> None:
        if not current.isValid():
            self._series_model.set_series([])
            return
        study = self._study_model.study_at(current.row())
        self._series_model.set_series(self._store.series_for_study(study.study_uid))

    def _on_series_activated(self, index: QModelIndex) -> None:
        if index.isValid():
            self.series_activated.emit(self._series_model.series_at(index.row()).series_uid)
