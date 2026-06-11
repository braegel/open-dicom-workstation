import tomllib
from pathlib import Path

import odw

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_version_matches_pyproject() -> None:
    with PYPROJECT.open("rb") as f:
        pyproject = tomllib.load(f)
    assert odw.__version__ == pyproject["project"]["version"]
