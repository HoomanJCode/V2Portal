from types import SimpleNamespace

from v2raycli.models import Profile
from v2raycli.storage import ConfigStore
from v2raycli.tui import connection_screen


SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}


class _FakeSession:
    answers = iter(())

    def prompt(self, _text):
        return next(self.answers)


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

        def connect(self, selection):
            self.connected.append(selection)
            return connected(selection)

        def switch(self, selection):
            self.switched.append(selection)
            return connected(selection)

        def disconnect(self):
            self.disconnected = True

    controller = FakeController()
    _FakeSession.answers = iter(["s", "d"])
    monkeypatch.setattr(connection_screen, "PromptSession", _FakeSession)
    monkeypatch.setattr(
        connection_screen.widgets,
        "pick_profile",
        lambda profiles, groups: ("profile", second.id),
    )
    monkeypatch.setattr(connection_screen, "_render", lambda status: None)

    connection_screen.run(store, controller, first)

    assert controller.connected == [first]
    assert controller.switched == [second]
    assert controller.disconnected is True
