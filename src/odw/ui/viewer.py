"""Slice viewer widget: scroll, window/level, zoom, pan, cine and measurements.

Left button drives the active tool (window/zoom/length/polygon/ellipse),
the right button auto-plays through the stack (cine), the middle button pans.
"""

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from pydicom.dataset import Dataset
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from odw.core.config import DEFAULT_VIEWER_SHORTCUTS
from odw.core.imaging import default_window, modality_values, render_frame
from odw.core.measure import ellipse_mask, length_label, polygon_mask, roi_stats
from odw.core.presets import WindowPreset, preset_for_key

ZOOM_MIN = 0.1
ZOOM_MAX = 32.0
WIDTH_GAIN = 2.0
CENTER_GAIN = 2.0
ZOOM_GAIN = 0.005

CINE_TICK_MS = 33
CINE_BASE_SPEED = 10.0  # slices/s on right press, before any drag
CINE_SPEED_GAIN = 0.3  # slices/s per pixel of vertical drag (up = faster)
CINE_SPEED_MAX = 60.0

OVERLAY_COLOR = QColor(255, 220, 60)  # yellow
LABEL_OFFSET = QPointF(4.0, -4.0)

TOOLS: tuple[str, ...] = ("window", "zoom", "length", "polygon", "ellipse")
_SHORTCUT_ACTIONS: tuple[str, ...] = TOOLS + ("reset",)


@dataclass
class Measurement:
    """A finalized measurement on one slice, in image pixel coordinates."""

    kind: str  # "length" | "polygon" | "ellipse"
    points: list[tuple[float, float]]
    label: str


class ViewerWidget(QWidget):
    """Renders one slice of a DICOM series; mouse-driven scroll/window/zoom/pan,
    right-button cine and left-button measurement tools."""

    view_changed = Signal()
    tool_changed = Signal(str)

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

        self._tool: str = "window"
        self._shortcuts: dict[str, str] = dict(DEFAULT_VIEWER_SHORTCUTS)
        self._measurements: dict[int, list[Measurement]] = {}
        self._poly_vertices: list[tuple[float, float]] = []
        self._shape_start: tuple[float, float] | None = None  # length/ellipse anchor
        self._shape_current: tuple[float, float] | None = None

        self._cine_timer = QTimer(self)
        self._cine_timer.setInterval(CINE_TICK_MS)
        self._cine_timer.timeout.connect(self._cine_tick)
        self._cine_origin_y = 0.0
        self._cine_speed = CINE_BASE_SPEED
        self._cine_pos = 0.0  # fractional slice position accumulator

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

    @property
    def active_tool(self) -> str:
        return self._tool

    @property
    def measurements(self) -> list[Measurement]:
        """Finalized measurements of the CURRENT slice."""
        return list(self._measurements.get(self._index, []))

    # -- public API ------------------------------------------------------------

    def load_series(self, datasets: list[Dataset]) -> None:
        """Load a series, sorted by InstanceNumber (missing treated as 0)."""
        self._cine_timer.stop()
        self._datasets = sorted(datasets, key=lambda ds: int(getattr(ds, "InstanceNumber", 0) or 0))
        self._index = 0
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self._measurements = {}
        self._cancel_in_progress()
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

    def apply_preset(self, preset: WindowPreset) -> None:
        """Apply a built-in window preset (also bound to the digit keys 1-9)."""
        self.set_window(preset.center, preset.width)

    def reset_view(self) -> None:
        """Restore the dataset's default window, zoom 1.0 and no pan."""
        ds = self.current_dataset
        if ds is not None:
            self._center, self._width = self._safe_default_window(ds)
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()
        self.view_changed.emit()

    def set_tool(self, tool: str) -> None:
        """Select the left-button tool; raises ValueError on an unknown name."""
        if tool not in TOOLS:
            raise ValueError(f"unknown tool {tool!r}; expected one of {TOOLS}")
        self._tool = tool
        self._cancel_in_progress()
        self.update()
        self.tool_changed.emit(tool)

    def set_shortcuts(self, mapping: dict[str, str]) -> None:
        """Override tool/reset key bindings; keys are single letters (case-insensitive)."""
        normalized: dict[str, str] = {}
        for action, key in mapping.items():
            if action not in _SHORTCUT_ACTIONS:
                raise ValueError(
                    f"unknown shortcut action {action!r}; expected one of {_SHORTCUT_ACTIONS}"
                )
            letter = key.strip().upper()
            if len(letter) != 1:
                raise ValueError(f"shortcut for {action!r} must be a single letter, got {key!r}")
            normalized[action] = letter
        self._shortcuts.update(normalized)

    # -- coordinate helpers ------------------------------------------------------

    def widget_to_image(self, pos: QPointF) -> tuple[float, float]:
        """Widget-space position to image pixel coordinates (x=column, y=row)."""
        cols, rows = self._image_dims()
        x = (pos.x() - (self.width() / 2 + self._pan.x())) / self._zoom + cols // 2
        y = (pos.y() - (self.height() / 2 + self._pan.y())) / self._zoom + rows // 2
        return (x, y)

    def image_to_widget(self, point: tuple[float, float]) -> QPointF:
        """Image pixel coordinates to widget-space position (inverse of widget_to_image)."""
        cols, rows = self._image_dims()
        x = (point[0] - cols // 2) * self._zoom + self.width() / 2 + self._pan.x()
        y = (point[1] - rows // 2) * self._zoom + self.height() / 2 + self._pan.y()
        return QPointF(x, y)

    def _image_dims(self) -> tuple[int, int]:
        """(columns, rows) of the current dataset, (0, 0) when nothing is loaded."""
        ds = self.current_dataset
        if ds is None:
            return (0, 0)
        return (int(getattr(ds, "Columns", 0)), int(getattr(ds, "Rows", 0)))

    @staticmethod
    def _safe_default_window(ds: Dataset) -> tuple[float, float]:
        """default_window may decode pixel data, which can fail on bad datasets."""
        try:
            return default_window(ds)
        except Exception:
            return (0.0, 1.0)

    # -- cine ---------------------------------------------------------------------

    def _start_cine(self, pos: QPointF) -> None:
        if not self._datasets:
            return
        self._cine_origin_y = pos.y()
        self._cine_speed = CINE_BASE_SPEED
        self._cine_pos = float(self._index)
        self._cine_timer.start()

    def _cine_tick(self) -> None:
        n = len(self._datasets)
        if n == 0:
            self._cine_timer.stop()
            return
        step = self._cine_speed * (CINE_TICK_MS / 1000.0)
        self._cine_pos = (self._cine_pos + step) % n  # cine loop: wrap modulo len
        index = math.floor(self._cine_pos) % n
        if index != self._index:
            self._index = index
            self.update()
            self.view_changed.emit()

    # -- measurements ---------------------------------------------------------------

    def _cancel_in_progress(self) -> None:
        self._poly_vertices = []
        self._shape_start = None
        self._shape_current = None

    def _add_measurement(self, measurement: Measurement) -> None:
        self._measurements.setdefault(self._index, []).append(measurement)
        self.update()

    def _current_values(self) -> npt.NDArray[np.float32] | None:
        """Modality (e.g. HU) values of the current slice, None when undecodable."""
        ds = self.current_dataset
        if ds is None:
            return None
        try:
            return modality_values(ds)
        except Exception:
            return None

    @staticmethod
    def _roi_label(values: npt.NDArray[np.float32] | None, mask: npt.NDArray[np.bool_]) -> str:
        if values is None:
            return "empty ROI"
        stats = roi_stats(values, mask)
        if stats.count == 0:
            return "empty ROI"
        return f"Median {stats.median:.1f}  SD {stats.std:.1f}"

    def _finalize_length(self, end: tuple[float, float]) -> None:
        start = self._shape_start
        self._cancel_in_progress()
        ds = self.current_dataset
        if start is None or ds is None:
            return
        spacing = getattr(ds, "PixelSpacing", None)
        pixel_spacing = (float(spacing[0]), float(spacing[1])) if spacing is not None else None
        label = length_label(start, end, pixel_spacing)
        self._add_measurement(Measurement("length", [start, end], label))

    def _finalize_ellipse(self, end: tuple[float, float]) -> None:
        start = self._shape_start
        self._cancel_in_progress()
        if start is None or self.current_dataset is None:
            return
        center = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
        rx = abs(end[0] - start[0]) / 2.0
        ry = abs(end[1] - start[1]) / 2.0
        values = self._current_values()
        if values is None:
            label = "empty ROI"
        else:
            label = self._roi_label(values, ellipse_mask(values.shape, center, rx, ry))
        self._add_measurement(Measurement("ellipse", [start, end], label))

    def _close_polygon(self) -> None:
        vertices: list[tuple[float, float]] = []
        for vertex in self._poly_vertices:  # drop consecutive duplicates
            if not vertices or vertex != vertices[-1]:
                vertices.append(vertex)
        self._cancel_in_progress()
        self.update()
        if len(vertices) < 3 or self.current_dataset is None:
            return
        values = self._current_values()
        if values is None:
            label = "empty ROI"
        else:
            label = self._roi_label(values, polygon_mask(values.shape, vertices))
        self._add_measurement(Measurement("polygon", vertices, label))

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
        button = event.button()
        if button == Qt.MouseButton.RightButton:
            self._start_cine(event.position())
            event.accept()
            return
        if button == Qt.MouseButton.MiddleButton:
            self._drag_button = button
            self._drag_pos = event.position()
            event.accept()
            return
        if button == Qt.MouseButton.LeftButton:
            point = self.widget_to_image(event.position())
            if self._tool == "polygon":
                self._poly_vertices.append(point)
            else:
                self._drag_button = button
                self._drag_pos = event.position()
                if self._tool in ("length", "ellipse"):
                    self._shape_start = point
                    self._shape_current = point
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._cine_timer.isActive():
            # Vertical drag from the press point sets cine speed and direction.
            dy = event.position().y() - self._cine_origin_y
            speed = CINE_BASE_SPEED - dy * CINE_SPEED_GAIN
            self._cine_speed = min(max(speed, -CINE_SPEED_MAX), CINE_SPEED_MAX)
            event.accept()
            return
        if self._drag_button is None:
            super().mouseMoveEvent(event)
            return
        delta = event.position() - self._drag_pos
        self._drag_pos = event.position()
        if self._drag_button == Qt.MouseButton.LeftButton:
            if self._tool == "window":
                self._width = max(self._width + delta.x() * WIDTH_GAIN, 1.0)
                self._center += delta.y() * CENTER_GAIN
                self.update()
                self.view_changed.emit()
            elif self._tool == "zoom":
                zoom = self._zoom * math.exp(-delta.y() * ZOOM_GAIN)
                self._zoom = min(max(zoom, ZOOM_MIN), ZOOM_MAX)
                self.update()
            elif self._tool in ("length", "ellipse") and self._shape_start is not None:
                self._shape_current = self.widget_to_image(event.position())
                self.update()
        elif self._drag_button == Qt.MouseButton.MiddleButton:
            self._pan += delta
            self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton and self._cine_timer.isActive():
            self._cine_timer.stop()
            event.accept()
            return
        if event.button() == self._drag_button:
            self._drag_button = None
            end = self.widget_to_image(event.position())
            if self._tool == "length" and self._shape_start is not None:
                self._finalize_length(end)
            elif self._tool == "ellipse" and self._shape_start is not None:
                self._finalize_ellipse(end)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self._tool == "polygon":
            self._close_polygon()
        else:
            self.reset_view()
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        text = event.text()
        if len(text) == 1 and text in "123456789":
            preset = preset_for_key(text)
            if preset is not None:
                self.apply_preset(preset)
                event.accept()
                return
        if event.key() == Qt.Key.Key_Escape and self._poly_vertices:
            self._cancel_in_progress()
            self.update()
            event.accept()
            return
        key = text.upper()
        if key:
            for action, bound in self._shortcuts.items():
                if bound == key:
                    if action == "reset":
                        self.reset_view()
                    else:
                        self.set_tool(action)
                    event.accept()
                    return
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

        # Overlay shares the image transform so measurements stick to anatomy;
        # the pen is set AFTER the transform and cosmetic (1px at any zoom).
        painter.translate(-(image.width() // 2), -(image.height() // 2))
        pen = QPen(OVERLAY_COLOR)
        pen.setCosmetic(True)
        painter.setPen(pen)
        self._paint_overlay(painter)

    def _paint_overlay(self, painter: QPainter) -> None:
        for m in self._measurements.get(self._index, []):
            if m.kind == "length":
                p1, p2 = (QPointF(*p) for p in m.points)
                painter.drawLine(p1, p2)
                mid = QPointF((p1.x() + p2.x()) / 2.0, (p1.y() + p2.y()) / 2.0)
                painter.drawText(mid + LABEL_OFFSET, m.label)
            elif m.kind == "polygon":
                polygon = QPolygonF([QPointF(*p) for p in m.points])
                painter.drawPolygon(polygon)
                painter.drawText(QPointF(*m.points[0]) + LABEL_OFFSET, m.label)
            elif m.kind == "ellipse":
                rect = QRectF(QPointF(*m.points[0]), QPointF(*m.points[1])).normalized()
                painter.drawEllipse(rect)
                painter.drawText(rect.topLeft() + LABEL_OFFSET, m.label)

        # In-progress shapes.
        if len(self._poly_vertices) >= 2:
            painter.drawPolyline(QPolygonF([QPointF(*p) for p in self._poly_vertices]))
        if self._shape_start is not None and self._shape_current is not None:
            start = QPointF(*self._shape_start)
            current = QPointF(*self._shape_current)
            if self._tool == "length":
                painter.drawLine(start, current)
            elif self._tool == "ellipse":
                painter.drawEllipse(QRectF(start, current).normalized())

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
