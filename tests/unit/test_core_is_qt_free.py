"""Architecture guard: odw.core must be importable without Qt.

The core is meant to be reusable from scripts and alternative front ends,
so importing any odw.core module must never pull in PySide6.
"""

import subprocess
import sys

IMPORT_ALL_CORE = """
import pkgutil
import sys

import odw.core

for info in pkgutil.walk_packages(odw.core.__path__, prefix="odw.core."):
    __import__(info.name)

assert "PySide6" not in sys.modules, "odw.core imported PySide6"
"""


def test_core_package_imports_without_qt() -> None:
    result = subprocess.run(
        [sys.executable, "-c", IMPORT_ALL_CORE],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
