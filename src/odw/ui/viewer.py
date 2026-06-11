"""Slice viewer widget: mouse-driven scroll, window/level, zoom and pan."""

import math

import numpy as np
import numpy.typing as npt
from pydicom.dataset import Dataset
from PySide6.QtCore import QPoint, QPointF, Qt, Signal
from PySide6.QtGui import (
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from odw.core.imaging import default_window, render_frame

ZOOM_MIN = 0.1
ZOOM_MAX = 32.0
WIDTH_GAIN = 2.0
CENTER_GAIN = 2.0
ZOOM_GAIN = 0.005


class ViewerWidget(QWidget):
    """Renders one slice of a DICOM series; mouse-driven scroll/window/zoom/pan."""

    view_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(False)
        self.setMinimumSize(256, 256)

        self._datasets: list[Dataset] = []
        self._index = 0
        self._center = 0.0
        self._width = 1.0
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)

        self._drag_button: Qt.MouseButton | None = None
        self._drag_pos = QPointF()

        # Rendering cache; the numpy buffer MUST stay referenced because
        # QImage wraps it without copying.
        self._frame_buffer: npt.NDArray[np.uint8] | None = None
        self._frame_image: QImage | None = None
        self._cache_key: tuple[int, float, float] | None = None
        self._render_error: str | None = None

    # -- read-only state for tests / parent widgets ---------------------------

    @property
    def current_index(self) -> int:
        return self._index

    @property
    def current_dataset(self) -> Dataset | None:
        return self._datasets[self._index] if self._datasets else None

    @property
    def window_center(self) -> float:
        return self._center

    @property
    def window_width(self) -> float:
        return self._width

    @property
    def zoom(self) -> float:
        return self._zoom

    # -- public API ------------------------------------------------------------

    def load_series(self, datasets: list[Dataset]) -> None:
        """Load a series, sorted by InstanceNumber (missing treated as 0)."""
        self._datasets = sorted(datasets, key=lambda ds: int(getattr(ds, "InstanceNumber", 0) or 0))
        self._index = 0
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        if self._datasets:
            self._center, self._width = self._safe_default_window(self._datasets[0])
        self._invalidate_cache()
        self.update()
        self.view_changed.emit()

    def set_window(self, center: float, width: float) -> None:
        self._center = float(center)
        self._width = max(float(width), 1.0)
        self.update()
        self.view_changed.emit()

    def reset_view(self) -> None:
        """Restore the dataset's default window, zoom 1.0 and no pan."""
        ds = self.current_dataset
        if ds is not None:
            self._center, self._width = self._safe_default_window(ds)
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()
        self.view_changed.emit()

    @staticmethod
    def _safe_default_window(ds: Dataset) -> tuple[float, float]:
        """default_window may decode pixel data, which can fail on bad datasets."""
        try:
            return default_window(ds)
        except Exception:
            return (0.0, 1.0)

    # -- event handlers ----------------------------------------------------------

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not self._datasets:
            return
        delta = event.angleDelta().y()
        if delta < 0:
            new_index = min(self._index + 1, len(self._datasets) - 1)
        elif delta > 0:
            new_index = max(self._index - 1, 0)
        else:
            return
        if new_index != self._index:
            self._index = new_index
            self.update()
        self.view_changed.emit()
        event.accept()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() in (
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.RightButton,
            Qt.MouseButton.MiddleButton,
        ):
            self._drag_button = event.button()
            self._drag_pos = event.position()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_button is None:
            super().mouseMoveEvent(event)
            return
        delta = event.position() - self._drag_pos
        self._drag_pos = event.position()
        if self._drag_button == Qt.MouseButton.LeftButton:
            self._width = max(self._width + delta.x() * WIDTH_GAIN, 1.0)
            self._center += delta.y() * CENTER_GAIN
            self.update()
            self.view_changed.emit()
        elif self._drag_button == Qt.MouseButton.RightButton:
            self._zoom = min(max(self._zoom * math.exp(-delta.y() * ZOOM_GAIN), ZOOM_MIN), ZOOM_MAX)
            self.update()
        elif self._drag_button == Qt.MouseButton.MiddleButton:
            self._pan += delta
            self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == self._drag_button:
            self._drag_button = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.reset_view()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_R:
            self.reset_view()
            event.accept()
        else:
            super().keyPressEvent(event)

    # -- painting -------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)

        if not self._datasets:
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.tr("No series loaded"))
            return

        image = self._current_image()
        if image is None:
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                self._render_error or self.tr("Unable to render image"),
            )
            return

        painter.translate(self.width() / 2 + self._pan.x(), self.height() / 2 + self._pan.y())
        painter.scale(self._zoom, self._zoom)
        painter.drawImage(QPoint(-image.width() // 2, -image.height() // 2), image)

    def _invalidate_cache(self) -> None:
        self._cache_key = None
        self._frame_buffer = None
        self._frame_image = None
        self._render_error = None

    def _current_image(self) -> QImage | None:
        key = (self._index, self._center, self._width)
        if key == self._cache_key:
            return self._frame_image
        self._cache_key = key
        self._render_error = None
        try:
            frame = render_frame(self._datasets[self._index], self._center, self._width)
        except Exception as exc:
            # paintEvent must never raise: an escaping exception leaves the
            # QPainter active and crashes Qt on the next backing-store flush.
            self._frame_buffer = None
            self._frame_image = None
            self._render_error = str(exc)
            return None
        # Keep the numpy array alive: QImage does not copy the buffer.
        self._frame_buffer = frame
        height, width = frame.shape
        self._frame_image = QImage(
            frame.data, width, height, width, QImage.Format.Format_Grayscale8
        )
        return self._frame_image
