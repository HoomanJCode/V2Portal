"""Subscription payload parsing, import, and update."""

from __future__ import annotations

import base64
from datetime import datetime, timezone

from ..models import Profile, Subscription, now_iso
from . import fetcher
from .share import ShareLinkError, decode_link


def _try_b64(text: str) -> str | None:
    """Return decoded text if ``text`` is a base64 blob of share links."""
    t = "".join(text.split()).replace("-", "+").replace("_", "/")
    t += "=" * (-len(t) % 4)
    try:
        raw = base64.b64decode(t)
    except Exception:
        return None
    try:
        decoded = raw.decode("utf-8")
    except Exception:
        return None
    if "\n" in decoded or "://" in decoded or decoded.lstrip().startswith("vmess"):
        return decoded
    return None


def parse_payload(body: str) -> list[str]:
    """Turn a subscription body into a list of share-link strings.

    Handles a plain newline list or a base64-encoded blob (std/url-safe,
    padded/unpadded), tolerating a BOM, stray whitespace, and blank lines.
    """
    text = body.lstrip("\ufeff").strip()
    if not text:
        return []
    decoded = _try_b64(text)
    if decoded is not None:
        text = decoded
    return [line.strip() for line in text.splitlines() if line.strip()]


def _profile_key(p: Profile) -> tuple:
    """Best-effort dedupe key: (kind, host, port, credential)."""
    outbound = p.outbound
    settings = outbound.get("settings", {})
    servers = settings.get("servers") or settings.get("vnext")
    if servers:
        first = servers[0]
        host = first.get("address", "")
        port = first.get("port", "")
        cred = ""
        for u in first.get("users") or []:
            cred += u.get("id") or u.get("password") or u.get("user") or ""
        if not cred:
            cred = first.get("password") or first.get("id") or first.get("uuid") or ""
        return (p.kind, host, port, cred)
    if "server" in outbound:
        return (
            p.kind,
            outbound.get("server", ""),
            outbound.get("server_port", ""),
            outbound.get("password") or outbound.get("uuid") or "",
        )
    return (p.kind, p.name, "", "")


def _userinfo(headers: dict) -> tuple[int, str | None]:
    """Parse the Subscription-Userinfo header into (traffic_used, expires)."""
    value = headers.get("subscription-userinfo")
    if not value:
        return 0, None
    fields: dict = {}
    for part in value.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            fields[k.strip().lower()] = v.strip()
    traffic = 0
    try:
        traffic = int(fields.get("upload", 0)) + int(fields.get("download", 0))
    except (TypeError, ValueError):
        traffic = 0
    expires = None
    expire = fields.get("expire")
    if expire and expire.isdigit():
        try:
            expires = datetime.fromtimestamp(int(expire), tz=timezone.utc).isoformat()
        except (ValueError, OSError):
            expires = None
    return traffic, expires


def _build(sub_id: str, url: str, user_agent: str | None) -> tuple[list[Profile], list[str], int, str | None]:
    body, headers = fetcher.fetch(url, user_agent)
    links = parse_payload(body)
    profiles: list[Profile] = []
    errors: list[str] = []
    seen: set = set()
    for link in links:
        try:
            profile = decode_link(link)
        except ShareLinkError as exc:
            errors.append(f"{link[:40]}: {exc}")
            continue
        key = _profile_key(profile)
        if key in seen:
            continue
        seen.add(key)
        profile.source = "subscription"
        profile.subscription_id = sub_id
        profiles.append(profile)
    traffic, expires = _userinfo(headers)
    return profiles, errors, traffic, expires


def import_subscription(
    name: str, url: str, user_agent: str | None = None
) -> tuple[Subscription, list[Profile], list[str]]:
    """Fetch + parse a subscription into a Subscription and Profiles.

    Does not mutate storage; the caller adds the returned objects.
    """
    sub = Subscription(name=name, url=url, user_agent=user_agent)
    profiles, errors, traffic, expires = _build(sub.id, url, user_agent)
    sub.profile_ids = [p.id for p in profiles]
    sub.last_updated = now_iso()
    sub.traffic_used = traffic
    sub.expires = expires
    return sub, profiles, errors


def update_subscription(store, sub_id: str) -> tuple[list[Profile], list[str]]:
    """Re-fetch a subscription and reconcile it in place.

    Preserves names of unchanged nodes (matched by share link), deletes nodes
    that vanished upstream, and prunes deleted ids from any group.
    """
    sub = store.get_subscription(sub_id)
    if sub is None:
        raise ValueError(f"subscription not found: {sub_id}")

    existing = {p.share_link: p for p in store.config.profiles if p.subscription_id == sub_id}
    profiles, errors, traffic, expires = _build(sub_id, sub.url, sub.user_agent)

    for profile in profiles:
        old = existing.get(profile.share_link)
        if old is not None:
            profile.id = old.id
            profile.name = old.name or profile.name

    new_links = {p.share_link for p in profiles}
    removed_ids = [
        p.id
        for p in store.config.profiles
        if p.subscription_id == sub_id and p.share_link not in new_links
    ]

    store.config.profiles = [
        p for p in store.config.profiles if p.subscription_id != sub_id
    ] + profiles
    for group in store.config.groups:
        group.profile_ids = [pid for pid in group.profile_ids if pid not in removed_ids]

    sub.profile_ids = [p.id for p in profiles]
    sub.last_updated = now_iso()
    sub.traffic_used = traffic
    sub.expires = expires
    return profiles, errors
