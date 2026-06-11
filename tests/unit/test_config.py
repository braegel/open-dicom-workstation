"""Tests for PACS node configuration with TOML persistence."""

from pathlib import Path

import pytest
from pydicom.uid import ImplicitVRLittleEndian, RLELossless

from odw.core.config import (
    DEFAULT_VIEWER_SHORTCUTS,
    AppConfig,
    ConfigError,
    default_config_path,
    default_storage_dir,
    load_config,
    save_config,
)
from odw.core.models import PacsNode
from odw.core.transfer import DEFAULT_TRANSFER_SYNTAXES


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
            PacsNode(
                name="Main PACS",
                ae_title="MAIN",
                host="pacs.example.org",
                port=104,
                retrieve_method="C-MOVE",
            ),
            PacsNode(name="Backup", ae_title="BACKUP", host="10.0.0.2", port=11112),
        ],
        transfer_syntaxes=[str(ImplicitVRLittleEndian), str(RLELossless)],
    )
    path = tmp_path / "config.toml"

    save_config(original, path)
    loaded = load_config(path)

    assert loaded.local_ae_title == original.local_ae_title
    assert loaded.listen_port == original.listen_port
    assert loaded.storage_dir == original.storage_dir
    assert loaded.nodes == original.nodes
    assert loaded.nodes[0].retrieve_method == "C-MOVE"
    assert loaded.nodes[1].retrieve_method == "C-GET"
    assert loaded.transfer_syntaxes == [str(ImplicitVRLittleEndian), str(RLELossless)]


def test_load_old_config_without_new_keys_yields_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        'local_ae_title = "OLD"\n'
        "\n"
        "[[nodes]]\n"
        'name = "Main"\n'
        'ae_title = "MAIN"\n'
        'host = "pacs.example.org"\n'
        "port = 104\n"
    )

    config = load_config(path)

    assert config.nodes[0].retrieve_method == "C-GET"
    assert config.transfer_syntaxes == DEFAULT_TRANSFER_SYNTAXES
    assert config.viewer_shortcuts == DEFAULT_VIEWER_SHORTCUTS


def test_load_rejects_invalid_retrieve_method(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        "[[nodes]]\n"
        'name = "Main"\n'
        'ae_title = "MAIN"\n'
        'host = "pacs.example.org"\n'
        "port = 104\n"
        'retrieve_method = "C-PULL"\n'
    )

    with pytest.raises(ConfigError):
        load_config(path)


def test_load_rejects_empty_transfer_syntaxes(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("transfer_syntaxes = []\n")

    with pytest.raises(ConfigError):
        load_config(path)


def test_load_rejects_unknown_transfer_syntax(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('transfer_syntaxes = ["1.2.3.4.5"]\n')

    with pytest.raises(ConfigError):
        load_config(path)


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


def test_viewer_shortcuts_roundtrip(tmp_path: Path) -> None:
    custom = dict(DEFAULT_VIEWER_SHORTCUTS)
    custom["window"] = "F"
    custom["reset"] = "0"
    path = tmp_path / "config.toml"

    save_config(AppConfig(viewer_shortcuts=custom), path)
    loaded = load_config(path)

    assert loaded.viewer_shortcuts == custom


def test_viewer_shortcuts_default_when_absent(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('local_ae_title = "OLD"\n')

    config = load_config(path)

    assert config.viewer_shortcuts == DEFAULT_VIEWER_SHORTCUTS


def test_viewer_shortcuts_partial_table_fills_defaults(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[viewer_shortcuts]\nwindow = "F"\n')

    config = load_config(path)

    expected = dict(DEFAULT_VIEWER_SHORTCUTS)
    expected["window"] = "F"
    assert config.viewer_shortcuts == expected


def test_viewer_shortcuts_lowercase_input_is_normalized(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[viewer_shortcuts]\nwindow = " f "\n')

    config = load_config(path)

    assert config.viewer_shortcuts["window"] == "F"


def test_viewer_shortcuts_rejects_unknown_action(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[viewer_shortcuts]\nteleport = "T"\n')

    with pytest.raises(ConfigError):
        load_config(path)


def test_viewer_shortcuts_rejects_empty_value(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[viewer_shortcuts]\nwindow = ""\n')

    with pytest.raises(ConfigError):
        load_config(path)


def test_viewer_shortcuts_rejects_duplicate_values_case_insensitive(
    tmp_path: Path,
) -> None:
    # "z" collides with the default zoom shortcut "Z" after normalization.
    path = tmp_path / "config.toml"
    path.write_text('[viewer_shortcuts]\nwindow = "z"\n')

    with pytest.raises(ConfigError):
        load_config(path)


def test_default_paths_are_absolute() -> None:
    config_path = default_config_path()
    storage_dir = default_storage_dir()

    assert config_path.is_absolute()
    assert storage_dir.is_absolute()
    assert "odw" in str(config_path)
    assert "odw" in str(storage_dir)
