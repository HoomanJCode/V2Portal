"""Shared cross-platform test helpers.

On POSIX tests create ``.sh`` scripts with a ``#!/bin/sh`` shebang.
On Windows they create ``.cmd`` batch files instead, because
``subprocess.Popen`` cannot execute ``.sh`` files directly.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def _shell_to_cmd(body: str) -> str:
    """Translate a minimal subset of POSIX shell lines to ``.cmd`` syntax.

    Supported constructs (matching the patterns used across the test suite):
    * ``exec sleep <N>``  →  ``ping -n <N+1> 127.0.0.1 >nul``
    * ``echo "text"``     →  ``echo text``
    * ``exit [0|1]``      →  ``exit /b [0|1]``
    * ``CHECK_GUARD`` (``if [ "$1" = "check" ] …``) → ``if`` lines
    """
    lines: list[str] = []
    for raw in body.strip().splitlines():
        line = raw.strip()
        if not line or line.startswith("#!"):
            continue

        # CHECK_GUARD: if [ "$1" = "check" ] || [ "$2" = "-test" ]; then exit 0; fi
        if re.match(r'if\s+\[.*"?\$[12]"?.*"?(check|[-]test)"?', line):
            lines.append('if "%~1"=="check" exit /b 0')
            lines.append('if "%~2"=="-test" exit /b 0')
            continue

        m = re.match(r"exec\s+sleep\s+(\d+)", line)
        if m:
            n = int(m.group(1)) + 1
            lines.append(f"ping -n {n} 127.0.0.1 >nul 2>&1")
            continue

        m = re.match(r'echo\s+["\']?(.*?)["\']?\s*$', line)
        if m:
            lines.append(f"echo {m.group(1)}")
            continue

        m = re.match(r"exit\s+(\d+)", line)
        if m:
            lines.append(f"exit /b {m.group(1)}")
            continue

        # Fallback: keep as-is (best-effort)
        lines.append(line)

    return "\r\n".join(lines)


def make_fake_script(tmp_path: Path, name: str, shell_body: str) -> str:
    """Create a platform-appropriate executable script.

    Returns the string path of the created script.
    """
    if sys.platform == "win32":
        cmd = _shell_to_cmd(shell_body)
        path = tmp_path / f"{name}.cmd"
        path.write_text(f"@echo off\r\n{cmd}\r\n", encoding="utf-8")
    else:
        path = tmp_path / f"{name}.sh"
        path.write_text("#!/bin/sh\n" + shell_body + "\n")
        path.chmod(0o755)
    return str(path)


def engine_binary_name(tmp_path: Path, engine: str = "sing-box") -> str:
    """Return the correct binary filename for the current platform."""
    if sys.platform == "win32":
        return f"{engine}.exe" if engine == "sing-box" else f"{engine}.exe"
    return engine


def engine_binary_path(tmp_path: Path, engine: str = "sing-box") -> Path:
    """Return a Path for the fake binary in tmp_path with the correct platform name."""
    return tmp_path / engine_binary_name(tmp_path, engine)
