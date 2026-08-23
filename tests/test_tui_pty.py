"""Smoke-test the CLI by launching it through a pseudo-terminal.

The CLI is deliberately non-interactive — it prints a summary and exits
when no command is given.  This test verifies that the process starts,
prints the expected summary lines, and exits cleanly.
"""

from __future__ import annotations

import os
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

from v2raycli.models import Profile
from v2raycli.storage import ConfigStore

SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}

pytest.importorskip("fcntl")
pytest.importorskip("termios")
pytest.importorskip("pty")
pytest.importorskip("select")


def _read_all(master: int, timeout: float) -> bytes:
    import select

    data = b""
    end = time.time() + timeout
    while time.time() < end:
        ready, _, _ = select.select([master], [], [], 0.5)
        if not ready:
            break
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        data += chunk
    return data


def test_cli_launches_and_exits_on_pty(tmp_path):
    """Launch the CLI on a pty and verify it prints the summary and exits."""
    import fcntl
    import pty
    import termios

    store = ConfigStore(tmp_path / "config.json")
    store.load()
    store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    store.save()

    master, slave = pty.openpty()
    # 40 columns forces widgets._use_simple_ui() if the TUI were launched.
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 40, 0, 0))

    src = Path(__file__).resolve().parent.parent / "src"
    env = {
        **os.environ,
        "TERM": "dumb",
        "PYTHONPATH": str(src) + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "v2raycli", "--config-dir", str(tmp_path), "--no-auto-update"],
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=env,
        close_fds=True,
    )
    os.close(slave)

    output = b""
    deadline = time.time() + 15
    while time.time() < deadline and proc.poll() is None:
        output += _read_all(master, 0.5)

    output += _read_all(master, 2.0)
    os.close(master)
    rc = proc.wait(timeout=10)

    text = output.decode("utf-8", errors="replace")
    assert rc == 0, f"CLI exited {rc}; output:\n{text}"
    # The CLI prints a summary (version + config path + counts).
    assert "v2raycli" in text
    assert "profiles" in text
