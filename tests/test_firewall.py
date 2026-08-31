"""Tests for Windows Firewall rule management."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from v2raycli import firewall


def test_rule_display_name():
    assert firewall._rule_display_name("sing-box") == "v2portal sing-box"
    assert firewall._rule_display_name("xray") == "v2portal xray"


def test_is_windows_returns_false_on_posix(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    assert firewall.is_windows() is False


def test_is_windows_returns_true_on_win32(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    assert firewall.is_windows() is True


def test_add_rule_returns_hint_on_non_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    result = firewall.add_rule("sing-box", "/usr/bin/sing-box")
    assert "only needed on Windows" in result


def test_add_rule_returns_error_when_binary_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", "win32")
    missing = tmp_path / "nonexistent.exe"
    result = firewall.add_rule("sing-box", missing)
    assert "not found" in result


def test_add_rule_success(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(firewall, "is_admin", lambda: True)

    fake_binary = tmp_path / "sing-box.exe"
    fake_binary.write_bytes(b"fake")

    completed = subprocess.CompletedProcess([], returncode=0, stdout="v2portal sing-box\n", stderr="")
    monkeypatch.setattr(firewall, "_run_powershell", lambda cmd: completed)

    result = firewall.add_rule("sing-box", fake_binary)
    assert "added" in result
    assert "sing-box" in result


def test_add_rule_detects_existing(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(firewall, "is_admin", lambda: True)

    fake_binary = tmp_path / "sing-box.exe"
    fake_binary.write_bytes(b"fake")

    # PowerShell returns empty (rule already exists)
    empty = subprocess.CompletedProcess([], returncode=0, stdout="", stderr="")
    monkeypatch.setattr(firewall, "_run_powershell", lambda cmd: empty)
    monkeypatch.setattr(firewall, "check_rule", lambda engine: {"DisplayName": "v2portal sing-box"})

    result = firewall.add_rule("sing-box", fake_binary)
    assert "already exists" in result


def test_remove_rule_returns_hint_on_non_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    result = firewall.remove_rule("sing-box")
    assert "only needed on Windows" in result


def test_remove_rule_success(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(firewall, "is_admin", lambda: True)

    completed = subprocess.CompletedProcess([], returncode=0, stdout="", stderr="")
    monkeypatch.setattr(firewall, "_run_powershell", lambda cmd: completed)

    result = firewall.remove_rule("sing-box")
    assert "removed" in result


def test_check_rule_returns_none_on_non_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    assert firewall.check_rule("sing-box") is None


def test_check_rule_returns_dict_when_found(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    rule_json = json.dumps({"DisplayName": "v2portal sing-box", "Enabled": True})
    completed = subprocess.CompletedProcess([], returncode=0, stdout=rule_json, stderr="")
    monkeypatch.setattr(firewall, "_run_powershell", lambda cmd: completed)

    result = firewall.check_rule("sing-box")
    assert result is not None
    assert result["DisplayName"] == "v2portal sing-box"


def test_check_rule_returns_none_when_not_found(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    completed = subprocess.CompletedProcess([], returncode=0, stdout="", stderr="")
    monkeypatch.setattr(firewall, "_run_powershell", lambda cmd: completed)

    assert firewall.check_rule("sing-box") is None


def test_list_rules_returns_empty_on_non_windows(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    assert firewall.list_rules() == []


def test_list_rules_returns_list(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    rules_json = json.dumps([
        {"DisplayName": "v2portal sing-box", "Enabled": True},
        {"DisplayName": "v2portal xray", "Enabled": False},
    ])
    completed = subprocess.CompletedProcess([], returncode=0, stdout=rules_json, stderr="")
    monkeypatch.setattr(firewall, "_run_powershell", lambda cmd: completed)

    result = firewall.list_rules()
    assert len(result) == 2


# -- CLI integration -------------------------------------------------------


def test_firewall_command_not_on_windows(monkeypatch, tmp_path, capsys):
    from v2raycli import app
    from v2raycli.storage import ConfigStore

    monkeypatch.setattr("sys.platform", "linux")
    store = ConfigStore(tmp_path / "config.json")
    store.load()

    args = app.build_parser().parse_args(["settings", "firewall", "allow", "sing-box"])
    assert app._settings_command(store, args) == 0
    assert "only needed on Windows" in capsys.readouterr().out


def test_firewall_command_list_no_rules(monkeypatch, tmp_path, capsys):
    from v2raycli import app
    from v2raycli.storage import ConfigStore

    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(firewall, "list_rules", lambda: [])
    store = ConfigStore(tmp_path / "config.json")
    store.load()

    args = app.build_parser().parse_args(["settings", "firewall", "list"])
    assert app._settings_command(store, args) == 0
    assert "no v2portal firewall rules" in capsys.readouterr().out


def test_firewall_command_allow_both(monkeypatch, tmp_path, capsys):
    from v2raycli import app
    from v2raycli.storage import ConfigStore

    monkeypatch.setattr("sys.platform", "win32")
    store = ConfigStore(tmp_path / "config.json")
    store.load()

    # Mock locate_binary to return fake paths
    fake_sb = tmp_path / "sing-box.exe"
    fake_sb.write_bytes(b"fake")
    fake_xray = tmp_path / "xray.exe"
    fake_xray.write_bytes(b"fake")

    call_log = []

    def fake_locate(engine, options, **kw):
        return fake_sb if engine == "sing-box" else fake_xray

    def fake_add(engine, binary, **kw):
        call_log.append(engine)
        return f"rule added for {engine}"

    monkeypatch.setattr("v2raycli.engines.binary.locate_binary", fake_locate)
    monkeypatch.setattr(firewall, "add_rule", fake_add)

    args = app.build_parser().parse_args(["settings", "firewall", "allow", "both"])
    assert app._settings_command(store, args) == 0
    assert "sing-box" in call_log
    assert "xray" in call_log
    out = capsys.readouterr().out
    assert "rule added for sing-box" in out
    assert "rule added for xray" in out


def test_firewall_command_remove(monkeypatch, tmp_path, capsys):
    from v2raycli import app
    from v2raycli.storage import ConfigStore

    monkeypatch.setattr("sys.platform", "win32")
    store = ConfigStore(tmp_path / "config.json")
    store.load()

    fake_binary = tmp_path / "sing-box.exe"
    fake_binary.write_bytes(b"fake")

    monkeypatch.setattr("v2raycli.engines.binary.locate_binary", lambda engine, opts, **kw: fake_binary)
    monkeypatch.setattr(firewall, "remove_rule", lambda engine: f"rule removed for {engine}")

    args = app.build_parser().parse_args(["settings", "firewall", "remove", "sing-box"])
    assert app._settings_command(store, args) == 0
    assert "rule removed for sing-box" in capsys.readouterr().out


def test_firewall_command_no_action_shows_usage(monkeypatch, tmp_path, capsys):
    from v2raycli import app
    from v2raycli.storage import ConfigStore

    monkeypatch.setattr("sys.platform", "win32")
    store = ConfigStore(tmp_path / "config.json")
    store.load()

    args = app.build_parser().parse_args(["settings", "firewall"])
    assert app._settings_command(store, args) == 2
