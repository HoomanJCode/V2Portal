import pytest

pytest.importorskip("prompt_toolkit")

from v2raycli.models import Group, Profile, Server
from v2raycli.storage import ConfigStore
from v2raycli.tui import groups_screen

SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}


def _store(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    return store


def test_groups_screen_renders_tree(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="node", kind="socks", outbound=SOCKS))
    sv = store.add_server(Server(name="local", port=1081))
    g = store.add_group(Group(name="fast", type="balancer", strategy="latency",
                              profile_ids=[p.id], server_ids=[sv.id]))
    store.save()

    groups_screen._render_tree(store)

    out = capsys.readouterr().out
    assert f"{g.id}  balancer fast (latency)" in out
    assert "node" in out
    assert "local" in out


def test_groups_screen_empty_message(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.save()
    messages = []
    monkeypatch.setattr(
        groups_screen.widgets,
        "show_message",
        lambda title, text: messages.append((title, text)),
    )
    groups_screen._render_tree(store)
    assert messages == [("No groups", "Add a group, subscription, or server first.")]


def test_groups_screen_back_exits(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    store.save()
    monkeypatch.setattr(groups_screen.widgets, "menu", lambda *args: "back")

    groups_screen.run(store)  # must return without raising
