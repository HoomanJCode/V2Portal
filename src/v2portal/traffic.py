"""Poll engine traffic counters.

sing-box's Clash API reports cumulative traffic on the ``/connections``
endpoint as ``uploadTotal`` / ``downloadTotal``. (The ``/traffic`` endpoint
stays at zero for non-clash-mode configs, which is how this app runs.)
"""

from __future__ import annotations

import httpx


def _counter(value) -> int:
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        raise ValueError("traffic counter must be a non-negative integer")
    counter = int(value)
    if counter < 0:
        raise ValueError("traffic counter must be a non-negative integer")
    return counter


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
        if not isinstance(data, dict):
            return None
        return {
            "up": _counter(data.get("uploadTotal", 0)),
            "down": _counter(data.get("downloadTotal", 0)),
        }
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return None


def read_active_outbound(host: str, port: int, timeout: float = 3.0) -> str | None:
    """Return the outbound tag used by the most recent active connection.

    Polls the sing-box Clash API ``/connections`` and returns the
    ``outbound`` tag of the newest connection. Returns ``None`` when the
    engine is unreachable (xray has no Clash API) or there are no active
    connections. For selectors/urltest this usually reports the balancer
    tag rather than the concrete child node.
    """
    try:
        resp = httpx.get(f"http://{host}:{port}/connections", timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        connections = data.get("connections")
        if not isinstance(connections, list) or not connections:
            return None
        by_start = sorted(
            connections,
            key=lambda c: c.get("start", 0) if isinstance(c, dict) else 0,
            reverse=True,
        )
        for conn in by_start:
            tag = conn.get("outbound") if isinstance(conn, dict) else None
            if isinstance(tag, str) and tag:
                return tag
        return None
    except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError, OverflowError, IndexError):
        return None
