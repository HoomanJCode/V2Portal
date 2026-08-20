"""Smoke-test the real TUI by driving it through a pseudo-terminal.

The widget-level tests mock ``prompt_toolkit`` dialogs, so they never exercise
the actual terminal loop. This test launches ``python -m v2raycli`` on a real
pty, forces the small-terminal numbered menu, sends the Quit selection, and
asserts the process renders the menu and exits cleanly.
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


def test_tui_launches_and_quits_on_pty(tmp_path):
    import fcntl
    import pty
    import termios

    store = ConfigStore(tmp_path / "config.json")
    store.load()
    store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    store.save()

    master, slave = pty.openpty()
    # 40 columns forces widgets._use_simple_ui() -> numbered text prompts.
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
    sent_quit = False
    deadline = time.time() + 15
    while time.time() < deadline and proc.poll() is None:
        output += _read_all(master, 0.5)
        if not sent_quit and b"Quit" in output:
            os.write(master, b"6\n")
            sent_quit = True

    output += _read_all(master, 2.0)
    os.close(master)
    rc = proc.wait(timeout=10)

    text = output.decode("utf-8", errors="replace")
    assert rc == 0, f"TUI exited {rc}; output:\n{text}"
    assert "Quit" in text
