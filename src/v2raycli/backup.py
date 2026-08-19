"""Automatic rolling backups of the config, plus restore.

Backups are timestamped snapshots of the whole config JSON, stored in
``BACKUP_DIR``. Destructive operations trigger one via the ``ConfigStore``
pre-write hook (see ``install_backup_hook``).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import config
from .models import Config

_BACKUP_RE = re.compile(r"^backup-(\d{8}-\d{6}-\d{6})-(.+)\.json$")


@dataclass
class BackupInfo:
    path: str
    timestamp: str  # YYYYmmdd-HHMMSS-ffffff
    reason: str
    size: int


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def _safe_reason(reason: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", reason or "manual").strip("-") or "manual"


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="backup-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def create_backup(
    reason: str, store=None, backup_dir=None, keep: int | None = None
) -> Path | None:
    """Snapshot the current config into a timestamped backup file.

    Uses the in-memory ``store.config`` when a store is given (so the snapshot
    reflects the pre-mutation state), else falls back to ``CONFIG_PATH`` on
    disk. Returns the created path, or ``None`` if there is nothing to back up.
    """
    directory = Path(backup_dir) if backup_dir is not None else config.BACKUP_DIR
    if store is not None:
        data = store.config.to_dict()
    elif config.CONFIG_PATH.exists():
        data = json.loads(config.CONFIG_PATH.read_text(encoding="utf-8"))
    else:
        return None
    path = directory / f"backup-{_timestamp()}-{_safe_reason(reason)}.json"
    _atomic_write(path, data)
    if keep is not None:
        prune(keep, directory)
    return path


def list_backups(backup_dir=None) -> list[BackupInfo]:
    """List backups, newest first."""
    directory = Path(backup_dir) if backup_dir is not None else config.BACKUP_DIR
    if not directory.exists():
        return []
    results: list[BackupInfo] = []
    for path in directory.glob("backup-*.json"):
        match = _BACKUP_RE.match(path.name)
        if not match:
            continue
        results.append(
            BackupInfo(
                path=str(path),
                timestamp=match.group(1),
                reason=match.group(2),
                size=path.stat().st_size,
            )
        )
    results.sort(key=lambda b: b.timestamp, reverse=True)
    return results


def prune(keep: int, backup_dir=None) -> None:
    """Keep only the newest ``keep`` backups; delete the rest."""
    if keep <= 0:
        return
    directory = Path(backup_dir) if backup_dir is not None else config.BACKUP_DIR
    for info in list_backups(directory)[keep:]:
        try:
            Path(info.path).unlink()
        except OSError:
            pass


def restore_backup(path, store, backup_dir=None) -> Config:
    """Replace the current config with a backup, saving a safety backup first."""
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"backup not found: {source}")
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != config.SCHEMA_VERSION:
            raise ValueError("not a valid v2raycli backup")
        restored = Config.from_dict(data)
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
        if isinstance(exc, ValueError) and str(exc) == "not a valid v2raycli backup":
            raise
        raise ValueError(f"invalid backup: {exc}") from exc

    create_backup("pre-restore", store=store, backup_dir=backup_dir)
    store.config = restored
    store.save()
    return store.config


def install_backup_hook(store, backup_dir=None) -> None:
    """Auto-backup before destructive mutations, honoring ``backup_keep``."""

    def hook(s, reason: str) -> None:
        keep = s.config.settings.backup_keep
        create_backup(reason, store=s, backup_dir=backup_dir, keep=keep)

    store.register_pre_write_hook(hook)


def set_private_permissions() -> None:
    """Set the config dir and BACKUP_DIR to 0700 on POSIX (no-op on Windows)."""
    if os.name == "nt":
        return
    for directory in (config.CONFIG_PATH.parent, config.BACKUP_DIR):
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
