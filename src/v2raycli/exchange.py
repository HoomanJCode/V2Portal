"""Full-config and share-link export/import.

``export_full``/``import_full`` move the whole config (settings, routing,
profiles, subscriptions, groups) between machines. ``redact=True`` produces a
share-safe copy with credentials/keys masked.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config
from .backup import create_backup
from .models import Config, Profile
from .subs.parser import _profile_key, parse_payload
from .subs.share import ShareLinkError, decode_link, encode_link

# Value keys that hold credentials/keys and must be masked on redacted export.
_SECRET_KEYS = {
    "password",
    "pass",
    "uuid",
    "user",
    "username",
    "secretKey",
    "private_key",
    "privateKey",
    "preSharedKey",
    "pre_shared_key",
    "preshared_key",
    "share_link",
}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def redact(value, in_users: bool = False):
    """Recursively mask credentials/keys; returns a new structure."""
    if isinstance(value, dict):
        result: dict = {}
        for key, item in value.items():
            if key in _SECRET_KEYS:
                result[key] = "REDACTED"
            elif key == "id" and in_users:
                result[key] = "REDACTED"
            else:
                result[key] = redact(item, in_users or key == "users")
        return result
    if isinstance(value, list):
        return [redact(item, in_users) for item in value]
    return value


def export_full(store, path=None, redact: bool = False) -> dict:
    """Return (and optionally write) a portable full-config export."""
    data = store.config.to_dict()
    if redact:
        data = redact(data)
    if path is not None:
        _write_json(Path(path), data)
    return data


def export_share_links(profiles: list[Profile], path) -> list[str]:
    """Write one share link per encodable profile; skip non-encodable kinds."""
    links: list[str] = []
    for profile in profiles:
        try:
            links.append(encode_link(profile))
        except ShareLinkError:
            continue
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(links) + ("\n" if links else ""), encoding="utf-8")
    return links


def _index_of_id(items, item_id: str) -> int | None:
    for index, item in enumerate(items):
        if getattr(item, "id", None) == item_id:
            return index
    return None


def _merge(store, incoming: Config) -> None:
    profiles = list(store.config.profiles)
    keys = {_profile_key(p) for p in profiles}

    for profile in incoming.profiles:
        index = _index_of_id(profiles, profile.id)
        if index is not None:
            profiles[index] = profile  # update by id
            continue
        key = _profile_key(profile)
        if key in keys:
            continue  # duplicate; keep the existing profile
        profiles.append(profile)
        keys.add(key)

    store.config.profiles = profiles

    for sub in incoming.subscriptions:
        index = _index_of_id(store.config.subscriptions, sub.id)
        if index is not None:
            store.config.subscriptions[index] = sub
        else:
            store.config.subscriptions.append(sub)

    for group in incoming.groups:
        index = _index_of_id(store.config.groups, group.id)
        if index is not None:
            store.config.groups[index] = group
        else:
            store.config.groups.append(group)

    for name, options in incoming.engines.items():
        store.config.engines.setdefault(name, {}).update(options)

    _relink(store)


def _relink(store) -> None:
    profile_ids = {p.id for p in store.config.profiles}
    for sub in store.config.subscriptions:
        sub.profile_ids = [pid for pid in sub.profile_ids if pid in profile_ids]
    for group in store.config.groups:
        group.profile_ids = [pid for pid in group.profile_ids if pid in profile_ids]


def import_full(store, path, mode: str = "merge") -> Config:
    """Import a full-config export file.

    ``mode="merge"`` combines collections (keep existing on dedupe conflicts);
    ``mode="replace"`` backs up the current config then loads the file
    wholesale.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("export must be a JSON object")
    if raw.get("schema_version") != config.SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version: {raw.get('schema_version')}")
    incoming = Config.from_dict(raw)

    if mode == "replace":
        create_backup("import-replace", store=store, keep=store.config.settings.backup_keep)
        store.config = incoming
        store.save()
        return store.config

    if mode != "merge":
        raise ValueError(f"unknown import mode: {mode}")

    _merge(store, incoming)
    store.save()
    return store.config


def import_share_links(store, path_or_text: str) -> list[Profile]:
    """Import profiles from a file of share links, or from raw link text."""
    candidate = Path(path_or_text)
    if candidate.is_file():
        text = candidate.read_text(encoding="utf-8")
    else:
        text = path_or_text

    existing = {_profile_key(p) for p in store.config.profiles}
    added: list[Profile] = []
    for link in parse_payload(text):
        try:
            profile = decode_link(link)
        except ShareLinkError:
            continue
        key = _profile_key(profile)
        if key in existing:
            continue
        profile.source = "manual"
        store.add_profile(profile)
        existing.add(key)
        added.append(profile)

    store.save()
    return added
