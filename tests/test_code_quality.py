"""Guard against double-escaped string/byte literals.

A previous batch of code wrote CRLF and hex-byte escape sequences with two
backslashes instead of one, so the literal text (backslash-r, backslash-n,
etc.) was emitted instead of the real bytes. That silently broke the WebSocket
and SOCKS probes. Scan the source for those exact patterns so the bug class
can't quietly return.
"""

from __future__ import annotations

import re
from pathlib import Path

# Two backslashes before a hex byte escape (e.g. 0x05 written as two
# backslashes, an x, and the digits instead of one backslash, an x, and the
# digits).
_DOUBLE_HEX = re.compile(r"\\\\x[0-9a-fA-F]{2}")
# Two backslashes around "r" and "n" (CRLF written as escaped text).
_DOUBLE_CRLF = re.compile(r"\\\\r\\\\n")

_ROOT = Path(__file__).resolve().parent.parent
_DIRS = ("src", "tests", "scripts")


def _violations() -> list[str]:
    found: list[str] = []
    for directory in _DIRS:
        base = _ROOT / directory
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                if _DOUBLE_HEX.search(line) or _DOUBLE_CRLF.search(line):
                    found.append(f"{path.relative_to(_ROOT)}:{lineno}: {line.strip()}")
    return found


def test_no_double_escaped_literals() -> None:
    violations = _violations()
    assert not violations, (
        "double-escaped literals found (CRLF and hex-byte escapes must use a "
        "single backslash):\n" + "\n".join(violations)
    )
