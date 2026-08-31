from __future__ import annotations

import json

import pytest

from v2portal import app
from v2portal.models import Group, Profile, Subscription
from v2portal.storage import ConfigStore

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

    assert app.main(["--no-auto-update", "status"]) == 0


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


# -- group CLI auto-detection ---------------------------------------------


def test_group_create_detects_mixed_profile_and_subscription_ids(tmp_path, capsys):
    store = _store(tmp_path)
    manual = store.add_profile(Profile(name="manual", kind="socks", outbound=SOCKS))
    sub_node = store.add_profile(Profile(name="sub-node", kind="vless", outbound=SOCKS))
    sub = store.add_subscription(Subscription(name="myprovider", profile_ids=[sub_node.id]))
    store.save()

    args = app.build_parser().parse_args(
        ["group", "create", "balancer", "pool", manual.id, sub.id]
    )
    assert app._group_command(store, args) == 0
    group = store.get_group(capsys.readouterr().out.strip())
    assert group is not None
    assert group.profile_ids == [manual.id]
    assert group.subscription_ids == [sub.id]


def test_group_add_member_detects_subscription_id(tmp_path, capsys):
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    sub = store.add_subscription(Subscription(name="sub"))
    group = store.add_group(Group(name="g", type="single", profile_ids=[p.id]))
    store.save()

    args = app.build_parser().parse_args(["group", "add-member", group.id, sub.id])
    assert app._group_command(store, args) == 0
    assert store.get_group(group.id).subscription_ids == [sub.id]


def test_group_remove_member_detects_subscription_id(tmp_path, capsys):
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    sub = store.add_subscription(Subscription(name="sub"))
    group = store.add_group(Group(
        name="g", type="single", profile_ids=[p.id], subscription_ids=[sub.id],
    ))
    store.save()

    args = app.build_parser().parse_args(["group", "remove-member", group.id, sub.id])
    assert app._group_command(store, args) == 0
    assert store.get_group(group.id).subscription_ids == []


def test_group_add_member_rejects_unknown_id(tmp_path, capsys):
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    group = store.add_group(Group(name="g", type="single", profile_ids=[p.id]))
    store.save()

    args = app.build_parser().parse_args(["group", "add-member", group.id, "999"])
    assert app._command(store, args) == 1
    assert "unknown id: 999" in capsys.readouterr().err


# -- uniform command shape (Phase 02) -------------------------------------


def test_group_add_replaces_create_and_supports_nested_group(tmp_path, capsys):
    store = _store(tmp_path)
    p1 = store.add_profile(Profile(name="p1", kind="socks", outbound=SOCKS))
    p2 = store.add_profile(Profile(name="p2", kind="vless", outbound=SOCKS))
    leaf = store.add_group(Group(name="leaf", type="single", profile_ids=[p2.id]))
    store.save()

    # group add balancer with a nested group ref
    args = app.build_parser().parse_args(
        ["group", "add", "balancer", "pool", p1.id, leaf.id]
    )
    assert app._group_command(store, args) == 0
    group = store.get_group(capsys.readouterr().out.strip())
    assert group is not None
    assert group.profile_ids == [p1.id]
    assert group.group_ids == [leaf.id]

    # legacy 'group create' alias still works
    args = app.build_parser().parse_args(
        ["group", "create", "balancer", "two", p1.id, p2.id]
    )
    assert app._group_command(store, args) == 0
    two = store.get_group(capsys.readouterr().out.strip())
    assert two is not None and two.type == "balancer"


def test_group_add_has_no_single_type(tmp_path, capsys):
    """The 'single' group type was removed; only balancer/chain exist."""
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    store.save()
    with pytest.raises(SystemExit) as excinfo:
        app.build_parser().parse_args(["group", "add", "single", "one", p.id])
    assert excinfo.value.code == 2


def test_group_add_balancer_rejects_lone_profile(tmp_path, capsys):
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    store.save()
    args = app.build_parser().parse_args(["group", "add", "balancer", "one", p.id])
    assert app._command(store, args) == 1
    assert "single profile is not a group" in capsys.readouterr().err


def test_group_add_accepts_single_subscription(tmp_path, capsys):
    store = _store(tmp_path)
    p1 = store.add_profile(Profile(name="p1", kind="socks", outbound=SOCKS))
    p2 = store.add_profile(Profile(name="p2", kind="vless", outbound=SOCKS))
    sub = store.add_subscription(Subscription(name="sub", profile_ids=[p1.id, p2.id]))
    store.save()

    args = app.build_parser().parse_args(["group", "add", "balancer", "pool", sub.id])
    assert app._group_command(store, args) == 0
    bal = store.get_group(capsys.readouterr().out.strip())
    assert bal is not None and bal.type == "balancer"
    assert bal.subscription_ids == [sub.id]

    args = app.build_parser().parse_args(["group", "add", "chain", "tunnel", sub.id])
    assert app._group_command(store, args) == 0
    chain = store.get_group(capsys.readouterr().out.strip())
    assert chain is not None and chain.type == "chain"
    assert chain.subscription_ids == [sub.id]


# -- servers as group members (nested hierarchy) ---------------------------


def test_group_add_balancer_detects_server_ref(tmp_path, capsys):
    from v2portal.models import Server

    store = _store(tmp_path)
    p = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    sv = store.add_server(Server(name="local", port=1081))
    store.save()

    args = app.build_parser().parse_args(["group", "add", "balancer", "pool", p.id, sv.id])
    assert app._group_command(store, args) == 0
    g = store.get_group(capsys.readouterr().out.strip())
    assert g.profile_ids == [p.id]
    assert g.server_ids == [sv.id]


def test_group_add_member_detects_server_id(tmp_path, capsys):
    from v2portal.models import Server

    store = _store(tmp_path)
    p = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    sv = store.add_server(Server(name="local", port=1081))
    group = store.add_group(Group(name="g", type="single", profile_ids=[p.id]))
    store.save()

    args = app.build_parser().parse_args(["group", "add-member", group.id, sv.id])
    assert app._group_command(store, args) == 0
    assert store.get_group(group.id).server_ids == [sv.id]


def test_group_remove_member_detects_server_id(tmp_path, capsys):
    from v2portal.models import Server

    store = _store(tmp_path)
    sv = store.add_server(Server(name="local", port=1081))
    group = store.add_group(Group(name="g", type="single", server_ids=[sv.id]))
    store.save()

    args = app.build_parser().parse_args(["group", "remove-member", group.id, sv.id])
    assert app._group_command(store, args) == 0
    assert store.get_group(group.id).server_ids == []


def test_group_add_member_rejects_server_forwarding_to_group(tmp_path, capsys):
    from v2portal.models import Server

    store = _store(tmp_path)
    p = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    sv = store.add_server(Server(name="local", port=1081))
    group = store.add_group(Group(name="g", type="single", profile_ids=[p.id]))
    sv.outbound_type = "group"
    sv.outbound_id = group.id
    store.save()

    args = app.build_parser().parse_args(["group", "add-member", group.id, sv.id])
    assert app._command(store, args) == 1
    assert "circular" in capsys.readouterr().err


def test_profile_add_server_creates_localhost_profile(tmp_path, capsys):
    from v2portal.models import Server

    store = _store(tmp_path)
    sv = store.add_server(Server(name="local", port=1081, protocol="mixed", listen="127.0.0.1"))
    store.save()

    args = app.build_parser().parse_args(["profile", "add", "server", "via-server", sv.id])
    assert app._profile_command(store, args) == 0
    profile = store.get_profile(capsys.readouterr().out.strip())
    assert profile is not None
    assert profile.kind == "socks"
    assert profile.name == "via-server"
    assert profile.outbound["settings"]["servers"][0]["address"] == "127.0.0.1"
    assert profile.outbound["settings"]["servers"][0]["port"] == 1081


def test_profile_add_server_unknown_id_fails(tmp_path, capsys):
    store = _store(tmp_path)
    args = app.build_parser().parse_args(["profile", "add", "server", "x", "999"])
    assert app._command(store, args) == 1
    assert "unknown server id" in capsys.readouterr().err


def test_subscription_update_proxy_accepts_server_id(tmp_path, capsys):
    from v2portal.models import Server

    store = _store(tmp_path)
    sv = store.add_server(Server(name="local", port=1081))
    sub = store.add_subscription(
        Subscription(name="sub", url="paste://socks://user:pass@1.2.3.4:1080")
    )
    store.save()

    args = app.build_parser().parse_args(["subscription", "update", sub.id, "--proxy", sv.id])
    assert app._subscription_command(store, args) == 0
    assert "updated 1 profiles" in capsys.readouterr().out


def test_subscription_update_proxy_unknown_id_fails(tmp_path, capsys):
    store = _store(tmp_path)
    sub = store.add_subscription(
        Subscription(name="sub", url="paste://socks://user:pass@1.2.3.4:1080")
    )
    store.save()

    args = app.build_parser().parse_args(["subscription", "update", sub.id, "--proxy", "nope"])
    assert app._command(store, args) == 1
    assert "proxy must be a URL" in capsys.readouterr().err


# -- group tree ------------------------------------------------------------


def test_group_tree_command_renders_hierarchy(tmp_path, capsys):
    from v2portal.models import Server

    store = _store(tmp_path)
    p1 = store.add_profile(Profile(name="p1", kind="vmess", outbound=SOCKS))
    p2 = store.add_profile(Profile(name="p2", kind="socks", outbound=SOCKS))
    sub = store.add_subscription(Subscription(name="sub", profile_ids=[p2.id]))
    sv = store.add_server(Server(name="local", port=1081))
    inner = store.add_group(Group(name="inner", type="single", profile_ids=[p2.id]))
    outer = store.add_group(Group(
        name="fast", type="balancer", strategy="latency",
        profile_ids=[p1.id], subscription_ids=[sub.id],
        server_ids=[sv.id], group_ids=[inner.id],
    ))
    store.save()

    args = app.build_parser().parse_args(["group", "tree"])
    assert app._group_command(store, args) == 0
    out = capsys.readouterr().out
    assert f"{outer.id}  balancer fast (latency)" in out
    assert f"{inner.id}  single inner" in out
    assert f"{sub.id}  subscription sub (1 profiles)" in out
    assert f"{sv.id}  server local :1081" in out


def test_group_tree_command_empty(tmp_path, capsys):
    store = _store(tmp_path)
    store.save()
    args = app.build_parser().parse_args(["group", "tree"])
    assert app._group_command(store, args) == 0
    assert "no groups" in capsys.readouterr().out


def test_group_edit(tmp_path, capsys):
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    g = store.add_group(Group(name="g", type="balancer", strategy="latency", profile_ids=[p.id]))
    store.save()

    args = app.build_parser().parse_args(
        ["group", "edit", g.id, "--name", "fast", "--strategy", "random"]
    )
    assert app._group_command(store, args) == 0
    updated = store.get_group(g.id)
    assert updated.name == "fast"
    assert updated.strategy == "random"

    args = app.build_parser().parse_args(["group", "edit", g.id, "--no-enabled"])
    assert app._group_command(store, args) == 0
    assert store.get_group(g.id).enabled is False


def test_subscription_edit_and_rename(tmp_path, capsys):
    store = _store(tmp_path)
    sub = store.add_subscription(Subscription(name="old", url="https://a"))
    store.save()

    args = app.build_parser().parse_args(
        ["subscription", "edit", sub.id, "--name", "new", "--auto-update-days", "2"]
    )
    assert app._subscription_command(store, args) == 0
    updated = store.get_subscription(sub.id)
    assert updated.name == "new"
    assert updated.auto_update_days == 2

    args = app.build_parser().parse_args(["subscription", "rename", sub.id, "renamed"])
    assert app._subscription_command(store, args) == 0
    assert store.get_subscription(sub.id).name == "renamed"


def test_subscription_remove_prunes_groups_and_deletes_profiles(tmp_path, capsys):
    store = _store(tmp_path)
    sub = store.add_subscription(Subscription(name="myprovider"))
    sub_node = store.add_profile(Profile(
        name="sub-node", kind="socks", outbound=SOCKS, subscription_id=sub.id,
    ))
    sub.profile_ids = [sub_node.id]
    group = store.add_group(Group(name="g", subscription_ids=[sub.id]))
    store.save()

    args = app.build_parser().parse_args(["subscription", "remove", sub.id])
    assert app._subscription_command(store, args) == 0
    out = capsys.readouterr().out
    assert "deleted 1 profile(s)" in out
    assert "pruned from 1 group(s)" in out
    assert store.get_subscription(sub.id) is None
    assert store.get_profile(sub_node.id) is None
    assert store.get_group(group.id).subscription_ids == []


def test_group_remove_prunes_nested(tmp_path, capsys):
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    leaf = store.add_group(Group(name="leaf", type="single", profile_ids=[p.id]))
    parent = store.add_group(Group(name="parent", type="single", group_ids=[leaf.id]))
    store.save()

    args = app.build_parser().parse_args(["group", "remove", leaf.id])
    assert app._group_command(store, args) == 0
    assert "pruned from 1 group(s)" in capsys.readouterr().out
    assert store.get_group(parent.id).group_ids == []


def test_profile_edit_enabled_and_engine(tmp_path, capsys):
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS, engine="auto"))
    store.save()

    args = app.build_parser().parse_args(
        ["profile", "edit", p.id, "--engine", "xray", "--no-enabled"]
    )
    assert app._profile_command(store, args) == 0
    updated = store.get_profile(p.id)
    assert updated.engine == "xray"
    assert updated.enabled is False


# -- routing CLI commands --------------------------------------------------


def test_routing_list_empty(tmp_path, capsys):
    store = _store(tmp_path)
    args = app.build_parser().parse_args(["routing", "list"])
    assert app._routing_command(store, args) == 0
    out = capsys.readouterr().out
    assert "mode=all" in out


def test_routing_list_json(tmp_path, capsys):
    from v2portal.models import RoutingRule

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
    from v2portal.models import RoutingRule

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
    from v2portal.models import RoutingRule

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
    from v2portal.models import RoutingRule

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


def test_settings_port_validation(tmp_path, capsys):
    """settings mixed-port rejects port 65535 but accepts 65534."""
    store = _store(tmp_path)

    # 65534 should be accepted
    args = app.build_parser().parse_args(
        ["settings", "mixed-port", "65534"]
    )
    assert app._settings_command(store, args) == 0
    assert store.config.settings.mixed_port == 65534

    # 65535 should be rejected
    args = app.build_parser().parse_args(
        ["settings", "mixed-port", "65535"]
    )
    with pytest.raises(ValueError, match="65534"):
        app._settings_command(store, args)
    assert store.config.settings.mixed_port == 65534  # unchanged


def test_settings_port_zero_accepted(tmp_path, capsys):
    """settings accepts port 0 (disabled) for socks-port and http-port."""
    store = _store(tmp_path)

    args = app.build_parser().parse_args(
        ["settings", "socks-port", "0"]
    )
    assert app._settings_command(store, args) == 0
    assert store.config.settings.socks_port == 0

    args = app.build_parser().parse_args(
        ["settings", "http-port", "0"]
    )
    assert app._settings_command(store, args) == 0
    assert store.config.settings.http_port == 0


def test_settings_port_negative_rejected(tmp_path, capsys):
    """settings rejects negative port values."""
    store = _store(tmp_path)

    args = app.build_parser().parse_args(
        ["settings", "mixed-port", "-1"]
    )
    with pytest.raises(ValueError, match="65534"):
        app._settings_command(store, args)


def test_settings_port_string_rejected(tmp_path, capsys):
    """settings rejects non-integer port values."""
    store = _store(tmp_path)

    args = app.build_parser().parse_args(
        ["settings", "mixed-port", "abc"]
    )
    with pytest.raises(ValueError, match="integer"):
        app._settings_command(store, args)


def test_settings_port_bool_rejected(tmp_path, capsys):
    """settings rejects boolean port values."""
    store = _store(tmp_path)

    args = app.build_parser().parse_args(
        ["settings", "mixed-port", "true"]
    )
    with pytest.raises(ValueError, match="integer"):
        app._settings_command(store, args)


def test_routing_list_shows_disabled(tmp_path, capsys):
    from v2portal.models import RoutingRule

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
    """Typing 'v2portal foo' prints the top-level usage and exits 2."""
    with pytest.raises(SystemExit, match="2"):
        app.build_parser().parse_args(["foo"])
    err = capsys.readouterr().out + capsys.readouterr().err
    assert "usage:" in err.lower()


def test_invalid_profile_action_shows_profile_help(capsys):
    """Typing 'v2portal profile foo' prints profile usage and exits 2."""
    with pytest.raises(SystemExit, match="2"):
        app.build_parser().parse_args(["profile", "foo"])
    err = capsys.readouterr().out + capsys.readouterr().err
    assert "profile" in err.lower()


def test_invalid_subscription_action_shows_subscription_help(capsys):
    """Typing 'v2portal subscription foo' prints subscription usage and exits 2."""
    with pytest.raises(SystemExit, match="2"):
        app.build_parser().parse_args(["subscription", "foo"])
    err = capsys.readouterr().out + capsys.readouterr().err
    assert "subscription" in err.lower()


def test_invalid_server_action_shows_server_help(capsys):
    """Typing 'v2portal server foo' prints server usage and exits 2."""
    with pytest.raises(SystemExit, match="2"):
        app.build_parser().parse_args(["server", "foo"])
    err = capsys.readouterr().out + capsys.readouterr().err
    assert "server" in err.lower()


def test_invalid_routing_action_shows_routing_help(capsys):
    """Typing 'v2portal routing foo' prints routing usage and exits 2."""
    with pytest.raises(SystemExit, match="2"):
        app.build_parser().parse_args(["routing", "foo"])
    err = capsys.readouterr().out + capsys.readouterr().err
    assert "routing" in err.lower()


def test_bare_test_scope_defaults_to_endpoint():
    """Typing 'v2portal test <id>' treats the token as a scope and defaults
    to an endpoint probe rather than erroring on an unknown type."""
    args = app.build_parser().parse_args(["test", "foo"])
    assert args.test_type == "foo"
    assert args.scope == "all"
    assert args.test_type not in ("latency", "request", "websocket", "ws")


# -- settings / config ------------------------------------------------------


def test_settings_bare_shows_all(tmp_path, capsys):
    """'v2portal settings' with no subcommand prints all settings as JSON."""
    store = _store(tmp_path)
    args = app.build_parser().parse_args(["settings"])
    assert app._settings_command(store, args) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "mixed-port" in data
    assert "default-engine" in data


def test_settings_get_single(tmp_path, capsys):
    """'v2portal settings mixed-port' prints current value."""
    store = _store(tmp_path)
    args = app.build_parser().parse_args(["settings", "mixed-port"])
    assert app._settings_command(store, args) == 0
    out = capsys.readouterr().out.strip()
    assert json.loads(out) == store.config.settings.mixed_port


def test_settings_set_single(tmp_path, capsys):
    """'v2portal settings mixed-port 1081' sets the value."""
    store = _store(tmp_path)
    args = app.build_parser().parse_args(["settings", "mixed-port", "1081"])
    assert app._settings_command(store, args) == 0
    assert store.config.settings.mixed_port == 1081
