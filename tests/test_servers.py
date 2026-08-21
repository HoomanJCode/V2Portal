"""Tests for server management."""

from __future__ import annotations

import json

from v2raycli import app
from v2raycli.models import Profile, Server
from v2raycli.servers import ServerManager, ServerState
from v2raycli.storage import ConfigStore

SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}


def _store(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    return store


def test_server_model_persists(tmp_path):
    store = _store(tmp_path)
    server = Server(name="test", port=1080, protocol="mixed", outbound_id="abc", outbound_type="profile")
    store.add_server(server)
    store.save()

    store2 = ConfigStore(tmp_path / "config.json")
    store2.load()
    assert len(store2.config.servers) == 1
    assert store2.config.servers[0].port == 1080
    assert store2.config.servers[0].outbound_id == "abc"


def test_server_crud(tmp_path):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    store.save()

    server = Server(name="s1", port=1080, outbound_id=profile.id, outbound_type="profile")
    store.add_server(server)
    store.save()
    assert store.get_server(server.id) is not None

    store.remove_server(server.id)
    store.save()
    assert store.get_server(server.id) is None


def test_server_list_json(tmp_path, capsys):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    server = Server(name="s1", port=1080, outbound_id=profile.id, outbound_type="profile")
    store.add_server(server)
    store.save()

    args = app.build_parser().parse_args(["server", "list", "--json"])
    assert app._server_command(store, args) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data) == 1
    assert data[0]["port"] == 1080


def test_server_add_requires_profile_or_group(tmp_path, capsys):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    store.save()

    args = app.build_parser().parse_args(["server", "add", "--port", "1080", "--profile", profile.id, "--name", "test"])
    assert app._server_command(store, args) == 0
    assert len(store.list_servers()) == 1
    assert store.list_servers()[0].name == "test"


def test_server_add_unknown_profile(tmp_path, capsys):
    store = _store(tmp_path)
    args = app.build_parser().parse_args(["server", "add", "--port", "1080", "--profile", "nope"])
    assert app._server_command(store, args) == 1
    assert "unknown" in capsys.readouterr().err


def test_server_start_unknown(tmp_path, capsys):
    store = _store(tmp_path)
    args = app.build_parser().parse_args(["server", "start", "nope"])
    assert app._server_command(store, args) == 1
    assert "unknown" in capsys.readouterr().err


def test_server_stop_not_running(tmp_path, capsys):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    server = Server(name="s1", port=1080, outbound_id=profile.id, outbound_type="profile")
    store.add_server(server)
    store.save()

    args = app.build_parser().parse_args(["server", "stop", server.id])
    assert app._server_command(store, args) == 0
    assert "not running" in capsys.readouterr().out


def test_server_remove(tmp_path, capsys):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    server = Server(name="s1", port=1080, outbound_id=profile.id, outbound_type="profile")
    store.add_server(server)
    store.save()

    args = app.build_parser().parse_args(["server", "remove", server.id])
    assert app._server_command(store, args) == 0
    assert store.get_server(server.id) is None
    assert "removed" in capsys.readouterr().out


def test_server_state_tracking(tmp_path):
    store = _store(tmp_path)
    mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")

    # No states initially
    assert mgr.list_running() == []

    # Simulate a state
    state = ServerState(server_id="test", pid=None)
    mgr._states["test"] = state
    assert mgr.get_state("test") is not None


def test_server_config_includes_split_routing_targets(tmp_path):
    """Server config generation enriches the target with routing extras."""
    from v2raycli.models import Group, RoutingConfig, RoutingRule

    store = _store(tmp_path)
    main = store.add_profile(Profile(name="main", kind="socks", outbound=SOCKS))
    extra = store.add_profile(Profile(name="netflix", kind="socks", outbound=SOCKS))
    store.config.routing = RoutingConfig(
        mode="split",
        rules=[
            RoutingRule(action="proxy", target_id=extra.id, match={"domains": ["netflix.com"]}),
        ],
    )
    server = store.add_server(
        Server(name="s1", port=1080, outbound_id=main.id, outbound_type="profile")
    )
    mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")
    config = mgr._generate_server_config(server)

    # The extra profile's outbound should be in the config.
    all_outbound_tags = [o.get("tag") for o in config.get("outbounds", [])]
    assert extra.id in all_outbound_tags
    # The routing rule should reference the extra profile.
    rules = config.get("route", {}).get("rules", []) + config.get("routing", {}).get("rules", [])
    assert any(
        r.get("outbound") == extra.id or r.get("outboundTag") == extra.id
        for r in rules
    )


def test_server_config_with_balancer_routing_target(tmp_path):
    """Server config includes balancer group constructs from routing rules."""
    from v2raycli.models import Group, RoutingConfig, RoutingRule

    store = _store(tmp_path)
    main = store.add_profile(Profile(name="main", kind="socks", outbound=SOCKS))
    b = store.add_profile(Profile(name="b", kind="socks", outbound=SOCKS))
    c = store.add_profile(Profile(name="c", kind="socks", outbound=SOCKS))
    bal = store.add_group(
        Group(name="bal", type="balancer", strategy="latency", profile_ids=[b.id, c.id])
    )
    store.config.routing = RoutingConfig(
        mode="split",
        rules=[RoutingRule(action="proxy", target_id=bal.id, match={"domains": ["streaming.com"]})],
    )
    server = store.add_server(
        Server(name="s1", port=1080, outbound_id=main.id, outbound_type="profile")
    )
    mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")
    config = mgr._generate_server_config(server)

    all_outbound_tags = [o.get("tag") for o in config.get("outbounds", [])]
    # Both member profiles and the balancer group should be in the config.
    assert b.id in all_outbound_tags
    assert c.id in all_outbound_tags
    # The group should have a urltest or selector construct.
    assert any(
        o.get("tag") == bal.id and o.get("type") in ("urltest", "selector")
        for o in config.get("outbounds", [])
    )
