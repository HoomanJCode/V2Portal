"""Read-only diagnostics for cross-platform acceptance checks."""

from __future__ import annotations

import sys

from . import config, runner
from .engines.binary import arch_name, is_android, platform_name
from .outbounds.vpn import detect_clients


def tui_available() -> bool:
    """Return whether the optional interactive UI dependencies are importable."""
    try:
        import prompt_toolkit  # noqa: F401
        import rich  # noqa: F401
    except ImportError:
        return False
    return True


def platform_report() -> dict:
    """Return environment facts without creating files or starting processes."""
    process_kwargs = runner._process_kwargs()
    if "creationflags" in process_kwargs:
        process_mode = "windows-no-window-new-process-group"
    else:
        process_mode = "own-session"
    return {
        "platform": platform_name(),
        "sys_platform": sys.platform,
        "architecture": arch_name(),
        "android": is_android(),
        "config_dir": str(config.config_dir()),
        "runtime_dir": str(config.RUNTIME_DIR),
        "binary_dir": str(config.BIN_DIR),
        "geo_dir": str(config.GEO_DIR),
        "backup_dir": str(config.BACKUP_DIR),
        "process_mode": process_mode,
        "tui_available": tui_available(),
        "vpn_clients": detect_clients(),
    }
