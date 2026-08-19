import json

import httpx
import pytest

from v2raycli import traffic
from v2raycli.connection import ConnectionController
from v2raycli.models import Group, Profile, Settings
from v2raycli.storage import ConfigStore

SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}
CHECK_GUARD = 'if [ "$1" = "check" ] || [ "$2" = "-test" ]; then exit 0; fi'


def test_read_traffic_parses_connections(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"connections": [], "uploadTotal": 1234, "downloadTotal": 5678}

    monkeypatch.setattr(traffic.httpx, "get", lambda url, timeout=None: FakeResp())
    assert traffic.read_traffic("127.0.0.1", 9090) == {"up": 1234, "down": 5678}


def test_read_traffic_returns_none_on_error(monkeypatch):
    monkeypatch.setattr(
        traffic.httpx, "get", lambda url, timeout=None: (_ for _ in ()).throw(httpx.ConnectError("x"))
    )
    assert traffic.read_traffic("127.0.0.1", 9090) is None


def test_read_traffic_returns_none_on_bad_json(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("bad json")

    monkeypatch.setattr(traffic.httpx, "get", lambda url, timeout=None: FakeResp())
    assert traffic.read_traffic("127.0.0.1", 9090) is None


def test_read_traffic_returns_none_on_wrong_shape(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return []

    monkeypatch.setattr(traffic.httpx, "get", lambda url, timeout=None: FakeResp())
    assert traffic.read_traffic("127.0.0.1", 9090) is None


def test_traffic_disabled_when_api_off(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
    ctl.status.state = "connected"
    assert ctl.traffic() is None


def test_settings_roundtrip_traffic_api(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    store.config.settings.traffic_api = True
    store.config.settings.traffic_api_port = 1234
    store.save()

    reloaded = ConfigStore(tmp_path / "c.json")
    reloaded.load()
    assert reloaded.config.settings.traffic_api is True
    assert reloaded.config.settings.traffic_api_port == 1234


def _fake_binary(tmp_path):
    binary = tmp_path / "sing-box"
    binary.write_text("#!/bin/sh\n" + CHECK_GUARD + '\necho "started"\nexec sleep 30\n')
    binary.chmod(0o755)
    return binary


def test_controller_records_traffic_on_disconnect(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    store.config.settings.traffic_api = True
    store.config.settings.traffic_api_port = 19090
    binary = _fake_binary(tmp_path)
    store.config.engines["sing-box"] = {"binary_path": str(binary), "version": "x"}

    ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
    status = ctl.connect(profile)
    assert status.state == "connected"

    monkeypatch.setattr(traffic, "read_traffic", lambda host, port, timeout=3.0: {"up": 111, "down": 222})
    ctl.disconnect()

    assert profile.traffic_up == 111
    assert profile.traffic_down == 222


def test_controller_ignores_malformed_traffic_on_disconnect(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    store.config.settings.traffic_api = True
    store.config.settings.traffic_api_port = 19090
    binary = _fake_binary(tmp_path)
    store.config.engines["sing-box"] = {"binary_path": str(binary), "version": "x"}

    ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
    assert ctl.connect(profile).state == "connected"
    monkeypatch.setattr(traffic, "read_traffic", lambda host, port, timeout=3.0: {"up": "bad"})

    ctl.disconnect()

    assert profile.traffic_up == 0
    assert profile.traffic_down == 0


def test_controller_ignores_malformed_persisted_traffic_on_disconnect(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    profile.traffic_up = "bad"
    profile.traffic_down = None
    store.config.settings.traffic_api = True
    store.config.settings.traffic_api_port = 19090
    binary = _fake_binary(tmp_path)
    store.config.engines["sing-box"] = {"binary_path": str(binary), "version": "x"}

    ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
    assert ctl.connect(profile).state == "connected"
    monkeypatch.setattr(traffic, "read_traffic", lambda host, port, timeout=3.0: {"up": 111, "down": 222})

    ctl.disconnect()

    assert profile.traffic_up == "bad"
    assert profile.traffic_down is None


def test_controller_records_traffic_for_group(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    a = store.add_profile(Profile(name="a", kind="socks", outbound=SOCKS))
    b = store.add_profile(Profile(name="b", kind="socks", outbound=SOCKS))
    group = store.add_group(Group(name="g", type="balancer", strategy="random", profile_ids=[a.id, b.id]))
    store.config.settings.traffic_api = True
    store.config.settings.traffic_api_port = 19090
    binary = _fake_binary(tmp_path)
    store.config.engines["sing-box"] = {"binary_path": str(binary), "version": "x"}

    ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
    assert ctl.connect(group).state == "connected"
    monkeypatch.setattr(traffic, "read_traffic", lambda host, port, timeout=3.0: {"up": 7, "down": 9})
    ctl.disconnect()

    assert group.traffic_up == 7
    assert group.traffic_down == 9
    assert a.traffic_up == 0 and b.traffic_up == 0
