"""Subscription fetching (HTTP, file://, paste://)."""

from __future__ import annotations

from pathlib import Path

import httpx

from ..errors import V2RayCLIError


DEFAULT_USER_AGENT = "v2rayN/6.23"


class FetchError(V2RayCLIError):
    """A typed failure while fetching a subscription."""


def fetch(url: str, user_agent: str | None = None, proxy: str | None = None) -> tuple[str, dict]:
    """Return ``(body, headers)`` for a subscription URL.

    Supports ``https://``/``http://`` (via httpx), ``file://`` (local path),
    and ``paste://<payload>`` (inline payload). Header keys are lowercased.
    When *proxy* is given (e.g. ``socks5://127.0.0.1:1080``), HTTP requests
    are routed through it.
    """
    if not isinstance(url, str) or not url.strip():
        raise FetchError("subscription URL must be non-empty text")
    url = url.strip()
    if user_agent is not None and not isinstance(user_agent, str):
        raise FetchError("subscription user agent must be text")
    if proxy is not None and not isinstance(proxy, str):
        raise FetchError("proxy must be text")
    if url.startswith("paste://"):
        return url[len("paste://") :], {}
    if url.startswith("file://"):
        path = Path(url[len("file://") :])
        if not path.exists():
            raise FetchError(f"file not found: {path}")
        try:
            return path.read_text(encoding="utf-8", errors="replace"), {}
        except OSError as exc:
            raise FetchError(f"could not read subscription file: {path}") from exc
    if not url.startswith(("http://", "https://")):
        raise FetchError("unsupported subscription URL scheme")

    headers = {"User-Agent": user_agent or DEFAULT_USER_AGENT}
    client_opts: dict = {"follow_redirects": True, "timeout": 30.0, "headers": headers}
    if proxy:
        client_opts["proxy"] = proxy
    try:
        with httpx.Client(**client_opts) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text, {k.lower(): v for k, v in resp.headers.items()}
    except httpx.TimeoutException:
        raise FetchError("request timed out — check your network or proxy") from None
    except httpx.ConnectError as exc:
        # Strip verbose SSL/library details — the proxy URL is enough context.
        msg = str(exc).split(": ", 1)[-1].split("\n")[0]
        hint = f" (proxy: {proxy})" if proxy else ""
        raise FetchError(f"connection failed — {msg}{hint}") from exc
    except httpx.HTTPStatusError as exc:
        raise FetchError(f"http {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        # Keep the message short — strip verbose httpcore/h11 internals.
        msg = str(exc).split("\n")[0].strip()
        if len(msg) > 200:
            msg = msg[:197] + "..."
        raise FetchError(msg) from exc
