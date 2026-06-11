"""Built-in CT window presets, keyed to the digit keys 1-9."""

from dataclasses import dataclass

__all__ = ["WINDOW_PRESETS", "WindowPreset", "preset_for_key"]


@dataclass(frozen=True)
class WindowPreset:
    key: str  # digit "1".."9"
    name: str  # English display name
    center: float
    width: float


WINDOW_PRESETS: tuple[WindowPreset, ...] = (
    WindowPreset("1", "Soft tissue / abdomen", 50.0, 400.0),
    WindowPreset("2", "Lung", -600.0, 1500.0),
    WindowPreset("3", "Bone", 500.0, 2000.0),
    WindowPreset("4", "Brain", 40.0, 80.0),
    WindowPreset("5", "Blood", 60.0, 60.0),
    # Lev et al., Radiology 1999: narrow window improves early-ischemia detection.
    WindowPreset("6", "Stroke", 32.0, 8.0),
    WindowPreset("7", "Angio (CTA)", 150.0, 600.0),
    WindowPreset("8", "Liver", 70.0, 150.0),
    WindowPreset("9", "Disc (spine)", 60.0, 300.0),
)


def preset_for_key(key: str) -> WindowPreset | None:
    """The preset bound to a digit key, or None if the key has no preset."""
    for preset in WINDOW_PRESETS:
        if preset.key == key:
            return preset
    return None
