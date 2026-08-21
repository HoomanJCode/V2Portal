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
