"""Install v2portal as a background service.

A service keeps the persistent proxy servers running across reboots by
launching ``v2portal server start --all`` on boot:

- **Linux** — a systemd *user* unit under
  ``$XDG_CONFIG_HOME/systemd/user`` (or ``~/.config/systemd/user``).
- **Termux** — a ``termux-services`` run script under ``~/.termux/sv/v2portal``.
- **macOS** — a launchd *user* plist under
  ``~/Library/LaunchAgents/``.

Windows is not supported and raises.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
import sys
from xml.sax.saxutils import escape as xml_escape
from pathlib import Path

SERVICE_NAME = "v2portal"
_log = logging.getLogger(__name__)


def platform() -> str:
    """Detect the run environment: ``linux``, ``termux``, ``darwin``, or ``sys.platform``."""
    if os.environ.get("PREFIX") and os.environ.get("TERMUX_VERSION"):
        return "termux"
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    return sys.platform


def _cmdline(config_dir: str | None = None) -> str:
    args = [sys.executable, "-m", "v2portal", "server", "start", "--all"]
    if config_dir:
        args += ["--config-dir", config_dir]
    return " ".join(shlex.quote(arg) for arg in args)


def _systemd_quote(value: str) -> str:
    """Quote one systemd ExecStart argument without invoking a shell."""
    escaped = (
        value.replace("%", "%%")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    if re.fullmatch(r"[A-Za-z0-9_./:@+-]+", value):
        return escaped
    return f'"{escaped}"'


def build_systemd_unit(
    config_dir: str | None = None, restart: str = "on-failure"
) -> str:
    """Return the text of a systemd *user* unit that boots all servers."""
    argv = [sys.executable, "-m", "v2portal", "server", "start", "--all"]
    if config_dir:
        argv += ["--config-dir", config_dir]
    exec_start = " ".join(_systemd_quote(arg) for arg in argv)
    return (
        "[Unit]\n"
        "Description=v2portal LAN proxy\n"
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


def build_termux_run_script(config_dir: str | None = None) -> str:
    """Return the text of a termux-services ``run`` script that boots all servers."""
    return "#!/data/data/com.termux/files/usr/bin/sh\n" f"exec {_cmdline(config_dir)}\n"


def build_launchd_plist(config_dir: str | None = None) -> str:
    """Return the XML content of a macOS launchd user plist."""
    argv = [sys.executable, "-m", "v2portal", "server", "start", "--all"]
    if config_dir:
        argv += ["--config-dir", config_dir]
    log_dir = Path.home() / "Library" / "Logs"
    args_xml = "".join(f"    <string>{xml_escape(arg)}</string>\n" for arg in argv)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        '<dict>\n'
        '  <key>Label</key>\n'
        f'  <string>{SERVICE_NAME}</string>\n'
        '  <key>ProgramArguments</key>\n'
        '  <array>\n'
        + args_xml
        + '  </array>\n'
        '  <key>RunAtLoad</key>\n'
        '  <true/>\n'
        '  <key>KeepAlive</key>\n'
        '  <true/>\n'
        '  <key>StandardOutPath</key>\n'
        f'  <string>{log_dir}/{SERVICE_NAME}.stdout.log</string>\n'
        '  <key>StandardErrorPath</key>\n'
        f'  <string>{log_dir}/{SERVICE_NAME}.stderr.log</string>\n'
        '</dict>\n'
        '</plist>\n'
    )


def launchd_plist_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def systemd_unit_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def termux_service_dir() -> Path:
    return Path.home() / ".termux" / "sv" / SERVICE_NAME


def install_service(config_dir: str | None = None) -> Path:
    """Write a service unit that boots all servers on startup.

    Raises ``RuntimeError`` on unsupported platforms.
    """
    plat = platform()
    if plat == "linux":
        target = systemd_unit_dir() / f"{SERVICE_NAME}.service"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(build_systemd_unit(config_dir), encoding="utf-8")
        return target
    if plat == "termux":
        target = termux_service_dir() / "run"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(build_termux_run_script(config_dir), encoding="utf-8")
        target.chmod(0o700)
        return target
    if plat == "darwin":
        target = launchd_plist_dir() / f"{SERVICE_NAME}.plist"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(build_launchd_plist(config_dir), encoding="utf-8")
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
    elif plat == "darwin":
        candidates.append(launchd_plist_dir() / f"{SERVICE_NAME}.plist")
    removed = None
    for path in candidates:
        if path.exists():
            if plat == "linux":
                _run_manager_command(["systemctl", "--user", "disable", "--now", f"{SERVICE_NAME}.service"])
            elif plat == "termux":
                _run_manager_command(["sv", "down", SERVICE_NAME])
                _run_manager_command(["sv-disable", SERVICE_NAME])
            elif plat == "darwin":
                _run_manager_command(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)])
            try:
                path.unlink()
            except OSError as exc:
                _log.warning("failed to remove service %s: %s", path, exc)
                continue
            removed = path
    if removed is not None and plat == "linux":
        _run_manager_command(["systemctl", "--user", "daemon-reload"])
    return removed


def _run_manager_command(argv: list[str]) -> None:
    """Best-effort stop/unregister; missing managers must not block cleanup."""
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError as exc:
        _log.debug("could not run %s: %s", argv[0], exc)
        return
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip()
        _log.debug("%s failed (%d): %s", argv[0], result.returncode, detail)
