"""Poll engine traffic counters.

sing-box's Clash API reports cumulative traffic on the ``/connections``
endpoint as ``uploadTotal`` / ``downloadTotal``. (The ``/traffic`` endpoint
stays at zero for non-clash-mode configs, which is how this app runs.)
"""

from __future__ import annotations

import httpx


def read_traffic(host: str, port: int, timeout: float = 3.0) -> dict | None:
    """Return ``{"up": int, "down": int}`` of cumulative bytes, or ``None``.

    ``up``/``down`` map to the engine's ``uploadTotal``/``downloadTotal``
    counters. Any transport/parse failure returns ``None`` so callers can treat
    the meter as best-effort (e.g. an xray engine has no Clash API).
    """
    try:
        resp = httpx.get(f"http://{host}:{port}/connections", timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return {
            "up": int(data.get("uploadTotal", 0)),
            "down": int(data.get("downloadTotal", 0)),
        }
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        return None
