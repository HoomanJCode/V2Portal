"""Subscription fetching and share-link parsing for v2portal."""

from __future__ import annotations

import base64


def _b64decode(s: str) -> bytes:
    """Decode base64, tolerating url-safe chars and missing padding."""
    s = "".join(s.split()).replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)
