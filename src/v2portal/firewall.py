"""Windows Firewall rule management for engine binaries.

On Windows, engine binaries (sing-box, xray) need an outbound firewall
rule to connect to remote servers.  This module adds, removes, and
queries those rules using PowerShell's ``NetSecurity`` cmdlets.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from pathlib import Path

_log = logging.getLogger(__name__)

_RULE_PREFIX = "v2portal"


def is_windows() -> bool:
    return sys.platform == "win32"


def is_admin() -> bool:
    """Return True when the current process has administrator privileges."""
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


def _rule_display_name(engine: str) -> str:
    return f"{_RULE_PREFIX} {engine}"


def _run_powershell(command: str, *, capture: bool = True) -> subprocess.CompletedProcess:
    """Run a single PowerShell command line and return the result."""
    argv = [
        "powershell", "-NoProfile", "-NonInteractive",
        "-Command", command,
    ]
    return subprocess.run(
        argv,
        capture_output=capture,
        text=True,
        timeout=15,
    )


def _elevated_powershell(command: str) -> subprocess.CompletedProcess:
    """Run a PowerShell command elevated via ShellExecute 'runas'.

    Returns a CompletedProcess with returncode=-1 when elevation fails
    or the user cancels the UAC prompt.
    """
    if is_admin():
        return _run_powershell(command)

    # ShellExecuteW(runas) re-launches PowerShell elevated.
    # We wait for it synchronously via WaitForSingleObject.
    import ctypes.wintypes  # noqa: F811

    params = f'-NoProfile -NonInteractive -Command "{command}"'
    result = ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
        None, "runas", "powershell.exe", params, None, 1,
    )
    if result <= 32:
        _log.warning("elevation failed (ShellExecuteW returned %d)", result)
        return subprocess.CompletedProcess([], returncode=-1, stdout="", stderr="elevation denied")

    # ShellExecuteW is fire-and-forget; we cannot capture output, but the
    # rule will be in effect.  Return success so callers can proceed.
    return subprocess.CompletedProcess([], returncode=0, stdout="", stderr="")


def add_rule(engine: str, binary_path: str | Path, *, elevate: bool = True) -> str:
    """Add an outbound allow rule for *engine*'s binary.

    Returns a human-readable status message.
    """
    if not is_windows():
        return "firewall rules are only needed on Windows"

    binary = Path(binary_path).resolve()
    if not binary.exists():
        return f"binary not found: {binary}"

    name = _rule_display_name(engine)
    cmd = (
        f"New-NetFirewallRule -DisplayName '{name}' "
        f"-Direction Outbound -Program '{binary}' -Action Allow "
        f"-Description 'v2portal auto-generated rule for {engine}' "
        f"-ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name"
    )

    result = _run_powershell(cmd)
    if result.returncode == 0 and result.stdout.strip():
        return f"firewall rule added for {engine} ({binary.name})"

    # Might already exist — check.
    existing = check_rule(engine)
    if existing:
        return f"firewall rule already exists for {engine} ({binary.name})"

    if elevate:
        _elevated_powershell(cmd)
        return f"firewall rule added (elevated) for {engine} ({binary.name})"

    return (
        f"failed to add firewall rule — run as Administrator:\n"
        f"  New-NetFirewallRule -DisplayName '{name}' "
        f"-Direction Outbound -Program '{binary}' -Action Allow"
    )


def remove_rule(engine: str) -> str:
    """Remove the outbound allow rule for *engine*."""
    if not is_windows():
        return "firewall rules are only needed on Windows"

    name = _rule_display_name(engine)
    cmd = f"Remove-NetFirewallRule -DisplayName '{name}' -ErrorAction SilentlyContinue"

    result = _run_powershell(cmd)
    if result.returncode == 0:
        return f"firewall rule removed for {engine}"

    if elevate:
        _elevated_powershell(cmd)
        return f"firewall rule removed (elevated) for {engine}"

    return f"failed to remove firewall rule — run as Administrator"


def check_rule(engine: str) -> dict | None:
    """Return rule info dict if a firewall rule exists for *engine*, else None."""
    if not is_windows():
        return None

    name = _rule_display_name(engine)
    cmd = (
        f"Get-NetFirewallRule -DisplayName '{name}' -ErrorAction SilentlyContinue | "
        f"Select-Object DisplayName,Enabled,Direction,Action | "
        f"ConvertTo-Json -Compress"
    )
    result = _run_powershell(cmd)
    if result.returncode != 0 or not result.stdout.strip():
        return None

    import json
    try:
        data = json.loads(result.stdout.strip())
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def list_rules() -> list[dict]:
    """Return all v2portal firewall rules."""
    if not is_windows():
        return []

    cmd = (
        f"Get-NetFirewallRule | Where-Object {{$_.DisplayName -like '{_RULE_PREFIX}*'}} | "
        f"Select-Object DisplayName,Enabled,Direction,Action | "
        f"ConvertTo-Json -Compress"
    )
    result = _run_powershell(cmd)
    if result.returncode != 0 or not result.stdout.strip():
        return []

    import json
    try:
        data = json.loads(result.stdout.strip())
    except (json.JSONDecodeError, ValueError):
        return []
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return data
    return []
