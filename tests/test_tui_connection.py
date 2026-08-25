from types import SimpleNamespace

import pytest

pytest.importorskip("prompt_toolkit")

from v2raycli.models import Profile
from v2raycli.storage import ConfigStore
from v2raycli.tui import app_screen, connection_screen


SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}


class _FakeSession:
    answers = iter(())

    def prompt(self, _text):
        return next(self.answers)


def test_connection_screen_disconnects_on_interrupt(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    profile = store.add_profile(Profile(name="first", kind="socks", outbound=SOCKS))

    class FakeController:
        def __init__(self):
            self.disconnected = False

        def connect(self, selection):
            return SimpleNamespace(state="connected", target_name=selection.name)

        def disconnect(self):
            self.disconnected = True

        def traffic(self):
            return None

    class InterruptSession:
        def prompt(self, _text):
            raise KeyboardInterrupt

    controller = FakeController()
    monkeypatch.setattr(connection_screen, "PromptSession", InterruptSession)
    monkeypatch.setattr(connection_screen, "_render", lambda *args: None)

    connection_screen.run(store, controller, profile)

    assert controller.disconnected is True


def test_main_screen_disconnects_on_interrupt(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    controllers = []

    class FakeController:
        def __init__(self, _store):
            self.disconnected = False
            controllers.append(self)

        def disconnect(self):
            self.disconnected = True

    monkeypatch.setattr(app_screen, "ConnectionController", FakeController)
    monkeypatch.setattr(app_screen, "run_manage", lambda _store, _controller=None: None)
    monkeypatch.setattr(app_screen.widgets, "show_message", lambda *args: None)
    monkeypatch.setattr(app_screen.widgets, "menu", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt))

    assert app_screen.run(store) == 0
    assert controllers[0].disconnected is True


def test_fresh_tui_guides_user_to_manage(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    events = []

    class FakeController:
        def __init__(self, _store):
            pass

        def disconnect(self):
            events.append("disconnect")

    monkeypatch.setattr(app_screen, "ConnectionController", FakeController)
    monkeypatch.setattr(app_screen, "run_manage", lambda _store, _controller=None: events.append("manage"))
    monkeypatch.setattr(app_screen.widgets, "show_message", lambda *args: events.append("welcome"))
    monkeypatch.setattr(app_screen.widgets, "menu", lambda *args: "quit")

    assert app_screen.run(store) == 0
    assert events == ["welcome", "manage", "disconnect"]


def test_tui_action_error_returns_to_main_menu(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    events = []
    actions = iter(["manage", "quit"])

    class FakeController:
        def __init__(self, _store):
            pass

        def disconnect(self):
            events.append("disconnect")

    def fail_manage(_store, _controller=None):
        raise ValueError("invalid user input")

    monkeypatch.setattr(app_screen, "ConnectionController", FakeController)
    monkeypatch.setattr(app_screen, "run_manage", fail_manage)
    monkeypatch.setattr(app_screen.widgets, "menu", lambda *args: next(actions))
    monkeypatch.setattr(
        app_screen.widgets,
        "show_message",
        lambda title, text: events.append((title, text)),
    )

    assert app_screen.run(store) == 0
    assert ("Action failed", "invalid user input") in events
    assert events[-1] == "disconnect"


def test_tui_connect_dispatches_selected_profile(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    profile = store.add_profile(Profile(name="selected", kind="socks", outbound=SOCKS))
    connected = []

    monkeypatch.setattr(
        app_screen.widgets,
        "pick_profile",
        lambda profiles, groups, subscriptions=(): ("profile", profile.id),
    )
    monkeypatch.setattr(
        app_screen,
        "run_connection",
        lambda current_store, controller, selection: connected.append(selection),
    )

    app_screen._connect(store, object())

    assert connected == [profile]


def test_connection_screen_switches_target(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    first = store.add_profile(Profile(name="first", kind="socks", outbound=SOCKS))
    second = store.add_profile(Profile(name="second", kind="socks", outbound=SOCKS))

    connected = lambda profile: SimpleNamespace(
        state="connected", target_name=profile.name, error=None
    )

    class FakeController:
        def __init__(self):
            self.connected = []
            self.switched = []
            self.disconnected = False
            self.traffic_calls = 0

        def connect(self, selection):
            self.connected.append(selection)
            return connected(selection)

        def switch(self, selection):
            self.switched.append(selection)
            return connected(selection)

        def disconnect(self):
            self.disconnected = True

        def traffic(self):
            self.traffic_calls += 1
            return {"up": 1024, "down": 2048}

    controller = FakeController()
    _FakeSession.answers = iter(["s", "d"])
    monkeypatch.setattr(connection_screen, "PromptSession", _FakeSession)
    monkeypatch.setattr(
        connection_screen.widgets,
        "pick_profile",
        lambda profiles, groups, subscriptions=(): ("profile", second.id),
    )
    rendered = []
    monkeypatch.setattr(
        connection_screen,
        "_render",
        lambda status, traffic=None: rendered.append((status.target_name, traffic)),
    )

    connection_screen.run(store, controller, first)

    assert controller.connected == [first]
    assert controller.switched == [second]
    assert controller.disconnected is True
    assert controller.traffic_calls == 2
    assert rendered == [("first", {"up": 1024, "down": 2048}), ("second", {"up": 1024, "down": 2048})]
