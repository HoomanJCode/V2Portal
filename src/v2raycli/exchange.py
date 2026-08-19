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
from .storage import _validate_persisted_shape
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
    "inline",
    "auth_hint",
}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _redact(value, in_users: bool = False):
    """Recursively mask credentials/keys; returns a new structure."""
    if isinstance(value, dict):
        result: dict = {}
        for key, item in value.items():
            if key in _SECRET_KEYS:
                result[key] = "REDACTED"
            elif key == "id" and in_users:
                result[key] = "REDACTED"
            else:
                result[key] = _redact(item, in_users or key == "users")
        return result
    if isinstance(value, list):
        return [_redact(item, in_users) for item in value]
    return value


def export_full(store, path=None, redact: bool = False) -> dict:
    """Return (and optionally write) a portable full-config export."""
    data = store.config.to_dict()
    if redact:
        data = _redact(data)
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


def _merge_config(current: Config, incoming: Config) -> None:
    profiles = list(current.profiles)
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

    current.profiles = profiles

    for sub in incoming.subscriptions:
        index = _index_of_id(current.subscriptions, sub.id)
        if index is not None:
            current.subscriptions[index] = sub
        else:
            current.subscriptions.append(sub)

    for group in incoming.groups:
        index = _index_of_id(current.groups, group.id)
        if index is not None:
            current.groups[index] = group
        else:
            current.groups.append(group)

    for name, options in incoming.engines.items():
        current.engines.setdefault(name, {}).update(options)

    _relink_config(current)


def _merge(store, incoming: Config) -> None:
    _merge_config(store.config, incoming)


def _relink_config(current: Config) -> None:
    profile_ids = {p.id for p in current.profiles}
    for sub in current.subscriptions:
        sub.profile_ids = [pid for pid in sub.profile_ids if pid in profile_ids]
    for group in current.groups:
        group.profile_ids = [pid for pid in group.profile_ids if pid in profile_ids]


def _relink(store) -> None:
    _relink_config(store.config)


def _load_full_config(path) -> Config:
    """Read and validate an exported config before any store mutation."""
    try:
        source = Path(path)
        text = source.read_text(encoding="utf-8")
    except (OSError, TypeError, ValueError, UnicodeError) as exc:
        raise ValueError(f"could not read export: {exc}") from exc
    try:
        raw = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid export JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("export must be a JSON object")
    if raw.get("schema_version") != config.SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version: {raw.get('schema_version')}")
    try:
        _validate_persisted_shape(raw)
        return Config.from_dict(raw)
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise ValueError(f"invalid export: {exc}") from exc


def import_full(store, path, mode: str = "merge", backup_dir=None) -> Config:
    """Import a full-config export file.

    ``mode="merge"`` combines collections (keep existing on dedupe conflicts);
    ``mode="replace"`` backs up the current config then loads the file
    wholesale.
    """
    incoming = _load_full_config(path)

    if mode == "replace":
        create_backup(
            "import-replace",
            store=store,
            backup_dir=backup_dir,
            keep=store.config.settings.backup_keep,
        )
        store.config = incoming
        store.save()
        return store.config

    if mode != "merge":
        raise ValueError(f"unknown import mode: {mode}")

    candidate = Config.from_dict(store.config.to_dict())
    _merge_config(candidate, incoming)
    if candidate.to_dict() != store.config.to_dict():
        store.notify_destructive("import-merge")
        store.config = candidate
        store.save()
    else:
        # Avoid rewriting the file or creating a backup for a true no-op.
        return store.config
    return store.config


def import_share_links(store, path_or_text: str) -> list[Profile]:
    """Import profiles from a file of share links, or from raw link text."""
    if not isinstance(path_or_text, str):
        return []

    text = path_or_text
    try:
        candidate = Path(path_or_text)
        is_file = candidate.is_file()
    except (OSError, ValueError):
        # Long or otherwise invalid path-like text is still valid input to the
        # share-link parser; do not let the filesystem probe reject it.
        is_file = False
    if is_file:
        text = candidate.read_text(encoding="utf-8")

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
        existing.add(key)
        added.append(profile)

    if added:
        store.notify_destructive("import-share-links")
        for profile in added:
            store.add_profile(profile)
        store.save()
    return added
