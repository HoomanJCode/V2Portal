# Phase 09 — Backup, Export & Import

Goal: automatic rolling backups of the whole config, plus full-config and
share-link export/import for migration, sharing, and disaster recovery.

## Tasks

### Backup (`backup.py`)

- [ ] `create_backup(reason) -> path` — atomically copy `config.json` to
      `BACKUP_DIR/backup-<YYYYmmdd-HHMMSS>-<reason>.json`.
- [ ] Hook into destructive operations via the storage pre-write hook:
      subscription update, profile/group removal, import, restore.
- [ ] Retention: keep the last `settings.backup_keep` backups, prune older.
- [ ] `list_backups() -> list[BackupInfo]` (timestamp, reason, size).
- [ ] `restore_backup(path)` — create a safety backup of the current config,
      then replace it with the selected backup and reload storage.
- [ ] Set config dir (and `BACKUP_DIR`) permissions to `0700` on POSIX.

### Export (`exchange.py`)

- [ ] `export_full(path, redact=False) -> dict` — portable JSON with
      `schema_version`, settings, routing, profiles, subscriptions, groups;
      when `redact=True`, mask passwords/uuid/private keys (share-safe).
- [ ] `export_share_links(profile_ids, path)` — newline-separated share-link
      file via `subs.share.encode_link` (skip profiles that can't encode).
- [ ] `import_full(path, mode="merge")`:
  - validate `schema_version` and structure; reject malformed files cleanly
  - `merge`: add/update by profile id, dedupe by (protocol, host, port,
    credential), keep existing on conflict (or ask in TUI)
  - `replace`: back up current config, then load the imported file wholesale
  - re-link subscriptions → their profiles by id
- [ ] `import_share_links(path_or_text)` — reuse the subscription payload parser
      to create profiles from a list of links.

### TUI wiring (with Phase 06)

- [ ] Manage → **Transfer** menu actions reach the above:
      backup now, restore (list + pick), export full (redacted or not),
      import (full or share-link file), export share links.

## Tests

- [ ] `test_backup.py`: snapshot creation; retention pruning; restore creates a
      safety backup first; `0700` perms (POSIX-only assertion).
- [ ] `test_exchange.py`: export→import round-trip is lossless; redacted export
      contains no secrets; merge dedupe/conflict; replace backs up first;
      share-link export matches `encode_link` output.

## Definition of Done

- [ ] A full export→import round-trip reproduces an identical config.
- [ ] Destructive ops automatically leave a recoverable backup.
- [ ] Redacted exports contain no credentials/keys.
- [ ] `pytest` passes.
