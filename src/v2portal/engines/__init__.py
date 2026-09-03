"""Engine selection helpers shared across v2portal."""

from __future__ import annotations

from typing import Any

SINGBOX = "sing-box"
XRAY = "xray"
AUTO = "auto"

# Strategies each engine can serve (subset the adapters implement in Phase 04).
ENGINE_STRATEGIES: dict[str, set[str]] = {
    SINGBOX: {"latency", "random", "roundRobin"},
    XRAY: {"latency", "random", "roundRobin", "leastLoad"},
}


def engine_for_kind(kind: str) -> str:
    """Preferred engine for a protocol kind ('auto' where both engines work)."""
    if kind == "ssr":
        return XRAY
    if kind in ("hysteria2", "tuic"):
        return SINGBOX
    return AUTO


def resolve_engine(
    kind: str, strategy: str = "", explicit: str = "", default: str = SINGBOX
) -> str:
    """Resolve the engine for a single profile.

    Order: explicit choice, then kind-required engine, then strategy-required
    engine (leastLoad -> xray), then the configured default.
    """
    if explicit and explicit != AUTO:
        return explicit
    kind_engine = engine_for_kind(kind)
    if kind_engine != AUTO:
        return kind_engine
    if strategy == "leastLoad":
        return XRAY
    return default


def strategy_supported(engine: str, strategy: str) -> bool:
    return strategy in ENGINE_STRATEGIES.get(engine, set())


# -- shared profile validation -------------------------------------------


def _require_text(value: Any, label: str) -> None:
    """Raise if *value* is not a non-empty string."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} is required")


def _require_positive_int(value: Any, label: str) -> int:
    """Raise if *value* is not a positive integer; return the normalized int."""
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        raise ValueError(f"{label} must be a positive integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a positive integer") from exc
    if normalized <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return normalized


def _validate_endpoint(host: Any, port: Any, label: str) -> None:
    """Validate a host/port pair."""
    if not isinstance(host, str) or not host.strip():
        raise ValueError(f"{label} server address is required")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError(f"{label} server port must be between 1 and 65535")


def _validate_wireguard_network(value: str, label: str, *, interface: bool = False) -> None:
    """Validate a WireGuard CIDR."""
    import ipaddress

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"wireguard {label} must be a CIDR")
    try:
        if interface:
            ipaddress.ip_interface(value)
        else:
            ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise ValueError(f"wireguard {label} must be a CIDR") from exc


def _validate_wireguard_endpoint(endpoint: Any) -> None:
    """Validate a WireGuard peer endpoint (host:port)."""
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ValueError("wireguard peer endpoint must be host:port")
    value = endpoint.strip()
    if value.startswith("["):
        end = value.find("]")
        host = value[1:end] if end > 1 else ""
        port_text = value[end + 2 :] if end >= 0 and value[end + 1 :].startswith(":") else ""
    else:
        host, separator, port_text = value.rpartition(":")
        if not separator:
            host, port_text = "", ""
    try:
        port = int(port_text)
    except (TypeError, ValueError) as exc:
        raise ValueError("wireguard peer endpoint must be host:port") from exc
    if not host.strip() or not 1 <= port <= 65535:
        raise ValueError("wireguard peer endpoint must be host:port")


from .base import EngineAdapter, get_adapter, register  # noqa: E402,F401
from . import singbox, xray  # noqa: E402,F401  (registers adapters)
