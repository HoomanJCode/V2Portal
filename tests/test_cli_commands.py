from __future__ import annotations

import json

from v2raycli import app
from v2raycli.models import Profile, Subscription
from v2raycli.storage import ConfigStore

SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}


def _store(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    return store


def test_parser_exposes_command_tree():
    args = app.build_parser().parse_args(["profile", "list", "--json"])
    assert args.command == "profile"
    assert args.profile_command == "list"
    assert args.json is True


def test_status_command_can_emit_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(app.config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(app.config, "BACKUP_DIR", tmp_path / "backup")
    monkeypatch.setattr(app.config, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(app.config, "BIN_DIR", tmp_path / "bin")
    monkeypatch.setattr(app.config, "GEO_DIR", tmp_path / "geo")

    assert app.main(["--config-dir", str(tmp_path), "--no-auto-update", "status", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["profiles"] == 0
    assert data["groups"] == 0


def test_profile_add_list_rename_remove_are_non_interactive(tmp_path, capsys):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="old", kind="socks", outbound=SOCKS))
    store.save()

    assert app._profile_command(store, app.build_parser().parse_args(["profile", "list"])) == 0
    assert "old" in capsys.readouterr().out

    rename = app.build_parser().parse_args(["profile", "rename", profile.id, "new"])
    assert app._profile_command(store, rename) == 0
    assert store.get_profile(profile.id).name == "new"

    remove = app.build_parser().parse_args(["profile", "remove", profile.id])
    assert app._profile_command(store, remove) == 0
    assert store.get_profile(profile.id) is None


def test_default_main_never_enters_tui(tmp_path, monkeypatch):
    monkeypatch.setattr(app.config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(app.config, "BACKUP_DIR", tmp_path / "backup")
    monkeypatch.setattr(app.config, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(app.config, "BIN_DIR", tmp_path / "bin")
    monkeypatch.setattr(app.config, "GEO_DIR", tmp_path / "geo")
    monkeypatch.setattr(app.config, "ensure_dirs", lambda: None)
    monkeypatch.setattr(app, "_tui_available", lambda: (_ for _ in ()).throw(AssertionError("TUI invoked")))

    assert app.main(["--headless", "--no-auto-update"]) == 0


def test_profile_list_filter_by_subscription(tmp_path, capsys):
    store = _store(tmp_path)
    sub = store.add_subscription(Subscription(name="myprovider"))
    sub_node = store.add_profile(Profile(name="sub-node", kind="vless", outbound=SOCKS, subscription_id=sub.id))
    manual_node = store.add_profile(Profile(name="manual-node", kind="socks", outbound=SOCKS))
    store.save()

    args = app.build_parser().parse_args(["profile", "list", "--subscription", sub.id])
    assert app._profile_command(store, args) == 0
    out = capsys.readouterr().out
    assert "sub-node" in out
    assert "manual-node" not in out


def test_profile_list_filter_by_kind(tmp_path, capsys):
    store = _store(tmp_path)
    store.add_profile(Profile(name="a-socks", kind="socks", outbound=SOCKS))
    store.add_profile(Profile(name="a-vless", kind="vless", outbound=SOCKS))
    store.save()

    args = app.build_parser().parse_args(["profile", "list", "--kind", "socks"])
    assert app._profile_command(store, args) == 0
    out = capsys.readouterr().out
    assert "a-socks" in out
    assert "a-vless" not in out
