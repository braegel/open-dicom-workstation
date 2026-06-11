"""Tests for the slice viewer widget: scroll, window/level, zoom, pan, reset."""

import gc

import pytest
from pydicom.uid import generate_uid
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication
from tests.support.factory import make_ct_dataset

from odw.ui.viewer import ViewerWidget


def make_distinct_series(n: int = 5) -> list:
    """Series of *n* slices whose pixel values differ per slice."""
    study_uid = generate_uid()
    series_uid = generate_uid()
    return [
        make_ct_dataset(
            study_uid=study_uid,
            series_uid=series_uid,
            instance_number=i,
            pixel_fill=(i - 1) * 100,
            # Wide window covering all slice values (-1024..-624 HU) so each
            # slice renders to a distinct gray level.
            window_center=-800.0,
            window_width=1000.0,
        )
        for i in range(1, n + 1)
    ]


@pytest.fixture
def viewer(qtbot):
    widget = ViewerWidget()
    qtbot.addWidget(widget)
    widget.resize(256, 256)
    widget.show()
    return widget


def send_wheel(widget, delta_y: int) -> None:
    pos = QPointF(widget.width() / 2, widget.height() / 2)
    event = QWheelEvent(
        pos,
        widget.mapToGlobal(pos.toPoint()).toPointF(),
        QPoint(),
        QPoint(0, delta_y),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(widget, event)


def center_pixel(widget) -> int:
    image = widget.grab().toImage()
    assert not image.isNull()
    return image.pixelColor(image.width() // 2, image.height() // 2).red()


def test_load_series_shows_first_slice(viewer):
    viewer.load_series(make_distinct_series())
    assert viewer.current_index == 0
    first = center_pixel(viewer)
    send_wheel(viewer, -120)  # next slice has different pixel_fill
    second = center_pixel(viewer)
    assert first != second


def test_wheel_changes_slice_and_clamps(viewer):
    viewer.load_series(make_distinct_series())
    send_wheel(viewer, -120)
    assert viewer.current_index == 1
    send_wheel(viewer, 120)
    send_wheel(viewer, 120)
    assert viewer.current_index == 0  # clamped at first slice
    for _ in range(10):
        send_wheel(viewer, -120)
    assert viewer.current_index == 4  # clamped at last slice


def test_unsorted_series_sorted_by_instance_number(viewer):
    study_uid = generate_uid()
    series_uid = generate_uid()
    datasets = [
        make_ct_dataset(
            study_uid=study_uid,
            series_uid=series_uid,
            instance_number=i,
            pixel_fill=i * 100,
        )
        for i in (3, 1, 2)
    ]
    viewer.load_series(datasets)
    assert viewer.current_index == 0
    assert int(viewer.current_dataset.InstanceNumber) == 1


def test_left_drag_changes_window(viewer, qtbot):
    viewer.load_series(make_distinct_series())
    center0 = viewer.window_center
    width0 = viewer.window_width
    pos = QPoint(viewer.width() // 2, viewer.height() // 2)
    qtbot.mousePress(viewer, Qt.LeftButton, pos=pos)
    qtbot.mouseMove(viewer, pos + QPoint(20, 15))
    qtbot.mouseRelease(viewer, Qt.LeftButton, pos=pos + QPoint(20, 15))
    assert viewer.window_width > width0  # dx > 0 widens the window
    assert viewer.window_center > center0  # dy > 0 (drag down) raises center


def test_window_change_alters_rendered_pixel(viewer):
    viewer.load_series(make_distinct_series())
    before = center_pixel(viewer)
    # Slice 0 modality value is -1024 HU; window it so that value maps bright.
    viewer.set_window(-2000.0, 100.0)
    after = center_pixel(viewer)
    assert before != after


def test_reset_restores_default_window(viewer, qtbot):
    viewer.load_series(make_distinct_series())
    default_center = viewer.window_center
    default_width = viewer.window_width
    viewer.set_window(-2000.0, 100.0)
    assert (viewer.window_center, viewer.window_width) != (default_center, default_width)
    qtbot.keyClick(viewer, Qt.Key_R)
    assert viewer.window_center == default_center
    assert viewer.window_width == default_width
    assert viewer.zoom == 1.0


def test_render_keeps_buffer_alive(viewer):
    viewer.load_series(make_distinct_series())
    first = viewer.grab().toImage()
    gc.collect()
    second = viewer.grab().toImage()
    assert not second.isNull()
    assert first == second
