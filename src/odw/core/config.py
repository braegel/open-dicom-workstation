"""Application configuration with TOML persistence."""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import platformdirs
import tomli_w

from odw.core.models import PacsNode

DEFAULT_LOCAL_AET = "ODW"
DEFAULT_LISTEN_PORT = 11112


class ConfigError(Exception):
    """Raised when a configuration file contains invalid data."""


def default_storage_dir() -> Path:
    return Path(platformdirs.user_data_dir("odw")) / "dicom"


def default_config_path() -> Path:
    return Path(platformdirs.user_config_dir("odw")) / "config.toml"


@dataclass
class AppConfig:
    local_ae_title: str = DEFAULT_LOCAL_AET
    listen_port: int = DEFAULT_LISTEN_PORT
    storage_dir: Path = field(default_factory=default_storage_dir)
    nodes: list[PacsNode] = field(default_factory=list)


def _require_str(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ConfigError(f"{context}: missing or invalid '{key}'")
    return value


def _require_port(data: dict[str, Any], key: str, context: str) -> int:
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 65535:
        raise ConfigError(f"{context}: '{key}' must be an integer in 1-65535")
    return value


def _node_from_dict(data: Any) -> PacsNode:
    if not isinstance(data, dict):
        raise ConfigError("node entry must be a table")
    return PacsNode(
        name=_require_str(data, "name", "node"),
        ae_title=_require_str(data, "ae_title", "node"),
        host=_require_str(data, "host", "node"),
        port=_require_port(data, "port", "node"),
    )


def load_config(path: Path | None = None) -> AppConfig:
    if path is None:
        path = default_config_path()
    if not path.exists():
        return AppConfig()

    try:
        with path.open("rb") as fp:
            data = tomllib.load(fp)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {path}: {exc}") from exc

    config = AppConfig()
    if "local_ae_title" in data:
        config.local_ae_title = _require_str(data, "local_ae_title", "config")
    if "listen_port" in data:
        config.listen_port = _require_port(data, "listen_port", "config")
    if "storage_dir" in data:
        config.storage_dir = Path(_require_str(data, "storage_dir", "config"))
    config.nodes = [_node_from_dict(node) for node in data.get("nodes", [])]
    return config


def save_config(config: AppConfig, path: Path | None = None) -> None:
    if path is None:
        path = default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "local_ae_title": config.local_ae_title,
        "listen_port": config.listen_port,
        "storage_dir": str(config.storage_dir),
        "nodes": [
            {"name": n.name, "ae_title": n.ae_title, "host": n.host, "port": n.port}
            for n in config.nodes
        ],
    }

    # Write to a sibling temp file, then atomically replace, so readers
    # never observe a partially written config.
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with tmp_path.open("wb") as fp:
            tomli_w.dump(data, fp)
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)
