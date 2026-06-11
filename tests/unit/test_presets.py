"""Tests for the built-in CT window presets."""

from odw.core.presets import WINDOW_PRESETS, WindowPreset, preset_for_key


def test_there_are_nine_presets_keyed_1_to_9_in_order() -> None:
    assert len(WINDOW_PRESETS) == 9
    assert [p.key for p in WINDOW_PRESETS] == [str(d) for d in range(1, 10)]


def test_names_are_unique_and_non_empty() -> None:
    names = [p.name for p in WINDOW_PRESETS]

    assert all(names)
    assert len(set(names)) == len(names)


def test_widths_are_at_least_one() -> None:
    assert all(p.width >= 1.0 for p in WINDOW_PRESETS)


def test_preset_for_key_returns_stroke_preset() -> None:
    preset = preset_for_key("6")

    assert preset == WindowPreset(key="6", name="Stroke", center=32.0, width=8.0)


def test_preset_for_key_unknown_returns_none() -> None:
    assert preset_for_key("0") is None
    assert preset_for_key("w") is None
