"""Tests for the slice viewer widget: scroll, window/level, zoom, pan, reset,
tools (cine, zoom, length/ROI measurements) and window presets."""

import gc

import pytest
from pydicom.uid import generate_uid
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication
from tests.support.factory import make_ct_dataset, make_series

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


def test_undecodable_slice_paints_error_instead_of_crashing(qtbot):
    """A dataset whose pixel data cannot be decoded must never let an exception
    escape paintEvent — that leaves the QPainter active and segfaults Qt."""
    good = make_ct_dataset(rows=16, cols=16, instance_number=2)
    corrupt = make_ct_dataset(rows=16, cols=16, instance_number=1)
    corrupt.PixelData = corrupt.PixelData[:100]

    viewer = ViewerWidget()
    qtbot.addWidget(viewer)
    viewer.resize(256, 256)
    viewer.load_series([corrupt, good])

    image = viewer.grab().toImage()  # paints the corrupt slice
    assert not image.isNull()

    send_wheel(viewer, -120)  # move to the good slice
    assert viewer.current_index == 1
    assert not viewer.grab().toImage().isNull()


# -- tools: selection and shortcuts -------------------------------------------


def image_pos(viewer, x: float, y: float) -> QPoint:
    """Widget-space position of an image point, independent of zoom/pan."""
    return viewer.image_to_widget((x, y)).toPoint()


def left_drag(viewer, qtbot, start: QPoint, end: QPoint) -> None:
    qtbot.mousePress(viewer, Qt.LeftButton, pos=start)
    qtbot.mouseMove(viewer, end)
    qtbot.mouseRelease(viewer, Qt.LeftButton, pos=end)


def test_default_tool_is_window(viewer):
    viewer.load_series(make_distinct_series())
    assert viewer.active_tool == "window"


def test_keys_switch_tools(viewer, qtbot):
    viewer.load_series(make_distinct_series())
    seen: list[str] = []
    viewer.tool_changed.connect(seen.append)
    for key, tool in (
        ("Z", "zoom"),
        ("L", "length"),
        ("P", "polygon"),
        ("E", "ellipse"),
        ("W", "window"),
    ):
        qtbot.keyClicks(viewer, key)
        assert viewer.active_tool == tool
    assert seen == ["zoom", "length", "polygon", "ellipse", "window"]


def test_set_tool_rejects_unknown(viewer):
    with pytest.raises(ValueError):
        viewer.set_tool("rotate")


def test_zoom_tool_left_drag_zooms(viewer, qtbot):
    viewer.load_series(make_distinct_series())
    center0, width0 = viewer.window_center, viewer.window_width
    qtbot.keyClicks(viewer, "Z")
    pos = QPoint(viewer.width() // 2, viewer.height() // 2)
    left_drag(viewer, qtbot, pos, pos + QPoint(0, -40))  # drag up zooms in
    assert viewer.zoom > 1.0
    assert (viewer.window_center, viewer.window_width) == (center0, width0)


def test_window_tool_unaffected_by_zoom_switch(viewer, qtbot):
    viewer.load_series(make_distinct_series())
    width0 = viewer.window_width
    qtbot.keyClicks(viewer, "Z")
    qtbot.keyClicks(viewer, "W")
    pos = QPoint(viewer.width() // 2, viewer.height() // 2)
    left_drag(viewer, qtbot, pos, pos + QPoint(20, 15))
    assert viewer.window_width > width0
    assert viewer.zoom == 1.0


def test_set_shortcuts_overrides(viewer, qtbot):
    viewer.load_series(make_distinct_series())
    viewer.set_shortcuts({"zoom": "Y"})
    qtbot.keyClicks(viewer, "Y")
    assert viewer.active_tool == "zoom"
    viewer.set_tool("window")
    qtbot.keyClicks(viewer, "Z")  # old binding must be dead
    assert viewer.active_tool == "window"


# -- cine (right mouse button) -------------------------------------------------


def test_right_press_starts_cine(viewer, qtbot):
    viewer.load_series(make_distinct_series(5))
    pos = QPoint(viewer.width() // 2, viewer.height() // 2)
    qtbot.mousePress(viewer, Qt.RightButton, pos=pos)
    qtbot.mouseMove(viewer, pos + QPoint(0, -30))  # right-drag must NOT zoom
    # At >= 10 slices/s the cine loop can wrap back to 0 within a fixed wait,
    # so observe the advance instead of sampling after a delay.
    qtbot.waitUntil(lambda: viewer.current_index >= 1, timeout=2000)
    assert viewer.zoom == 1.0
    qtbot.mouseRelease(viewer, Qt.RightButton, pos=pos)
    stopped_at = viewer.current_index
    qtbot.wait(150)
    assert viewer.current_index == stopped_at


def test_cine_wraps_around(viewer, qtbot):
    viewer.load_series(make_distinct_series(2))
    pos = QPoint(viewer.width() // 2, viewer.height() // 2)
    qtbot.mousePress(viewer, Qt.RightButton, pos=pos)
    qtbot.waitUntil(lambda: viewer.current_index != 0, timeout=2000)
    qtbot.wait(400)  # > 2 slices at 10 slices/s: must wrap, never IndexError
    assert viewer.current_index in (0, 1)
    qtbot.mouseRelease(viewer, Qt.RightButton, pos=pos)


# -- window presets -------------------------------------------------------------


def test_digit_applies_preset(viewer, qtbot):
    viewer.load_series(make_distinct_series())
    qtbot.keyClicks(viewer, "4")
    assert (viewer.window_center, viewer.window_width) == (40.0, 80.0)
    qtbot.keyClicks(viewer, "6")
    assert (viewer.window_center, viewer.window_width) == (32.0, 8.0)


def test_reset_after_preset_restores_dataset_window(viewer, qtbot):
    viewer.load_series(make_series(3))  # factory default window 40/400
    qtbot.keyClicks(viewer, "6")
    assert (viewer.window_center, viewer.window_width) == (32.0, 8.0)
    qtbot.keyClicks(viewer, "R")
    assert (viewer.window_center, viewer.window_width) == (40.0, 400.0)


# -- measurements ---------------------------------------------------------------


def test_length_measurement_label_mm(viewer, qtbot):
    ds = make_ct_dataset()
    ds.PixelSpacing = [0.5, 0.5]
    viewer.load_series([ds])
    qtbot.keyClicks(viewer, "L")
    left_drag(viewer, qtbot, image_pos(viewer, 10, 10), image_pos(viewer, 14, 13))
    [m] = viewer.measurements
    assert m.kind == "length"
    assert m.label == "2.5 mm"  # hypot(4 * 0.5, 3 * 0.5)


def test_length_without_spacing_uses_px(viewer, qtbot):
    viewer.load_series([make_ct_dataset()])  # factory dataset has no PixelSpacing
    qtbot.keyClicks(viewer, "L")
    left_drag(viewer, qtbot, image_pos(viewer, 10, 10), image_pos(viewer, 13, 14))
    [m] = viewer.measurements
    assert m.kind == "length"
    assert m.label == "5.0 px"  # 3-4-5 triangle


def test_ellipse_roi_stats_uniform(viewer, qtbot):
    # pixel_fill=100, slope 1, intercept -1024 -> HU -924 everywhere.
    viewer.load_series([make_ct_dataset(pixel_fill=100)])
    qtbot.keyClicks(viewer, "E")
    left_drag(viewer, qtbot, image_pos(viewer, 10, 10), image_pos(viewer, 40, 40))
    [m] = viewer.measurements
    assert m.kind == "ellipse"
    assert m.label == "Median -924.0  SD 0.0"


def test_polygon_roi_closed_by_double_click(viewer, qtbot):
    viewer.load_series([make_ct_dataset()])
    viewer.set_window(-2000.0, 100.0)  # a reset would restore 40/400
    qtbot.keyClicks(viewer, "P")
    for point in ((10, 10), (40, 10), (25, 35)):
        qtbot.mouseClick(viewer, Qt.LeftButton, pos=image_pos(viewer, *point))
    qtbot.mouseDClick(viewer, Qt.LeftButton, pos=image_pos(viewer, 25, 35))
    [m] = viewer.measurements
    assert m.kind == "polygon"
    assert m.label.startswith("Median ")
    assert viewer.zoom == 1.0  # double click must not reset the view
    assert (viewer.window_center, viewer.window_width) == (-2000.0, 100.0)


def test_escape_cancels_polygon(viewer, qtbot):
    viewer.load_series([make_ct_dataset()])
    qtbot.keyClicks(viewer, "P")
    qtbot.mouseClick(viewer, Qt.LeftButton, pos=image_pos(viewer, 10, 10))
    qtbot.mouseClick(viewer, Qt.LeftButton, pos=image_pos(viewer, 40, 10))
    qtbot.keyClick(viewer, Qt.Key_Escape)
    assert viewer.measurements == []
    # The two vertices must be gone: a double click now cannot close a polygon.
    qtbot.mouseDClick(viewer, Qt.LeftButton, pos=image_pos(viewer, 25, 35))
    assert viewer.measurements == []


def test_measurements_are_per_slice(viewer, qtbot):
    viewer.load_series(make_distinct_series())
    qtbot.keyClicks(viewer, "L")
    left_drag(viewer, qtbot, image_pos(viewer, 10, 10), image_pos(viewer, 30, 30))
    assert len(viewer.measurements) == 1
    send_wheel(viewer, -120)  # slice 1 has no measurements
    assert viewer.measurements == []
