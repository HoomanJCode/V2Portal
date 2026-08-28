"""Tests for server management."""

from __future__ import annotations

import json

import pytest

from v2raycli import app
from v2raycli.models import Group, Profile, Server, Subscription
from v2raycli.servers import ServerManager, ServerState, _check_stderr_for_errors
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


# -- universal outbound refs (Phase 03) -----------------------------------


def test_server_add_accepts_subscription_ref(tmp_path, capsys):
    store = _store(tmp_path)
    sub_node = store.add_profile(Profile(name="sub-node", kind="socks", outbound=SOCKS))
    sub = store.add_subscription(Subscription(name="myprovider", profile_ids=[sub_node.id]))
    store.save()

    args = app.build_parser().parse_args(["server", "add", "--port", "1080", sub.id])
    assert app._server_command(store, args) == 0
    server = store.get_server(capsys.readouterr().out.strip())
    assert server is not None
    assert server.outbound_type == "subscription"
    assert server.outbound_id == sub.id


def test_server_add_accepts_group_ref(tmp_path, capsys):
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    g = store.add_group(Group(name="g", type="single", profile_ids=[p.id]))
    store.save()

    args = app.build_parser().parse_args(["server", "add", "--port", "1080", g.id])
    assert app._server_command(store, args) == 0
    server = store.get_server(capsys.readouterr().out.strip())
    assert server.outbound_type == "group"


def test_server_add_legacy_profile_flag_still_works(tmp_path, capsys):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    store.save()
    args = app.build_parser().parse_args(["server", "add", "--port", "1080", "--profile", profile.id])
    assert app._server_command(store, args) == 0
    server = store.get_server(capsys.readouterr().out.strip())
    assert server.outbound_type == "profile"


def test_server_list_shows_subscription_label(tmp_path, capsys):
    store = _store(tmp_path)
    sub_node = store.add_profile(Profile(name="n", kind="socks", outbound=SOCKS))
    sub = store.add_subscription(Subscription(name="myprovider", profile_ids=[sub_node.id]))
    server = Server(name="s1", port=1080, outbound_id=sub.id, outbound_type="subscription")
    store.add_server(server)
    store.save()

    args = app.build_parser().parse_args(["server", "list"])
    assert app._server_command(store, args) == 0
    assert f"subscription/{sub.id} (myprovider)" in capsys.readouterr().out


def test_server_edit_switches_outbound_ref(tmp_path, capsys):
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    sub_node = store.add_profile(Profile(name="n2", kind="socks", outbound=SOCKS))
    sub = store.add_subscription(Subscription(name="s", profile_ids=[sub_node.id]))
    server = store.add_server(Server(name="s1", port=1080, outbound_id=p.id, outbound_type="profile"))
    store.save()

    args = app.build_parser().parse_args(["server", "edit", server.id, "--outbound", sub.id])
    assert app._server_command(store, args) == 0
    updated = store.get_server(server.id)
    assert updated.outbound_type == "subscription"
    assert updated.outbound_id == sub.id


def test_server_resolve_subscription_outbound_target(tmp_path):
    """Subscription outbound resolves to a balancer over current profiles."""
    store = _store(tmp_path)
    p1 = store.add_profile(Profile(name="p1", kind="socks", outbound=SOCKS))
    p2 = store.add_profile(Profile(name="p2", kind="socks", outbound=SOCKS))
    sub = store.add_subscription(Subscription(name="sub", profile_ids=[p1.id, p2.id]))
    server = store.add_server(Server(name="s1", port=1080, outbound_id=sub.id, outbound_type="subscription"))

    manager = ServerManager(store)
    target = manager.resolve_outbound_target(server)
    assert target.type == "balancer"
    assert set(target.profile_ids) == {p1.id, p2.id}


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


def test_server_list_shows_outbound_id(tmp_path, capsys):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="US proxy", kind="socks", outbound=SOCKS))
    server = Server(name="s1", port=1080, outbound_id=profile.id, outbound_type="profile")
    store.add_server(server)
    store.save()

    args = app.build_parser().parse_args(["server", "list"])
    assert app._server_command(store, args) == 0
    out = capsys.readouterr().out
    assert f"profile/{profile.id} (US proxy)" in out


def test_server_list_resolves_balancer_group(tmp_path, capsys, monkeypatch):
    from v2raycli.models import Group

    store = _store(tmp_path)
    p1 = store.add_profile(Profile(name="US proxy", kind="socks", outbound=SOCKS))
    p2 = store.add_profile(Profile(name="EU proxy", kind="socks", outbound=SOCKS))
    group = store.add_group(
        Group(name="fast", type="balancer", strategy="latency", profile_ids=[p1.id, p2.id])
    )
    server = Server(name="s1", port=1080, outbound_id=group.id, outbound_type="group",
                    traffic_api_port=19090)
    store.add_server(server)
    store.save()

    # Simulate a running engine reporting the most recent active outbound.
    from v2raycli import traffic
    monkeypatch.setattr(
        traffic, "read_active_outbound", lambda host, port, timeout=3.0: p2.id
    )
    fake_state = ServerState(server_id=server.id, pid=99999)
    monkeypatch.setattr(ServerState, "is_running", lambda self: True)
    monkeypatch.setattr(ServerManager, "get_state", lambda self, sid: fake_state)

    args = app.build_parser().parse_args(["server", "list"])
    assert app._server_command(store, args) == 0
    out = capsys.readouterr().out
    assert f"group/{group.id} (fast)" in out
    assert "latency" in out and "2 nodes" in out
    assert f"→ {p2.id} (EU proxy)" in out


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
    config, engine = mgr._generate_server_config(server)

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
    config, engine = mgr._generate_server_config(server)

    all_outbound_tags = [o.get("tag") for o in config.get("outbounds", [])]
    # Both member profiles and the balancer group should be in the config.
    assert b.id in all_outbound_tags
    assert c.id in all_outbound_tags
    # The group should have a urltest or selector construct.
    assert any(
        o.get("tag") == bal.id and o.get("type") in ("urltest", "selector")
        for o in config.get("outbounds", [])
    )


def _probe_result(profile, tcp_ms, tcp_status="ok"):
    from v2raycli.test.latency import EndpointResult

    return EndpointResult(profile_id=profile.id, name=profile.name, tcp_ms=tcp_ms, tcp_status=tcp_status)


def test_balancer_server_pins_to_fastest_reachable_endpoint(tmp_path, monkeypatch):
    """Starting a balancer server pins to the lowest-TCP-delay reachable node
    and drops dead endpoints."""
    from v2raycli import servers as servers_module
    from v2raycli.test import latency

    store = _store(tmp_path)
    fast = store.add_profile(Profile(name="fast", kind="socks", outbound=SOCKS))
    slow = store.add_profile(Profile(name="slow", kind="socks", outbound=SOCKS))
    dead = store.add_profile(Profile(name="dead", kind="socks", outbound=SOCKS))
    group = store.add_group(
        Group(name="bal", type="balancer", strategy="latency", profile_ids=[fast.id, slow.id, dead.id])
    )
    server = store.add_server(
        Server(name="s1", port=1080, outbound_id=group.id, outbound_type="group")
    )

    results = {
        fast.id: _probe_result(fast, 12.0),
        slow.id: _probe_result(slow, 200.0),
        dead.id: _probe_result(dead, None, "timeout"),
    }
    monkeypatch.setattr(
        latency, "probe_endpoint", lambda profile, timeout=5.0: results[profile.id]
    )

    mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")
    config, engine = mgr._generate_server_config(server)

    assert mgr.selected_pinned is not None
    assert mgr.selected_pinned.id == fast.id
    # The generated config should only contain the pinned node as its outbound.
    tags = [o.get("tag") for o in config.get("outbounds", [])]
    assert fast.id in tags
    assert slow.id not in tags and dead.id not in tags


def test_balancer_server_start_fails_when_all_endpoints_dead(tmp_path, monkeypatch):
    from v2raycli.test import latency

    store = _store(tmp_path)
    p1 = store.add_profile(Profile(name="a", kind="socks", outbound=SOCKS))
    p2 = store.add_profile(Profile(name="b", kind="socks", outbound=SOCKS))
    group = store.add_group(
        Group(name="bal", type="balancer", strategy="latency", profile_ids=[p1.id, p2.id])
    )
    server = store.add_server(
        Server(name="s1", port=1080, outbound_id=group.id, outbound_type="group")
    )

    monkeypatch.setattr(
        latency, "probe_endpoint",
        lambda profile, timeout=5.0: _probe_result(profile, None, "timeout"),
    )

    mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")
    with pytest.raises(ValueError, match="no reachable endpoint"):
        mgr._generate_server_config(server)


def test_balancer_server_failover_keeps_healthy_balancer(tmp_path, monkeypatch):
    """Failover-enabled server keeps a health-checked balancer over healthy
    nodes (fastest first) instead of pinning to one."""
    from v2raycli.test import latency

    store = _store(tmp_path)
    fast = store.add_profile(Profile(name="fast", kind="socks", outbound=SOCKS))
    slow = store.add_profile(Profile(name="slow", kind="socks", outbound=SOCKS))
    dead = store.add_profile(Profile(name="dead", kind="socks", outbound=SOCKS))
    group = store.add_group(
        Group(name="bal", type="balancer", strategy="latency", profile_ids=[fast.id, slow.id, dead.id])
    )
    server = store.add_server(
        Server(name="s1", port=1080, outbound_id=group.id, outbound_type="group",
               failover=True, failover_timeout=5)
    )

    results = {
        fast.id: _probe_result(fast, 12.0),
        slow.id: _probe_result(slow, 200.0),
        dead.id: _probe_result(dead, None, "timeout"),
    }
    monkeypatch.setattr(latency, "probe_endpoint", lambda profile, timeout=5.0: results[profile.id])

    mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")
    config, engine = mgr._generate_server_config(server)

    # Failover was active over the two healthy nodes with a 5s probe interval.
    assert mgr.failover_active == (2, 5)
    # The generated config must keep both healthy nodes as an urltest balancer
    # and the dead node must be dropped.
    urltest = next(o for o in config["outbounds"] if o.get("type") == "urltest")
    assert fast.id in urltest["outbounds"] and slow.id in urltest["outbounds"]
    assert dead.id not in urltest["outbounds"]
    assert urltest.get("interval") == "5s"
    assert urltest.get("interrupt_exist_connections") is True


def test_balancer_failover_single_healthy_degrades_to_pin(tmp_path, monkeypatch):
    from v2raycli.test import latency

    store = _store(tmp_path)
    a = store.add_profile(Profile(name="a", kind="socks", outbound=SOCKS))
    dead = store.add_profile(Profile(name="dead", kind="socks", outbound=SOCKS))
    group = store.add_group(
        Group(name="bal", type="balancer", strategy="latency", profile_ids=[a.id, dead.id])
    )
    server = store.add_server(
        Server(name="s1", port=1080, outbound_id=group.id, outbound_type="group",
               failover=True, failover_timeout=5)
    )

    monkeypatch.setattr(
        latency, "probe_endpoint",
        lambda profile, timeout=5.0: (
            _probe_result(a, 5.0) if profile.id == a.id else _probe_result(profile, None, "timeout")
        ),
    )

    mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")
    config, engine = mgr._generate_server_config(server)

    # Only one healthy node → degrade to a single pinned node.
    assert mgr.selected_pinned is not None and mgr.selected_pinned.id == a.id
    assert mgr.failover_active is None
    tags = [o.get("tag") for o in config.get("outbounds", [])]
    assert a.id in tags
    assert dead.id not in tags


def test_server_spawn_uses_args_kwarg(tmp_path, monkeypatch):
    """ServerManager._spawn must pass 'args' (not 'argv') to Popen."""
    import subprocess

    store = _store(tmp_path)
    mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")

    captured_kwargs = {}
    fake_proc = type("FakeProc", (), {"pid": 12345})()

    def fake_popen(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return fake_proc

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    argv = ["/usr/bin/sing-box", "run", "-c", "/tmp/cfg.json"]
    result = mgr._spawn(argv, tmp_path)

    assert result is fake_proc
    assert "args" in captured_kwargs, (
        f"Expected Popen to receive 'args' kwarg, got keys: {list(captured_kwargs.keys())}"
    )
    assert captured_kwargs["args"] == argv
    assert "argv" not in captured_kwargs, (
        "Popen received old 'argv' kwarg — the fix was not applied"
    )


def test_server_spawn_sets_start_new_session(tmp_path, monkeypatch):
    """ServerManager._spawn uses start_new_session on non-Windows."""
    import subprocess

    store = _store(tmp_path)
    mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")

    captured_kwargs = {}
    fake_proc = type("FakeProc", (), {"pid": 12345})()

    def fake_popen(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return fake_proc

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr("os.name", "posix")

    mgr._spawn(["/usr/bin/sing-box"], tmp_path)
    assert captured_kwargs.get("start_new_session") is True


def test_server_stale_states_pruned_on_load(tmp_path):
    """ServerManager prunes states for servers no longer in config."""
    store = _store(tmp_path)
    server = store.add_server(
        Server(name="s1", port=1080, outbound_id="abc", outbound_type="profile")
    )
    store.save()

    mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")
    mgr._states[server.id] = ServerState(server_id=server.id, pid=999999)
    mgr._save_states()

    # Remove the server from config
    store.remove_server(server.id)
    store.save()

    # Reload — stale state should be pruned
    mgr2 = ServerManager(store, runtime_dir=tmp_path / "runtime")
    assert server.id not in mgr2._states


def test_server_active_states_survive_load(tmp_path):
    """ServerManager keeps states for servers that still exist in config."""
    store = _store(tmp_path)
    server = store.add_server(
        Server(name="s1", port=1080, outbound_id="abc", outbound_type="profile")
    )
    store.save()

    mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")
    mgr._states[server.id] = ServerState(server_id=server.id, pid=None)
    mgr._save_states()

    mgr2 = ServerManager(store, runtime_dir=tmp_path / "runtime")
    assert server.id in mgr2._states
    assert mgr2._states[server.id].pid is None


def test_server_start_reports_immediate_crash(tmp_path, monkeypatch):
    """start() returns an error state when the engine exits right away."""
    import subprocess

    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    server = store.add_server(
        Server(name="crashy", port=10808, outbound_id=profile.id)
    )
    store.save()

    mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")

    # Fake a process that has already exited
    class FakeDeadProc:
        pid = 99999
        returncode = 1
        stderr = None
        _captured_stderr = ["FATAL: bind: address already in use"]

        def poll(self):
            return 1  # already exited

    def fake_popen(*args, **kwargs):
        return FakeDeadProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    # Patch locate_binary to skip download
    monkeypatch.setattr(
        "v2raycli.engines.binary.locate_binary",
        lambda engine, opts: tmp_path / "fake-bin",
    )

    state = mgr.start(server.id)
    assert state.error is not None
    assert "immediately" in state.error
    assert "FATAL" in state.error


def test_server_edit_name_and_port(tmp_path, capsys):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    server = store.add_server(
        Server(name="old", port=1080, outbound_id=profile.id, outbound_type="profile")
    )
    store.save()

    args = app.build_parser().parse_args(
        ["server", "edit", server.id, "--name", "new", "--port", "8180"]
    )
    assert app._server_command(store, args) == 0
    updated = store.get_server(server.id)
    assert updated.name == "new"
    assert updated.port == 8180
    assert "edited" in capsys.readouterr().out


def test_server_edit_switch_profile(tmp_path, capsys):
    store = _store(tmp_path)
    p1 = store.add_profile(Profile(name="p1", kind="socks", outbound=SOCKS))
    p2 = store.add_profile(Profile(name="p2", kind="socks", outbound=SOCKS))
    server = store.add_server(
        Server(name="s", port=1080, outbound_id=p1.id, outbound_type="profile")
    )
    store.save()

    args = app.build_parser().parse_args(
        ["server", "edit", server.id, "--profile", p2.id]
    )
    assert app._server_command(store, args) == 0
    updated = store.get_server(server.id)
    assert updated.outbound_id == p2.id
    assert updated.outbound_type == "profile"


def test_server_edit_switch_to_direct(tmp_path, capsys):
    from v2raycli.models import Group

    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    group = store.add_group(
        Group(name="g", type="balancer", strategy="latency", profile_ids=[profile.id, profile.id])
    )
    server = store.add_server(
        Server(name="s", port=1080, outbound_id=group.id, outbound_type="group")
    )
    store.save()

    args = app.build_parser().parse_args(
        ["server", "edit", server.id, "--direct"]
    )
    assert app._server_command(store, args) == 0
    updated = store.get_server(server.id)
    assert updated.outbound_type == "direct"
    assert updated.outbound_id == ""


def test_server_edit_unknown_id(tmp_path, capsys):
    store = _store(tmp_path)
    args = app.build_parser().parse_args(["server", "edit", "nope", "--name", "x"])
    assert app._server_command(store, args) == 1
    assert "unknown" in capsys.readouterr().err


def test_server_edit_unknown_profile(tmp_path, capsys):
    store = _store(tmp_path)
    server = store.add_server(
        Server(name="s", port=1080, outbound_id="abc", outbound_type="profile")
    )
    store.save()

    args = app.build_parser().parse_args(
        ["server", "edit", server.id, "--profile", "nope"]
    )
    assert app._server_command(store, args) == 1
    assert "unknown" in capsys.readouterr().err


def test_server_edit_protocol_and_listen(tmp_path, capsys):
    store = _store(tmp_path)
    server = store.add_server(
        Server(name="s", port=1080, protocol="mixed", listen="0.0.0.0", outbound_type="direct")
    )
    store.save()

    args = app.build_parser().parse_args(
        ["server", "edit", server.id, "--protocol", "http", "--listen", "127.0.0.1"]
    )
    assert app._server_command(store, args) == 0
    updated = store.get_server(server.id)
    assert updated.protocol == "http"
    assert updated.listen == "127.0.0.1"


# -- server-to-server forwarding (loop prevention) -------------------------


def test_server_add_accepts_server_ref(tmp_path, capsys):
    store = _store(tmp_path)
    target = store.add_server(Server(name="hop", port=1081))
    store.save()

    args = app.build_parser().parse_args(["server", "add", "--port", "1080", target.id])
    assert app._server_command(store, args) == 0
    server = store.get_server(capsys.readouterr().out.strip())
    assert server is not None
    assert server.outbound_type == "server"
    assert server.outbound_id == target.id


def test_server_edit_accepts_server_ref(tmp_path, capsys):
    store = _store(tmp_path)
    target = store.add_server(Server(name="hop", port=1081))
    server = store.add_server(Server(name="s1", port=1080, outbound_type="direct"))
    store.save()

    args = app.build_parser().parse_args(
        ["server", "edit", server.id, "--profile", target.id]
    )
    assert app._server_command(store, args) == 0
    updated = store.get_server(server.id)
    assert updated.outbound_type == "server"
    assert updated.outbound_id == target.id


def test_server_edit_rejects_self_reference(tmp_path, capsys):
    store = _store(tmp_path)
    server = store.add_server(Server(name="s1", port=1080, outbound_type="direct"))
    store.save()

    args = app.build_parser().parse_args(
        ["server", "edit", server.id, "--profile", server.id]
    )
    assert app._server_command(store, args) == 1
    assert "cannot forward to itself" in capsys.readouterr().err
    # Outbound unchanged.
    updated = store.get_server(server.id)
    assert updated.outbound_type == "direct"
    assert updated.outbound_id == ""


def test_server_edit_rejects_circular_chain(tmp_path, capsys):
    store = _store(tmp_path)
    a = store.add_server(Server(name="a", port=1080))
    b = store.add_server(Server(name="b", port=1081))
    store.get_server(a.id).outbound_type = "server"
    store.get_server(a.id).outbound_id = b.id
    store.save()

    args = app.build_parser().parse_args(["server", "edit", b.id, "--profile", a.id])
    assert app._server_command(store, args) == 1
    assert "circular server reference" in capsys.readouterr().err
    # b's outbound unchanged.
    updated = store.get_server(b.id)
    assert updated.outbound_type == "profile"
    assert updated.outbound_id == ""


def test_server_edit_allows_valid_chain(tmp_path, capsys):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    c = store.add_server(Server(name="c", port=1082, outbound_id=profile.id, outbound_type="profile"))
    b = store.add_server(Server(name="b", port=1081))
    a = store.add_server(Server(name="a", port=1080))
    store.save()

    # a -> b (server hop)
    args = app.build_parser().parse_args(["server", "edit", a.id, "--profile", b.id])
    assert app._server_command(store, args) == 0
    assert store.get_server(a.id).outbound_type == "server"
    assert store.get_server(a.id).outbound_id == b.id

    # b -> c (server hop)
    args = app.build_parser().parse_args(["server", "edit", b.id, "--profile", c.id])
    assert app._server_command(store, args) == 0
    assert store.get_server(b.id).outbound_type == "server"
    assert store.get_server(b.id).outbound_id == c.id


def test_resolve_server_outbound_builds_socks_hop(tmp_path):
    from v2raycli.outbounds.groups import resolve_outbound

    store = _store(tmp_path)
    target = store.add_server(
        Server(name="hop", port=1081, protocol="mixed", listen="127.0.0.1")
    )
    store.save()

    resolved = resolve_outbound(store, "server", target.id, default_engine="sing-box")
    assert resolved.type == "single"
    assert len(resolved.profiles) == 1
    profile = resolved.profiles[0]
    assert profile.kind == "socks"
    entry = profile.outbound["settings"]["servers"][0]
    assert entry["address"] == "127.0.0.1"
    assert entry["port"] == 1081


def test_resolve_server_outbound_http_protocol(tmp_path):
    from v2raycli.outbounds.groups import resolve_outbound

    store = _store(tmp_path)
    target = store.add_server(Server(name="web", port=3128, protocol="http"))
    store.save()
    resolved = resolve_outbound(store, "server", target.id, default_engine="sing-box")
    assert resolved.profiles[0].kind == "http"


def test_resolve_server_outbound_includes_auth(tmp_path):
    from v2raycli.outbounds.groups import resolve_outbound

    store = _store(tmp_path)
    target = store.add_server(Server(
        name="locked", port=1081,
        auth={"enabled": True, "username": "u", "password": "p"},
    ))
    store.save()
    resolved = resolve_outbound(store, "server", target.id, default_engine="sing-box")
    users = resolved.profiles[0].outbound["settings"]["servers"][0]["users"]
    assert users == [{"user": "u", "pass": "p"}]


def test_resolve_server_outbound_rejects_cycle(tmp_path):
    from v2raycli.outbounds.groups import resolve_outbound

    store = _store(tmp_path)
    a = store.add_server(Server(name="a", port=1080))
    b = store.add_server(Server(name="b", port=1081))
    store.get_server(a.id).outbound_type = "server"
    store.get_server(a.id).outbound_id = b.id
    store.get_server(b.id).outbound_type = "server"
    store.get_server(b.id).outbound_id = a.id
    store.save()

    with pytest.raises(ValueError, match="circular server reference"):
        resolve_outbound(store, "server", b.id, default_engine="sing-box", from_server_id=a.id)


def test_server_config_forwards_through_other_server(tmp_path):
    store = _store(tmp_path)
    target = store.add_server(Server(name="hop", port=1081, listen="127.0.0.1"))
    server = store.add_server(Server(
        name="s1", port=1080, outbound_id=target.id, outbound_type="server"
    ))
    mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")
    config, engine = mgr._generate_server_config(server)

    socks = next(o for o in config["outbounds"] if o.get("type") == "socks")
    assert socks["server"] == "127.0.0.1"
    assert socks["server_port"] == 1081


def test_server_list_shows_server_outbound_label(tmp_path, capsys):
    store = _store(tmp_path)
    target = store.add_server(Server(name="hop", port=1081))
    server = Server(name="s1", port=1080, outbound_id=target.id, outbound_type="server")
    store.add_server(server)
    store.save()

    args = app.build_parser().parse_args(["server", "list"])
    assert app._server_command(store, args) == 0
    assert f"server/{target.id} (hop)" in capsys.readouterr().out


# -- engine stderr error detection ----------------------------------------


def test_check_stderr_returns_none_for_empty():
    assert _check_stderr_for_errors([]) is None
    assert _check_stderr_for_errors(None) is None  # type: ignore[arg-type]


def test_check_stderr_returns_none_for_clean_logs():
    lines = [
        "INFO[0000] inbound mixed listening on 127.0.0.1:1080",
        "INFO[0000] outbound direct tag=direct",
    ]
    assert _check_stderr_for_errors(lines) is None


def test_check_stderr_detects_handshake_failure():
    lines = [
        "INFO listening on 127.0.0.1:1080",
        "ERRO[0001] dial tcp 1.2.3.4:443: failed to handshake",
    ]
    result = _check_stderr_for_errors(lines)
    assert result is not None
    assert "engine reports errors" in result
    assert "failed to handshake" in result


def test_check_stderr_detects_connection_refused():
    lines = ["dial tcp 1.2.3.4:443: connection refused"]
    result = _check_stderr_for_errors(lines)
    assert result is not None
    assert "connection refused" in result


def test_check_stderr_detects_address_in_use():
    lines = ["bind: address already in use"]
    result = _check_stderr_for_errors(lines)
    assert result is not None
    assert "address already in use" in result


def test_check_stderr_includes_firewall_hint_on_windows(monkeypatch):
    import os as _os
    monkeypatch.setattr(_os, "name", "nt")
    lines = ["dial tcp 1.2.3.4:443: i/o timeout"]
    result = _check_stderr_for_errors(lines)
    assert result is not None
    assert "firewall" in result.lower()
    assert "Firewall" in result
