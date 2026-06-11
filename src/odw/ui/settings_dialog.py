"""Settings dialog: local AE, listen port, storage directory and PACS nodes."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from odw.core.config import RETRIEVE_METHODS, AppConfig
from odw.core.models import PacsNode
from odw.core.transfer import DEFAULT_TRANSFER_SYNTAXES, TRANSFER_SYNTAXES

_NODE_TEXT_COLUMNS = 4
_NODE_COLUMNS = 5
_RETRIEVE_COLUMN = 4
_DEFAULT_NODE_PORT = "104"


class SettingsDialog(QDialog):
    """Edit the application configuration; read the result via :meth:`result_config`."""

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Settings"))

        self.aet_edit = QLineEdit(config.local_ae_title, self)
        self.aet_edit.setObjectName("aet_edit")

        self.port_spin = QSpinBox(self)
        self.port_spin.setObjectName("port_spin")
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(max(config.listen_port, 1))

        self.storage_dir_edit = QLineEdit(str(config.storage_dir), self)
        self.storage_dir_edit.setObjectName("storage_dir_edit")
        self.browse_button = QPushButton(self.tr("Browse…"), self)
        self.browse_button.setObjectName("browse_button")
        self.browse_button.clicked.connect(self._on_browse)

        self.nodes_table = QTableWidget(0, _NODE_COLUMNS, self)
        self.nodes_table.setObjectName("nodes_table")
        self.nodes_table.setHorizontalHeaderLabels(
            (
                self.tr("Name"),
                self.tr("AE Title"),
                self.tr("Host"),
                self.tr("Port"),
                self.tr("Retrieve"),
            )
        )
        for node in config.nodes:
            self._append_node_row(node)

        self.add_node_button = QPushButton(self.tr("Add node"), self)
        self.add_node_button.setObjectName("add_node_button")
        self.add_node_button.clicked.connect(lambda: self._append_node_row(None))
        self.remove_node_button = QPushButton(self.tr("Remove node"), self)
        self.remove_node_button.setObjectName("remove_node_button")
        self.remove_node_button.clicked.connect(self._on_remove_node)

        self.syntax_list = QListWidget(self)
        self.syntax_list.setObjectName("syntax_list")
        for uid, name in TRANSFER_SYNTAXES.items():
            item = QListWidgetItem(name, self.syntax_list)
            item.setData(Qt.ItemDataRole.UserRole, uid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if uid in config.transfer_syntaxes
                else Qt.CheckState.Unchecked
            )
        self.syntax_group = QGroupBox(self.tr("Transfer syntaxes"), self)
        self.syntax_group.setObjectName("syntax_group")
        syntax_layout = QVBoxLayout(self.syntax_group)
        syntax_layout.addWidget(self.syntax_list)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)

        storage_row = QHBoxLayout()
        storage_row.addWidget(self.storage_dir_edit)
        storage_row.addWidget(self.browse_button)

        form = QFormLayout()
        form.addRow(self.tr("Local AE title"), self.aet_edit)
        form.addRow(self.tr("Listen port"), self.port_spin)
        form.addRow(self.tr("Storage directory"), storage_row)

        node_buttons = QHBoxLayout()
        node_buttons.addWidget(self.add_node_button)
        node_buttons.addWidget(self.remove_node_button)
        node_buttons.addStretch()

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.nodes_table)
        layout.addLayout(node_buttons)
        layout.addWidget(self.syntax_group)
        layout.addWidget(self.button_box)

    def _append_node_row(self, node: PacsNode | None) -> None:
        row = self.nodes_table.rowCount()
        self.nodes_table.insertRow(row)
        values = (
            ("", "", "", _DEFAULT_NODE_PORT)
            if node is None
            else (node.name, node.ae_title, node.host, str(node.port))
        )
        for col, value in enumerate(values):
            self.nodes_table.setItem(row, col, QTableWidgetItem(value))
        combo = QComboBox(self.nodes_table)
        combo.addItems(RETRIEVE_METHODS)
        combo.setCurrentText(node.retrieve_method if node is not None else RETRIEVE_METHODS[0])
        self.nodes_table.setCellWidget(row, _RETRIEVE_COLUMN, combo)

    def _on_remove_node(self) -> None:
        row = self.nodes_table.currentRow()
        if row >= 0:
            self.nodes_table.removeRow(row)

    def _on_browse(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, self.tr("Choose storage directory"), self.storage_dir_edit.text()
        )
        if directory:
            self.storage_dir_edit.setText(directory)

    def result_config(self) -> AppConfig:
        """Build a new :class:`AppConfig` from the current widget state."""
        nodes: list[PacsNode] = []
        for row in range(self.nodes_table.rowCount()):
            name, ae_title, host, port_text = (
                self._cell_text(row, col) for col in range(_NODE_TEXT_COLUMNS)
            )
            if not (name or ae_title or host):
                continue  # skip rows left entirely empty
            if not (port_text.isdigit() and 1 <= int(port_text) <= 65535):
                continue
            nodes.append(
                PacsNode(
                    name=name,
                    ae_title=ae_title,
                    host=host,
                    port=int(port_text),
                    retrieve_method=self._retrieve_method(row),
                )
            )
        return AppConfig(
            local_ae_title=self.aet_edit.text().strip(),
            listen_port=self.port_spin.value(),
            storage_dir=Path(self.storage_dir_edit.text().strip()),
            nodes=nodes,
            transfer_syntaxes=self._checked_syntaxes(),
        )

    def _retrieve_method(self, row: int) -> str:
        combo = self.nodes_table.cellWidget(row, _RETRIEVE_COLUMN)
        if isinstance(combo, QComboBox):
            return combo.currentText()
        return RETRIEVE_METHODS[0]

    def _checked_syntaxes(self) -> list[str]:
        """Checked transfer syntax UIDs in catalog order; defaults if none is checked."""
        checked = [
            self.syntax_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.syntax_list.count())
            if self.syntax_list.item(i).checkState() == Qt.CheckState.Checked
        ]
        return checked if checked else list(DEFAULT_TRANSFER_SYNTAXES)

    def _cell_text(self, row: int, col: int) -> str:
        item = self.nodes_table.item(row, col)
        return item.text().strip() if item is not None else ""
