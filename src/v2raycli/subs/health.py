"""Subscription health: expiry and traffic accounting.

Turns the ``expires`` and ``traffic_used`` fields (populated from the
``Subscription-Userinfo`` header) into human-readable status for startup
warnings and the ``--health`` report.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..models import Subscription


def human_bytes(n: int | float | None) -> str:
    """Format a byte count as ``1.5 GiB`` (binary units)."""
    if n is None or n < 0:
        return "0 B"
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if value < 1024 or unit == "PiB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PiB"


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO timestamp, normalizing naive values to UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def subscription_status(sub: Subscription, now: datetime | None = None, warn_days: int = 7) -> dict:
    """Classify a subscription's expiry; return a status dict."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    expires = parse_iso(sub.expires)
    expired = expires is not None and expires <= now
    days_left = None
    expiring = False
    if expires is not None and not expired:
        days_left = (expires - now).days
        expiring = days_left <= warn_days

    return {
        "subscription_id": sub.id,
        "name": sub.name,
        "expired": expired,
        "expiring": expiring,
        "expires": expires,
        "days_left": days_left,
        "traffic_used": sub.traffic_used,
    }


def check_subscriptions(store, now: datetime | None = None, warn_days: int = 7) -> list[dict]:
    """Return status dicts for every enabled subscription."""
    return [
        subscription_status(sub, now, warn_days)
        for sub in store.config.subscriptions
        if sub.enabled
    ]
