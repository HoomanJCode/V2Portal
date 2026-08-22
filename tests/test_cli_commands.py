from __future__ import annotations

import json

import pytest

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


# -- routing CLI commands --------------------------------------------------


def test_routing_list_empty(tmp_path, capsys):
    store = _store(tmp_path)
    args = app.build_parser().parse_args(["routing", "list"])
    assert app._routing_command(store, args) == 0
    out = capsys.readouterr().out
    assert "mode=all" in out


def test_routing_list_json(tmp_path, capsys):
    from v2raycli.models import RoutingRule

    store = _store(tmp_path)
    store.config.routing.mode = "split"
    store.config.routing.rules.append(
        RoutingRule(action="block", match={"domains": ["ads.dev"]})
    )
    args = app.build_parser().parse_args(["routing", "list", "--json"])
    assert app._routing_command(store, args) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 1
    assert data[0]["action"] == "block"


def test_routing_mode_switch(tmp_path, capsys):
    store = _store(tmp_path)
    args = app.build_parser().parse_args(["routing", "mode", "split"])
    assert app._routing_command(store, args) == 0
    assert store.config.routing.mode == "split"
    assert "split" in capsys.readouterr().out


def test_routing_add_and_remove(tmp_path, capsys):
    store = _store(tmp_path)

    # Add a block rule
    args = app.build_parser().parse_args(
        ["routing", "add", "block", "--domain", "keyword:ads", "--domain", "ads.dev"]
    )
    assert app._routing_command(store, args) == 0
    rule_id = capsys.readouterr().out.strip()
    assert len(store.config.routing.rules) == 1
    assert store.config.routing.mode == "split"  # auto-switched

    # Add a direct rule with geoip
    args = app.build_parser().parse_args(
        ["routing", "add", "direct", "--ip", "192.168.0.0/16", "--geoip", "cn"]
    )
    assert app._routing_command(store, args) == 0
    assert len(store.config.routing.rules) == 2

    # Add a proxy rule with --target
    p = store.add_profile(Profile(name="US", kind="socks", outbound=SOCKS))
    store.save()
    args = app.build_parser().parse_args(
        ["routing", "add", "proxy", "--domain", "netflix.com", "--target", p.id]
    )
    assert app._routing_command(store, args) == 0
    assert len(store.config.routing.rules) == 3

    # Remove the first rule
    args = app.build_parser().parse_args(["routing", "remove", rule_id])
    assert app._routing_command(store, args) == 0
    assert len(store.config.routing.rules) == 2

    # Remove unknown rule
    args = app.build_parser().parse_args(["routing", "remove", "no-such-id"])
    assert app._routing_command(store, args) == 1
    assert "unknown" in capsys.readouterr().err


def test_routing_add_geosite(tmp_path, capsys):
    store = _store(tmp_path)
    args = app.build_parser().parse_args(
        ["routing", "add", "block", "--geosite", "category-ads-all", "--geosite", "gfw"]
    )
    assert app._routing_command(store, args) == 0
    rule = store.config.routing.rules[0]
    assert rule.match["geosite"] == ["category-ads-all", "gfw"]


def test_routing_parser_parsing(tmp_path):
    args = app.build_parser().parse_args(
        ["routing", "add", "proxy", "--domain", "example.com", "--ip", "10.0.0.0/8",
         "--geoip", "cn", "--geosite", "gfw", "--target", "abc-123"]
    )
    assert args.routing_command == "add"
    assert args.action == "proxy"
    assert args.domain == ["example.com"]
    assert args.ip == ["10.0.0.0/8"]
    assert args.geoip == ["cn"]
    assert args.geosite == ["gfw"]
    assert args.target == "abc-123"


def test_routing_move_up_and_down(tmp_path, capsys):
    from v2raycli.models import RoutingRule

    store = _store(tmp_path)
    r1 = RoutingRule(action="block", match={"domains": ["a.com"]})
    r2 = RoutingRule(action="direct", match={"domains": ["b.com"]})
    r3 = RoutingRule(action="proxy", target_id="x", match={"domains": ["c.com"]})
    store.config.routing.rules = [r1, r2, r3]

    # Move r3 up
    args = app.build_parser().parse_args(["routing", "move", r3.id, "up"])
    assert app._routing_command(store, args) == 0
    assert [r.id for r in store.config.routing.rules] == [r1.id, r3.id, r2.id]
    assert "up" in capsys.readouterr().out

    # Move r3 back down
    args = app.build_parser().parse_args(["routing", "move", r3.id, "down"])
    assert app._routing_command(store, args) == 0
    assert [r.id for r in store.config.routing.rules] == [r1.id, r2.id, r3.id]


def test_routing_move_edge_rejected(tmp_path, capsys):
    from v2raycli.models import RoutingRule

    store = _store(tmp_path)
    r1 = RoutingRule(action="block", match={"domains": ["a.com"]})
    store.config.routing.rules = [r1]

    args = app.build_parser().parse_args(["routing", "move", r1.id, "up"])
    assert app._routing_command(store, args) == 1
    assert "edge" in capsys.readouterr().err


def test_routing_move_unknown_id(tmp_path, capsys):
    store = _store(tmp_path)
    args = app.build_parser().parse_args(["routing", "move", "no-such", "up"])
    assert app._routing_command(store, args) == 1
    assert "unknown" in capsys.readouterr().err


def test_routing_enable_and_disable(tmp_path, capsys):
    from v2raycli.models import RoutingRule

    store = _store(tmp_path)
    r = RoutingRule(action="block", match={"domains": ["ads.dev"]})
    store.config.routing.rules.append(r)

    # Disable it
    args = app.build_parser().parse_args(["routing", "disable", r.id])
    assert app._routing_command(store, args) == 0
    assert r.enabled is False
    assert "disabled" in capsys.readouterr().out

    # Enable it
    args = app.build_parser().parse_args(["routing", "enable", r.id])
    assert app._routing_command(store, args) == 0
    assert r.enabled is True
    assert "enabled" in capsys.readouterr().out


def test_routing_enable_unknown_id(tmp_path, capsys):
    store = _store(tmp_path)
    args = app.build_parser().parse_args(["routing", "enable", "no-such"])
    assert app._routing_command(store, args) == 1
    assert "unknown" in capsys.readouterr().err


def test_config_set_port_validation(tmp_path, capsys):
    """config set rejects port 65535 (xray HTTP overflow) but accepts 65534."""
    store = _store(tmp_path)

    # 65534 should be accepted
    args = app.build_parser().parse_args(
        ["config", "set", "settings.mixed_port", "65534"]
    )
    assert app._config_command(store, args) == 0
    assert store.config.settings.mixed_port == 65534

    # 65535 should be rejected (raises ValueError, caught by _command)
    args = app.build_parser().parse_args(
        ["config", "set", "settings.mixed_port", "65535"]
    )
    with pytest.raises(ValueError, match="65534"):
        app._config_command(store, args)
    assert store.config.settings.mixed_port == 65534  # unchanged


def test_config_set_port_zero_accepted(tmp_path, capsys):
    """config set accepts port 0 (disabled) for socks_port and http_port."""
    store = _store(tmp_path)

    args = app.build_parser().parse_args(
        ["config", "set", "settings.socks_port", "0"]
    )
    assert app._config_command(store, args) == 0
    assert store.config.settings.socks_port == 0

    args = app.build_parser().parse_args(
        ["config", "set", "settings.http_port", "0"]
    )
    assert app._config_command(store, args) == 0
    assert store.config.settings.http_port == 0


def test_config_set_port_negative_rejected(tmp_path, capsys):
    """config set rejects negative port values."""
    store = _store(tmp_path)

    args = app.build_parser().parse_args(
        ["config", "set", "settings.mixed_port", "-1"]
    )
    with pytest.raises(ValueError, match="65534"):
        app._config_command(store, args)


def test_config_set_port_string_rejected(tmp_path, capsys):
    """config set rejects non-integer port values."""
    store = _store(tmp_path)

    args = app.build_parser().parse_args(
        ["config", "set", "settings.mixed_port", "abc"]
    )
    with pytest.raises(ValueError, match="integer"):
        app._config_command(store, args)


def test_config_set_port_bool_rejected(tmp_path, capsys):
    """config set rejects boolean port values."""
    store = _store(tmp_path)

    args = app.build_parser().parse_args(
        ["config", "set", "settings.mixed_port", "true"]
    )
    with pytest.raises(ValueError, match="integer"):
        app._config_command(store, args)


def test_routing_list_shows_disabled(tmp_path, capsys):
    from v2raycli.models import RoutingRule

    store = _store(tmp_path)
    store.config.routing.mode = "split"
    store.config.routing.rules = [
        RoutingRule(action="block", enabled=True, match={"domains": ["a.com"]}),
        RoutingRule(action="direct", enabled=False, match={"domains": ["b.com"]}),
    ]
    args = app.build_parser().parse_args(["routing", "list"])
    assert app._routing_command(store, args) == 0
    out = capsys.readouterr().out
    assert "[disabled]" in out
    assert "b.com" in out


# -- wrong-command help ------------------------------------------------------


def test_invalid_top_level_command_shows_help(capsys):
    """Typing 'v2raycli foo' prints the top-level usage and exits 2."""
    with pytest.raises(SystemExit, match="2"):
        app.build_parser().parse_args(["foo"])
    err = capsys.readouterr().out + capsys.readouterr().err
    assert "usage:" in err.lower()


def test_invalid_profile_action_shows_profile_help(capsys):
    """Typing 'v2raycli profile foo' prints profile usage and exits 2."""
    with pytest.raises(SystemExit, match="2"):
        app.build_parser().parse_args(["profile", "foo"])
    err = capsys.readouterr().out + capsys.readouterr().err
    assert "profile" in err.lower()


def test_invalid_subscription_action_shows_subscription_help(capsys):
    """Typing 'v2raycli subscription foo' prints subscription usage and exits 2."""
    with pytest.raises(SystemExit, match="2"):
        app.build_parser().parse_args(["subscription", "foo"])
    err = capsys.readouterr().out + capsys.readouterr().err
    assert "subscription" in err.lower()


def test_invalid_server_action_shows_server_help(capsys):
    """Typing 'v2raycli server foo' prints server usage and exits 2."""
    with pytest.raises(SystemExit, match="2"):
        app.build_parser().parse_args(["server", "foo"])
    err = capsys.readouterr().out + capsys.readouterr().err
    assert "server" in err.lower()


def test_invalid_routing_action_shows_routing_help(capsys):
    """Typing 'v2raycli routing foo' prints routing usage and exits 2."""
    with pytest.raises(SystemExit, match="2"):
        app.build_parser().parse_args(["routing", "foo"])
    err = capsys.readouterr().out + capsys.readouterr().err
    assert "routing" in err.lower()


def test_invalid_test_action_shows_test_help(capsys):
    """Typing 'v2raycli test foo' prints test usage and exits 2."""
    with pytest.raises(SystemExit, match="2"):
        app.build_parser().parse_args(["test", "foo"])
    err = capsys.readouterr().out + capsys.readouterr().err
    assert "test" in err.lower()
