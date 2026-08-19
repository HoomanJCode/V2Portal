"""Engine selection helpers shared across v2raycli."""

from __future__ import annotations

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


from .base import EngineAdapter, get_adapter, register  # noqa: E402,F401
from . import singbox, xray  # noqa: E402,F401  (registers adapters)
