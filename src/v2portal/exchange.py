"""Full-config and share-link export/import.

``export_full``/``import_full`` move the whole config between machines.
``redact=True`` produces a share-safe copy with credentials/keys masked.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import config
from .backup import create_backup
from .models import Config, Profile
from .storage import _validate_persisted_shape, migrate_config
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
    "subscription_proxy",
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
        is_subscription = "url" in value and "profile_ids" in value and "auto_update_days" in value
        for key, item in value.items():
            if key in _SECRET_KEYS or (key == "url" and is_subscription):
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
    current_types = {}
    for entity_type, items in (
        ("profile", current.profiles),
        ("subscription", current.subscriptions),
        ("group", current.groups),
        ("server", current.servers),
        ("routing rule", current.routing.rules),
    ):
        current_types.update({item.id: entity_type for item in items})
    for entity_type, items in (
        ("profile", incoming.profiles),
        ("subscription", incoming.subscriptions),
        ("group", incoming.groups),
        ("server", incoming.servers),
        ("routing rule", incoming.routing.rules),
    ):
        for item in items:
            existing_type = current_types.get(item.id)
            if existing_type is not None and existing_type != entity_type:
                raise ValueError(
                    f"entity id {item.id} belongs to an existing {existing_type}, "
                    f"cannot import it as a {entity_type}"
                )

    profiles = list(current.profiles)
    keys = {_profile_key(p) for p in profiles}
    profile_id_map: dict[str, str] = {}

    for profile in incoming.profiles:
        key = _profile_key(profile)
        if key in keys:
            matches = [p for p in profiles if _profile_key(p) == key]
            existing = next(
                (p for p in matches if p.subscription_id == profile.subscription_id),
                None,
            )
            if existing is not None:
                profile_id_map[profile.id] = existing.id
                continue  # duplicate node from the same source; keep the existing profile
            if profile.subscription_id is None and matches:
                profile_id_map[profile.id] = matches[0].id
                continue  # duplicate manual profile; keep the existing profile
        index = _index_of_id(profiles, profile.id)
        if index is not None:
            keys.discard(_profile_key(profiles[index]))
            profiles[index] = profile  # same id but different key → update
            keys.add(key)
            continue
        profiles.append(profile)
        keys.add(key)

    current.profiles = profiles
    if profile_id_map:
        for sub in incoming.subscriptions:
            sub.profile_ids = [profile_id_map.get(pid, pid) for pid in sub.profile_ids]
        for group in incoming.groups:
            group.profile_ids = [profile_id_map.get(pid, pid) for pid in group.profile_ids]
        for server in incoming.servers:
            if server.outbound_type == "profile":
                server.outbound_id = profile_id_map.get(server.outbound_id, server.outbound_id)

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

    for server in incoming.servers:
        index = _index_of_id(current.servers, server.id)
        if index is not None:
            current.servers[index] = server
        else:
            current.servers.append(server)

    for rule in incoming.routing.rules:
        index = _index_of_id(current.routing.rules, rule.id)
        if index is not None:
            current.routing.rules[index] = rule
        else:
            current.routing.rules.append(rule)
    if incoming.routing.rules:
        current.routing.mode = incoming.routing.mode

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
    sv = raw.get("schema_version")
    if isinstance(sv, bool) or not isinstance(sv, int) or sv > config.SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version: {sv}")
    try:
        _validate_persisted_shape(raw)
        cfg = Config.from_dict(raw)
        # Migrate older schemas to the current version
        if sv < config.SCHEMA_VERSION:
            cfg = migrate_config(cfg, sv)
        return cfg
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
        store._init_seq_from_config()
        store.save()
        return store.config

    if mode != "merge":
        raise ValueError(f"unknown import mode: {mode}")

    candidate = Config.from_dict(store.config.to_dict())
    _merge_config(candidate, incoming)
    if candidate.to_dict() != store.config.to_dict():
        store.notify_destructive("import-merge")
        store.config = candidate
        store._init_seq_from_config()
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
