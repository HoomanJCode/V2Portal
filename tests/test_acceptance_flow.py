from pathlib import Path

from v2raycli import app, connection
from v2raycli.models import Profile, RoutingConfig, Subscription
from v2raycli.routing.rules import add_rule
from v2raycli.storage import ConfigStore
from v2raycli.test import latency
from v2raycli.tui import manage


SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}


def _store(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    return store


def test_mocked_full_flow_from_subscription_to_disconnect(tmp_path, monkeypatch):
    store = _store(tmp_path)
    subscription = Subscription(name="provider", url="https://example.test/sub")
    imported = Profile(
        name="node",
        kind="socks",
        outbound=SOCKS,
        subscription_id=subscription.id,
        source="subscription",
    )
    inputs = iter(["provider", subscription.url])

    monkeypatch.setattr(manage.widgets, "menu", lambda *args: "sub")
    monkeypatch.setattr(manage.widgets, "input_text", lambda *args: next(inputs))
    monkeypatch.setattr(
        manage,
        "import_subscription",
        lambda name, url: (subscription, [imported], []),
    )

    manage._add(store)

    profile = store.config.profiles[0]
    assert store.config.subscriptions == [subscription]
    assert profile.subscription_id == subscription.id

    second = store.add_profile(Profile(name="backup", kind="socks", outbound=SOCKS))
    store.config.routing = RoutingConfig(
        mode="split",
        rules=[add_rule("proxy", {"domains": ["example.com"]}, profile.id)],
    )

    class FakeProc:
        instances = []

        def __init__(self):
            self.running = False
            self.starts = []
            self.stops = 0
            FakeProc.instances.append(self)

        @property
        def pid(self):
            return 1234

        def start(self, argv, env=None):
            self.starts.append((argv, env))
            self.running = True

        def is_running(self):
            return self.running

        def logs(self):
            return []

        def stop(self, grace_seconds=2.0):
            self.stops += 1
            self.running = False

    monkeypatch.setattr(connection, "Proc", FakeProc)
    monkeypatch.setattr(connection, "locate_binary", lambda *args, **kwargs: Path("/fake/sing-box"))
    monkeypatch.setattr(connection, "validate_config", lambda *args, **kwargs: None)
    monkeypatch.setattr(connection.time, "sleep", lambda *_args: None)

    controller = connection.ConnectionController(store, runtime_dir=tmp_path)
    assert controller.connect(profile).state == "connected"
    assert controller.status.target_name == "node"
    assert controller.switch(second).target_name == "backup"
    controller.disconnect()
    assert controller.status.state == "idle"
    assert FakeProc.instances[-1].stops >= 1

    monkeypatch.setattr(
        latency,
        "test_many",
        lambda profiles, settings, engines=None: [
            latency.TestResult(profile_id=p.id, name=p.name, ok=True, latency_ms=5.0)
            for p in profiles
        ],
    )
    monkeypatch.setattr(latency, "save_results", lambda *args, **kwargs: None)
    monkeypatch.setattr(latency, "render_table", lambda *args, **kwargs: None)

    assert app._test(store, "all") == 0
    assert profile in store.config.profiles
