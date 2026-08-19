"""Settings defaults and platform paths for v2raycli."""

from __future__ import annotations

import os
import sys
from pathlib import Path

try:  # prefer platformdirs when available
    from platformdirs import user_config_dir as _pdirs_user_config_dir
except ImportError:  # pragma: no cover - stdlib fallback for minimal dev setups
    _pdirs_user_config_dir = None

from .models import Settings

APP_NAME = "v2raycli"
SCHEMA_VERSION = 2


def _user_config_dir(appname: str) -> str:
    """Resolve the platform config dir, matching platformdirs semantics.

    Uses platformdirs when installed, otherwise a stdlib equivalent so the
    package stays importable in minimal environments (e.g. Termux dev shell).
    """
    if _pdirs_user_config_dir is not None:
        return _pdirs_user_config_dir(appname)
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return str(Path(base) / appname)
    if sys.platform == "darwin":
        return str(Path.home() / "Library" / "Application Support" / appname)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return str(Path(base) / appname)


def config_dir() -> Path:
    """Platform config directory (Linux/Termux ~/.config/v2raycli, Windows %APPDATA%/v2raycli)."""
    return Path(_user_config_dir(APP_NAME))


CONFIG_PATH = config_dir() / "config.json"
RUNTIME_DIR = config_dir() / "runtime"
BIN_DIR = config_dir() / "bin"
GEO_DIR = config_dir() / "geo"
BACKUP_DIR = config_dir() / "backup"


def ensure_dirs() -> None:
    """Create all directories the app needs."""
    config_dir().mkdir(parents=True, exist_ok=True)
    for directory in (RUNTIME_DIR, BIN_DIR, GEO_DIR, BACKUP_DIR):
        directory.mkdir(parents=True, exist_ok=True)


DEFAULT_SETTINGS = Settings().to_dict()

DEFAULT_ENGINES = {
    "sing-box": {"binary_path": "auto", "version": "latest"},
    "xray": {"binary_path": "auto", "version": "latest"},
}
