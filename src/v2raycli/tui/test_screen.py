"""Outbound testing screen.

The latency tester lands in Phase 07; this screen is a placeholder until then.
"""

from __future__ import annotations

from . import widgets


def run(store) -> None:
    widgets.show_message("Testing", "Latency testing is implemented in the next phase.")
