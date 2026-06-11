"""Tests for PACS node configuration with TOML persistence."""

from pathlib import Path

import pytest

from odw.core.config import (
    AppConfig,
    ConfigError,
    default_config_path,
    default_storage_dir,
    load_config,
    save_config,
)
from odw.core.models import PacsNode


def test_load_missing_file_returns_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "nope.toml")

    assert config.local_ae_title == "ODW"
    assert config.listen_port == 11112
    assert config.nodes == []


def test_roundtrip(tmp_path: Path) -> None:
    original = AppConfig(
        local_ae_title="MYAET",
        listen_port=10400,
        storage_dir=tmp_path / "store",
        nodes=[
            PacsNode(name="Main PACS", ae_title="MAIN", host="pacs.example.org", port=104),
            PacsNode(name="Backup", ae_title="BACKUP", host="10.0.0.2", port=11112),
        ],
    )
    path = tmp_path / "config.toml"

    save_config(original, path)
    loaded = load_config(path)

    assert loaded.local_ae_title == original.local_ae_title
    assert loaded.listen_port == original.listen_port
    assert loaded.storage_dir == original.storage_dir
    assert loaded.nodes == original.nodes


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "deeper" / "config.toml"

    save_config(AppConfig(), path)

    assert path.is_file()


def test_save_is_atomic_no_tmp_left_behind(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"

    save_config(AppConfig(), path)

    assert path.is_file()
    assert list(tmp_path.glob("*.tmp")) == []


@pytest.mark.parametrize("bad_port", ['"abc"', "99999"])
def test_load_rejects_invalid_port(tmp_path: Path, bad_port: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(f"listen_port = {bad_port}\n")

    with pytest.raises(ConfigError):
        load_config(path)


def test_default_paths_are_absolute() -> None:
    config_path = default_config_path()
    storage_dir = default_storage_dir()

    assert config_path.is_absolute()
    assert storage_dir.is_absolute()
    assert "odw" in str(config_path)
    assert "odw" in str(storage_dir)
