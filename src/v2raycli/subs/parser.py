"""Subscription payload parsing, import, and update."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone

from ..models import Profile, Subscription, now_iso
from ..outbounds.manual import ALLOWED_MANUAL_PROTOCOLS, add_manual_config
from . import fetcher
from .share import ShareLinkError, decode_link


def _try_b64(text: str) -> str | None:
    """Return decoded text if ``text`` is a base64 blob of share links."""
    t = "".join(text.split()).replace("-", "+").replace("_", "/")
    t += "=" * (-len(t) % 4)
    try:
        raw = base64.b64decode(t)
    except (ValueError, TypeError):
        return None
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if "\n" in decoded or "://" in decoded or decoded.lstrip().startswith("vmess"):
        return decoded
    return None


def parse_payload(body: str) -> list[str]:
    """Turn a subscription body into a list of share-link strings.

    Handles a plain newline list or a base64-encoded blob (std/url-safe,
    padded/unpadded), tolerating a BOM, stray whitespace, and blank lines.
    """
    if not isinstance(body, str):
        raise ValueError("subscription payload must be text")
    text = body.lstrip("\ufeff").strip()
    if not text:
        return []
    decoded = _try_b64(text)
    if decoded is not None:
        text = decoded
    return [line.strip() for line in text.splitlines() if line.strip()]


def _json_entries(body: str) -> list[dict] | None:
    """Return Xray JSON subscription entries, or None for link payloads."""
    text = body.lstrip(chr(0xFEFF)).strip()
    if not text.startswith(("{", "[")):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON subscription payload: {exc.msg}") from exc
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("JSON subscription payload must contain config objects")
    return payload


def _json_profile(entry: dict, index: int) -> Profile:
    """Convert one v2rayN/Xray config object into an Xray manual profile."""
    candidates = entry.get("outbounds") if "outbounds" in entry else [entry]
    if not isinstance(candidates, list):
        raise ValueError("outbounds must be a list")
    outbound = next(
        (
            item
            for item in candidates
            if isinstance(item, dict) and item.get("protocol") in ALLOWED_MANUAL_PROTOCOLS
        ),
        None,
    )
    if outbound is None:
        raise ValueError("config has no supported proxy outbound")
    name = (
        entry.get("remarks")
        or entry.get("remark")
        or entry.get("name")
        or outbound.get("tag")
        or f"json-node-{index + 1}"
    )
    if not isinstance(name, str) or not name.strip():
        name = f"json-node-{index + 1}"
    clean_outbound = {key: value for key, value in outbound.items() if key != "tag"}
    profile = add_manual_config(json.dumps(clean_outbound), name.strip(), engine="xray")
    identity = json.dumps(clean_outbound, sort_keys=True, separators=(",", ":"))
    profile.share_link = "xray-json://" + hashlib.sha256(identity.encode()).hexdigest()
    return profile


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
    if not isinstance(headers, dict):
        return 0, None
    value = headers.get("subscription-userinfo")
    if not isinstance(value, str) or not value.strip():
        return 0, None
    fields: dict = {}
    for part in value.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            fields[k.strip().lower()] = v.strip()

    def counter(name: str) -> int:
        value = fields.get(name, "0")
        if not isinstance(value, str) or not value.isdigit():
            return 0
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return 0

    traffic = counter("upload") + counter("download")
    expires = None
    expire = fields.get("expire")
    if isinstance(expire, str) and expire.isdigit():
        try:
            expires = datetime.fromtimestamp(int(expire), tz=timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            expires = None
    return traffic, expires


def _build(sub_id: str, url: str, user_agent: str | None, proxy: str | None = None) -> tuple[list[Profile], list[str], int, str | None]:
    body, headers = fetcher.fetch(url, user_agent, proxy=proxy)
    entries = _json_entries(body)
    profiles: list[Profile] = []
    errors: list[str] = []
    seen: set = set()
    if entries is not None:
        for index, entry in enumerate(entries):
            try:
                profile = _json_profile(entry, index)
            except (TypeError, ValueError) as exc:
                errors.append(f"json node {index + 1}: {exc}")
                continue
            key = _profile_key(profile)
            if key in seen:
                continue
            seen.add(key)
            profile.source = "subscription"
            profile.subscription_id = sub_id
            profiles.append(profile)
    else:
        links = parse_payload(body)
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
    name: str, url: str, user_agent: str | None = None, proxy: str | None = None,
) -> tuple[Subscription, list[Profile], list[str]]:
    """Fetch + parse a subscription into a Subscription and Profiles.

    Does not mutate storage; the caller adds the returned objects.
    """
    sub = Subscription(name=name, url=url, user_agent=user_agent)
    profiles, errors, traffic, expires = _build(sub.id, url, user_agent, proxy=proxy)
    sub.profile_ids = [p.id for p in profiles]
    sub.last_updated = now_iso()
    sub.traffic_used = traffic
    sub.expires = expires
    return sub, profiles, errors


def update_subscription(store, sub_id: str, proxy: str | None = None) -> tuple[list[Profile], list[str]]:
    """Re-fetch a subscription and reconcile it in place.

    Preserves names of unchanged nodes (matched by share link), deletes nodes
    that vanished upstream, and prunes deleted ids from any group.
    """
    sub = store.get_subscription(sub_id)
    if sub is None:
        raise ValueError(f"subscription not found: {sub_id}")

    existing = {p.share_link: p for p in store.config.profiles if p.subscription_id == sub_id}
    profiles, errors, traffic, expires = _build(sub_id, sub.url, sub.user_agent, proxy=proxy)
    if existing and errors and not profiles:
        raise ValueError(
            "subscription payload contained no valid profiles; keeping existing nodes"
        )

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

    store.notify_destructive("subscription-update")
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


def is_stale(sub: Subscription, now: datetime | None = None) -> bool:
    """True if ``sub`` should be auto-updated.

    A subscription is stale when it is enabled, has a positive
    ``auto_update_days``, and has never been updated or its last update is
    older than that many days.
    """
    if not sub.enabled or sub.auto_update_days <= 0:
        return False
    if not sub.last_updated:
        return True
    try:
        updated = datetime.fromisoformat(sub.last_updated)
    except ValueError:
        return True
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - updated).total_seconds() >= sub.auto_update_days * 86400


def auto_update_subscriptions(store, now: datetime | None = None) -> list[dict]:
    """Update every stale subscription; return per-subscription results.

    Fetch errors are captured per subscription (``updated=False`` + ``error``)
    so one failing URL never blocks the others. Callers should ``store.save()``
    if any result has ``updated=True``.
    """
    proxy = store.config.settings.subscription_proxy or None
    results: list[dict] = []
    for sub in list(store.config.subscriptions):
        if not is_stale(sub, now):
            continue
        try:
            update_subscription(store, sub.id, proxy=proxy)
            results.append(
                {"subscription_id": sub.id, "name": sub.name, "updated": True, "error": None}
            )
        except Exception as exc:  # noqa: BLE001 - isolate per-subscription failures
            results.append(
                {
                    "subscription_id": sub.id,
                    "name": sub.name,
                    "updated": False,
                    "error": str(exc),
                }
            )
    return results
