"""Base exception hierarchy for v2raycli.

All project-specific exceptions inherit from :class:`V2RayCLIError`, making
it easy for top-level handlers to catch every application error with a single
``except V2RayCLIError`` clause.

Subclasses that also inherit from a stdlib exception (e.g. ``ValueError``)
preserve backward compatibility so existing ``except ValueError`` handlers
keep working.
"""

from __future__ import annotations


class V2RayCLIError(Exception):
    """Base class for all v2raycli application errors."""
