"""Dialog for viewing and editing the viewer keyboard shortcuts."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from odw.core.config import DEFAULT_VIEWER_SHORTCUTS


class ShortcutsDialog(QDialog):
    """Edit the viewer shortcuts; read the result via :meth:`result_shortcuts`."""

    def __init__(self, shortcuts: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Edit shortcuts"))
        self.setModal(True)

        labels = {
            "window": self.tr("Windowing"),
            "zoom": self.tr("Zoom"),
            "length": self.tr("Measure length"),
            "polygon": self.tr("Polygon ROI"),
            "ellipse": self.tr("Ellipse ROI"),
            "reset": self.tr("Reset view"),
        }
        self._edits: dict[str, QLineEdit] = {}
        form = QFormLayout()
        for action, default_key in DEFAULT_VIEWER_SHORTCUTS.items():
            edit = QLineEdit(shortcuts.get(action, default_key), self)
            edit.setObjectName(f"edit_{action}")
            edit.setMaxLength(1)
            form.addRow(labels.get(action, action), edit)
            self._edits[action] = edit

        self.error_label = QLabel("", self)
        self.error_label.setObjectName("error_label")

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(self.button_box)

    def result_shortcuts(self) -> dict[str, str]:
        """The edited shortcuts, with keys normalized to uppercase."""
        return {action: edit.text().strip().upper() for action, edit in self._edits.items()}

    def _on_accept(self) -> None:
        shortcuts = self.result_shortcuts()
        if any(not self._is_letter(key) for key in shortcuts.values()):
            self.error_label.setText(
                self.tr(
                    "Each shortcut must be a single letter A-Z "
                    "(digits are reserved for window presets)"
                )
            )
            return
        if len(set(shortcuts.values())) != len(shortcuts):
            self.error_label.setText(self.tr("The same key is assigned to more than one action"))
            return
        self.accept()

    @staticmethod
    def _is_letter(key: str) -> bool:
        return len(key) == 1 and "A" <= key <= "Z"
