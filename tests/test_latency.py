from pathlib import Path

from v2raycli.engines.binary import BinaryError
from v2raycli.models import Profile, Subscription
from v2raycli.storage import ConfigStore
from v2raycli.test import latency

SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}


def _store(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    return store


class FakeProc:
    """Records start/stop without spawning a real process."""

    instances: list["FakeProc"] = []

    def __init__(self):
        self.argv = None
        self.stopped = False
        FakeProc.instances.append(self)

    def start(self, argv, env=None):
        self.argv = argv

    def stop(self, grace_seconds=2.0):
        self.stopped = True


def _install_fakes(monkeypatch, captured):
    FakeProc.instances.clear()
    monkeypatch.setattr(latency, "Proc", FakeProc)
    monkeypatch.setattr(latency, "locate_binary", lambda *a, **k: Path("/fake/sing-box"))
    monkeypatch.setattr(latency, "_wait_port", lambda *a, **k: True)

    def fake_write(engine, config_dict):
        captured["engine"] = engine
        captured["config"] = config_dict
        return str(Path("/tmp") / "v2raycli-probe.json")

    monkeypatch.setattr(latency, "_write_temp_config", fake_write)


def test_build_test_config_routes_through_profile(tmp_path):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))

    engine, cfg = latency.build_test_config(profile, store.config.settings, 9999)

    assert engine == "sing-box"
    assert cfg["route"]["final"] == profile.id
    inbound = cfg["inbounds"][0]
    assert inbound["listen"] == "127.0.0.1"
    assert inbound["listen_port"] == 9999
    assert "socks" in {o.get("type") for o in cfg["outbounds"]}


def test_test_profile_success_structured_result(tmp_path, monkeypatch):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))

    captured: dict = {}
    _install_fakes(monkeypatch, captured)
    monkeypatch.setattr(latency, "_http_latency", lambda url, port, timeout=10.0: (True, 42.0, ""))
    monkeypatch.setattr(latency, "_connect_ms", lambda port, host, dst_port, timeout=10.0: 15.0)

    result = latency.test_profile(profile, store.config.settings)

    assert result.ok is True
    assert result.latency_ms == 42.0
    assert result.connect_ms == 15.0
    assert result.engine == "sing-box"
    assert result.name == "s"
    assert result.error == ""

    # the runner was started against the fake binary with the probe config
    proc = FakeProc.instances[-1]
    assert proc.argv[0] == "/fake/sing-box"
    assert proc.argv[1] == "run"
    assert "v2raycli-probe.json" in proc.argv[3]
    assert captured["config"]["route"]["final"] == profile.id
    # process is always cleaned up
    assert proc.stopped is True


def test_test_profile_cleanup_on_http_failure(tmp_path, monkeypatch):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))

    captured: dict = {}
    _install_fakes(monkeypatch, captured)
    monkeypatch.setattr(
        latency, "_http_latency", lambda url, port, timeout=10.0: (False, 500.0, "boom")
    )

    result = latency.test_profile(profile, store.config.settings)

    assert result.ok is False
    assert result.error == "boom"
    assert FakeProc.instances[-1].stopped is True


def test_test_profile_binary_error_returns_result(tmp_path, monkeypatch):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))

    FakeProc.instances.clear()
    monkeypatch.setattr(latency, "Proc", FakeProc)
    monkeypatch.setattr(
        latency, "locate_binary", lambda *a, **k: (_ for _ in ()).throw(BinaryError("nope"))
    )

    result = latency.test_profile(profile, store.config.settings)

    assert result.ok is False
    assert result.error == "nope"
    # no process was ever started
    assert FakeProc.instances == []


def test_test_profile_vpn_skipped(tmp_path, monkeypatch):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="vpn", kind="openvpn", vpn={"type": "openvpn"}))

    called: dict = {"locate": False}
    monkeypatch.setattr(
        latency, "locate_binary", lambda *a, **k: called.__setitem__("locate", True)
    )

    result = latency.test_profile(profile, store.config.settings)

    assert result.not_testable is True
    assert result.ok is False
    assert called["locate"] is False


def test_url_authority():
    assert latency._url_authority("http://example.com/x") == ("example.com", 80)
    assert latency._url_authority("https://example.com:8443/x") == ("example.com", 8443)
    assert latency._url_authority("https://example.com/") == ("example.com", 443)


def test_scope_selectors(tmp_path):
    store = _store(tmp_path)
    sub = store.add_subscription(Subscription(name="sub"))
    p1 = store.add_profile(Profile(name="a", kind="socks", outbound=SOCKS, subscription_id=sub.id))
    p2 = store.add_profile(Profile(name="b", kind="socks", outbound=SOCKS))

    assert [p.id for p in latency.select_profiles(store, "all")] == [p1.id, p2.id]
    assert [p.id for p in latency.select_profiles(store, ("subscription", sub.id))] == [p1.id]
    assert [p.id for p in latency.select_profiles(store, ("profiles", [p2.id]))] == [p2.id]
    assert latency.select_profiles(store, "bogus") == []


def test_test_many_returns_in_input_order(tmp_path, monkeypatch):
    store = _store(tmp_path)
    a = store.add_profile(Profile(name="a", kind="socks", outbound=SOCKS))
    b = store.add_profile(Profile(name="b", kind="socks", outbound=SOCKS))

    def fake(profile, settings, engines=None, bin_dir=None):
        return latency.TestResult(
            profile_id=profile.id, name=profile.name, ok=True, latency_ms=10.0
        )

    monkeypatch.setattr(latency, "test_profile", fake)

    results = latency.test_many([a, b], store.config.settings)

    assert [r.profile_id for r in results] == [a.id, b.id]
