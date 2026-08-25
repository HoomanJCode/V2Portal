import json
import os
import stat
from pathlib import Path

import pytest

from v2raycli import backup, config
from v2raycli.models import Profile, RoutingRule
from v2raycli.storage import ConfigStore

SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}


def _store(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    return store


def test_create_backup_snapshot(tmp_path):
    store = _store(tmp_path)
    store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    store.save()

    path = backup.create_backup("manual", store=store, backup_dir=tmp_path / "b")

    assert path is not None
    assert path.exists()
    data = json.loads(path.read_text())
    assert data["profiles"][0]["name"] == "s"


def test_create_backup_returns_none_without_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "missing.json")
    assert backup.create_backup("manual", backup_dir=tmp_path / "b") is None


def test_list_backups_parses_timestamp_reason(tmp_path):
    store = _store(tmp_path)
    path = backup.create_backup("remove-profile", store=store, backup_dir=tmp_path / "b")

    infos = backup.list_backups(tmp_path / "b")
    assert len(infos) == 1
    assert infos[0].path == str(path)
    assert infos[0].reason == "remove-profile"
    assert infos[0].size > 0


def test_prune_keeps_newest(tmp_path, monkeypatch):
    bdir = tmp_path / "b"
    store = _store(tmp_path)
    stamps = iter(["20260101-000000-000001", "20260102-000000-000001", "20260103-000000-000001"])
    monkeypatch.setattr(backup, "_timestamp", lambda: next(stamps))

    for reason in ("a", "b", "c"):
        backup.create_backup(reason, store=store, backup_dir=bdir)

    backup.prune(2, bdir)
    assert [b.reason for b in backup.list_backups(bdir)] == ["c", "b"]


def test_restore_creates_safety_backup_first(tmp_path):
    bdir = tmp_path / "b"
    store = _store(tmp_path)
    store.add_profile(Profile(name="old", kind="socks", outbound=SOCKS))
    store.save()

    store.add_profile(Profile(name="new", kind="socks", outbound=SOCKS))
    path = backup.create_backup("snapshot", store=store, backup_dir=bdir)

    store.config.profiles = [store.config.profiles[0]]  # back to "old"
    store.save()

    backup.restore_backup(path, store, backup_dir=bdir)

    assert [p.name for p in store.config.profiles] == ["old", "new"]
    safety = [b for b in backup.list_backups(bdir) if b.reason == "pre-restore"]
    assert len(safety) == 1
    data = json.loads(Path(safety[0].path).read_text())
    assert [p["name"] for p in data["profiles"]] == ["old"]


def test_restore_rejects_unsupported_schema_before_safety_backup(tmp_path):
    bdir = tmp_path / "b"
    store = _store(tmp_path)
    store.add_profile(Profile(name="old", kind="socks", outbound=SOCKS))
    store.save()
    path = bdir / "bad.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"schema_version": 999}))

    with pytest.raises(ValueError, match="valid v2raycli backup"):
        backup.restore_backup(path, store, backup_dir=bdir)

    assert [p.name for p in store.config.profiles] == ["old"]
    assert backup.list_backups(bdir) == []


def test_restore_rejects_invalid_path_before_safety_backup(tmp_path):
    bdir = tmp_path / "b"
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="invalid backup path"):
        backup.restore_backup(None, store, backup_dir=bdir)

    assert backup.list_backups(bdir) == []


def test_restore_rejects_malformed_shape_before_safety_backup(tmp_path):
    bdir = tmp_path / "b"
    store = _store(tmp_path)
    store.add_profile(Profile(name="old", kind="socks", outbound=SOCKS))
    store.save()
    path = bdir / "bad.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"schema_version": 2, "profiles": [{"outbound": []}]}))

    with pytest.raises(ValueError, match="invalid backup"):
        backup.restore_backup(path, store, backup_dir=bdir)

    assert [p.name for p in store.config.profiles] == ["old"]
    assert backup.list_backups(bdir) == []


def test_hook_fires_on_destructive_op(tmp_path):
    bdir = tmp_path / "b"
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    store.save()
    backup.install_backup_hook(store, backup_dir=bdir)

    store.remove_profile(profile.id)

    assert any(b.reason == "remove-profile" for b in backup.list_backups(bdir))


def test_rule_removal_fires_backup_hook(tmp_path):
    bdir = tmp_path / "b"
    store = _store(tmp_path)
    rule = store.add_rule(RoutingRule(action="direct"))
    backup.install_backup_hook(store, backup_dir=bdir)

    assert store.remove_rule(rule.id) is True
    assert any(b.reason == "remove-rule" for b in backup.list_backups(bdir))


def test_missing_rule_does_not_fire_backup_hook(tmp_path):
    bdir = tmp_path / "b"
    store = _store(tmp_path)
    backup.install_backup_hook(store, backup_dir=bdir)

    assert store.remove_rule("missing") is False
    assert backup.list_backups(bdir) == []


def test_missing_group_does_not_fire_backup_hook(tmp_path):
    bdir = tmp_path / "b"
    store = _store(tmp_path)
    backup.install_backup_hook(store, backup_dir=bdir)

    assert store.remove_group("missing") == {}
    assert backup.list_backups(bdir) == []


def test_hook_honors_backup_keep(tmp_path):
    bdir = tmp_path / "b"
    store = _store(tmp_path)
    store.config.settings.backup_keep = 2
    backup.install_backup_hook(store, backup_dir=bdir)

    for name in ("a", "b", "c"):
        p = store.add_profile(Profile(name=name, kind="socks", outbound=SOCKS))
        store.remove_profile(p.id)

    assert len(backup.list_backups(bdir)) == 2


def test_set_private_permissions_posix(tmp_path, monkeypatch):
    if os.name == "nt":
        pytest.skip("POSIX only")
    base = tmp_path / "cfg"
    bdir = tmp_path / "b"
    base.mkdir()
    bdir.mkdir()
    monkeypatch.setattr(config, "CONFIG_PATH", base / "config.json")
    monkeypatch.setattr(config, "BACKUP_DIR", bdir)

    backup.set_private_permissions()

    assert stat.S_IMODE(base.stat().st_mode) == 0o700
    assert stat.S_IMODE(bdir.stat().st_mode) == 0o700
