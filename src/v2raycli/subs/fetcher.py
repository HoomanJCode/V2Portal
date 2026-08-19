"""Subscription fetching (HTTP, file://, paste://)."""

from __future__ import annotations

from pathlib import Path

import httpx


class FetchError(Exception):
    """A typed failure while fetching a subscription."""


def fetch(url: str, user_agent: str | None = None) -> tuple[str, dict]:
    """Return ``(body, headers)`` for a subscription URL.

    Supports ``https://``/``http://`` (via httpx), ``file://`` (local path),
    and ``paste://<payload>`` (inline payload). Header keys are lowercased.
    """
    if url.startswith("paste://"):
        return url[len("paste://") :], {}
    if url.startswith("file://"):
        path = Path(url[len("file://") :])
        if not path.exists():
            raise FetchError(f"file not found: {path}")
        return path.read_text(encoding="utf-8", errors="replace"), {}

    headers = {"User-Agent": user_agent} if user_agent else {}
    try:
        with httpx.Client(follow_redirects=True, timeout=30.0, headers=headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text, {k.lower(): v for k, v in resp.headers.items()}
    except httpx.TimeoutException:
        raise FetchError("request timed out") from None
    except httpx.ConnectError as exc:
        raise FetchError(f"connection failed: {exc}") from exc
    except httpx.HTTPStatusError as exc:
        raise FetchError(f"http {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise FetchError(str(exc)) from exc
