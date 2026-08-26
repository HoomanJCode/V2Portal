from types import SimpleNamespace

import pytest

pytest.importorskip("prompt_toolkit")

from v2raycli.models import Profile, Server
from v2raycli.storage import ConfigStore
from v2raycli.tui import servers_screen

SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}


def _store(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    return store


class FakeManager:
    def __init__(self, running=()):
        self._running = set(running)

    def get_state(self, server_id):
        if server_id in self._running:
            return SimpleNamespace(is_running=lambda: True)
        return None

    def list_running(self):
        return list(self._running)

    def start(self, server_id):
        return SimpleNamespace(error=None)

    def stop(self, server_id):
        return True

    def stop_all(self):
        return 0


def test_dashboard_renders_server_rows(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="upstream", kind="socks", outbound=SOCKS))
    sv = store.add_server(Server(
        name="local", port=1081, protocol="mixed", outbound_id=p.id, outbound_type="profile",
    ))
    store.save()

    mgr = FakeManager(running=[sv.id])
    servers_screen._render(store, mgr)

    out = capsys.readouterr().out
    assert sv.id in out
    assert "1081" in out
    assert "local" in out
    assert "running" in out
    assert "upstream" in out


def test_dashboard_outbound_hint_types(tmp_path):
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="node", kind="socks", outbound=SOCKS))
    direct = Server(name="d", port=1, outbound_type="direct")
    profile = Server(name="p", port=2, outbound_type="profile", outbound_id=p.id)
    dangling = Server(name="x", port=3, outbound_type="group", outbound_id="nope")
    assert servers_screen._outbound_hint(store, direct) == "direct"
    assert servers_screen._outbound_hint(store, profile) == "node"
    assert servers_screen._outbound_hint(store, dangling) == "nope"


def test_dashboard_start_flow(tmp_path, monkeypatch):
    store = _store(tmp_path)
    sv = store.add_server(Server(name="local", port=1081))
    store.save()

    actions = iter(["start", sv.id, "back"])
    monkeypatch.setattr(servers_screen.widgets, "menu", lambda *args: next(actions))
    monkeypatch.setattr(servers_screen, "ServerManager", lambda store: FakeManager())
    messages = []
    monkeypatch.setattr(
        servers_screen.widgets,
        "show_message",
        lambda title, text: messages.append((title, text)),
    )

    servers_screen.run(store)

    assert messages[0] == ("Started", f"{sv.id} listening on :1081")


def test_dashboard_start_all_and_stop_all(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.add_server(Server(name="a", port=1081, enabled=True))
    store.add_server(Server(name="b", port=1082, enabled=False))
    store.save()

    actions = iter(["start_all", "stop_all", "back"])
    monkeypatch.setattr(servers_screen.widgets, "menu", lambda *args: next(actions))
    monkeypatch.setattr(servers_screen, "ServerManager", lambda store: FakeManager())
    messages = []
    monkeypatch.setattr(
        servers_screen.widgets,
        "show_message",
        lambda title, text: messages.append((title, text)),
    )

    servers_screen.run(store)

    assert ("Start all", "All enabled servers started.") in messages
    assert ("Stop all", "Stopped 0 server(s)") in messages
