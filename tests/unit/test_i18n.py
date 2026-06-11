"""Tests for the i18n translation source stubs."""

import xml.etree.ElementTree as ET
from pathlib import Path

TS_PATH = Path(__file__).resolve().parents[2] / "src" / "odw" / "ui" / "i18n" / "odw_de.ts"


def test_german_translation_source_exists_and_is_valid():
    assert TS_PATH.exists(), f"missing translation source: {TS_PATH}"
    root = ET.parse(TS_PATH).getroot()
    assert root.tag == "TS"
    assert root.attrib["language"].startswith("de")
