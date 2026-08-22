"""Install v2raycli as a background service.

A service keeps a chosen profile/group connected across reboots by launching
``v2raycli --connect <id>`` on boot:

- **Linux** — a systemd *user* unit under
  ``$XDG_CONFIG_HOME/systemd/user`` (or ``~/.config/systemd/user``).
- **Termux** — a ``termux-services`` run script under ``~/.termux/sv/v2raycli``.

Other platforms (Windows, macOS) are not supported and raise.
"""

from __future__ import annotations

import logging
import os
import shlex
import sys
from pathlib import Path

SERVICE_NAME = "v2raycli"
_log = logging.getLogger(__name__)


def platform() -> str:
    """Detect the run environment: ``linux``, ``termux``, or ``sys.platform``."""
    if os.environ.get("PREFIX") and os.environ.get("TERMUX_VERSION"):
        return "termux"
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def _cmdline(connect_id: str, config_dir: str | None = None) -> str:
    args = [shlex.quote(sys.executable), "-m", "v2raycli", "--connect", connect_id]
    if config_dir:
        args += ["--config-dir", shlex.quote(config_dir)]
    return " ".join(args)


def build_systemd_unit(
    connect_id: str, config_dir: str | None = None, restart: str = "on-failure"
) -> str:
    """Return the text of a systemd *user* unit for ``connect_id``."""
    exec_start = _cmdline(connect_id, config_dir)
    return (
        "[Unit]\n"
        "Description=v2raycli LAN proxy\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        f"ExecStart={exec_start}\n"
        f"Restart={restart}\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def build_termux_run_script(connect_id: str, config_dir: str | None = None) -> str:
    """Return the text of a termux-services ``run`` script for ``connect_id``."""
    return "#!/data/data/com.termux/files/usr/bin/sh\n" f"exec {_cmdline(connect_id, config_dir)}\n"


def systemd_unit_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def termux_service_dir() -> Path:
    return Path.home() / ".termux" / "sv" / SERVICE_NAME


def install_service(store, connect_id: str, config_dir: str | None = None) -> Path:
    """Write a service unit for ``connect_id``; return the written path.

    Raises ``ValueError`` for an unknown id and ``RuntimeError`` on unsupported
    platforms.
    """
    if store.get_profile(connect_id) is None and store.get_group(connect_id) is None:
        raise ValueError(f"unknown profile or group id: {connect_id}")

    plat = platform()
    if plat == "linux":
        target = systemd_unit_dir() / f"{SERVICE_NAME}.service"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(build_systemd_unit(connect_id, config_dir), encoding="utf-8")
        return target
    if plat == "termux":
        target = termux_service_dir() / "run"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(build_termux_run_script(connect_id, config_dir), encoding="utf-8")
        target.chmod(0o700)
        return target
    raise RuntimeError(f"service install not supported on {plat}")


def uninstall_service() -> Path | None:
    """Remove any installed service unit/script; return the removed path."""
    plat = platform()
    candidates: list[Path] = []
    if plat == "linux":
        candidates.append(systemd_unit_dir() / f"{SERVICE_NAME}.service")
    elif plat == "termux":
        candidates.append(termux_service_dir() / "run")
    removed = None
    for path in candidates:
        if path.exists():
            try:
                path.unlink()
            except OSError as exc:
                _log.warning("failed to remove service %s: %s", path, exc)
                continue
            removed = path
    return removed
