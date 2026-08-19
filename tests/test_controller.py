from v2raycli import connection
from v2raycli.connection import ConnectionController
from v2raycli.models import Profile, RoutingConfig, RoutingRule
from v2raycli.storage import ConfigStore

SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}

# Exit 0 when invoked for validation (check / -test), otherwise run the body.
CHECK_GUARD = 'if [ "$1" = "check" ] || [ "$2" = "-test" ]; then exit 0; fi'


def _store(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    return store


def _fake(tmp_path, body):
    binary = tmp_path / "sing-box"
    binary.write_text("#!/bin/sh\n" + body + "\n")
    binary.chmod(0o755)
    return binary


def test_connect_proxy(tmp_path):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    binary = _fake(tmp_path, CHECK_GUARD + '\necho "started"\nexec sleep 30')
    store.config.engines["sing-box"] = {"binary_path": str(binary), "version": "x"}

    ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
    status = ctl.connect(profile)
    assert status.state == "connected"
    assert status.target_name == "s"
    assert status.engine == "sing-box"
    assert status.inbound["mixed_port"] == 1080
    assert status.inbound["urls"][0].startswith("socks5://")
    ctl.disconnect()
    assert ctl.status.state == "idle"


def test_missing_binary_maps_to_error(tmp_path):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    store.config.engines["sing-box"] = {"binary_path": str(tmp_path / "nope"), "version": "x"}

    ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
    status = ctl.connect(profile)
    assert status.state == "error"
    assert "binary" in status.error


def test_inbound_status_honors_allow_lan(tmp_path):
    store = _store(tmp_path)
    store.config.settings.allow_lan = False

    info = ConnectionController(store)._inbound_info(store.config.settings)

    assert info["listen"] == "127.0.0.1"
    assert info["urls"] == ["socks5://127.0.0.1:1080", "http://127.0.0.1:1080"]
    assert "lan" not in info


def test_engine_immediate_exit_maps_to_error(tmp_path):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    binary = _fake(tmp_path, CHECK_GUARD + '\necho "address already in use"\nexit 1')
    store.config.engines["sing-box"] = {"binary_path": str(binary), "version": "x"}

    ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
    status = ctl.connect(profile)
    assert status.state == "error"
    assert "address already in use" in status.error


def test_xray_geo_sets_asset_env(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.config.settings.default_engine = "xray"
    store.config.routing = RoutingConfig(
        mode="split", rules=[RoutingRule(action="direct", match={"geoip": ["cn"]})]
    )
    profile = store.add_profile(Profile(name="x", kind="socks", outbound=SOCKS))

    captured = {}

    class FakeProc:
        pid = 123

        def start(self, argv, env=None):
            captured["argv"] = argv
            captured["env"] = env

        def stop(self):
            pass

        def is_running(self):
            return True

        def logs(self):
            return []

    monkeypatch.setattr(connection, "Proc", FakeProc)
    monkeypatch.setattr(
        connection, "locate_binary", lambda engine, options, bin_dir=None: tmp_path / "xray"
    )
    monkeypatch.setattr(
        connection, "validate_config", lambda engine, path, binary=None, env=None: None
    )
    geo_dir = tmp_path / "geo"
    monkeypatch.setattr(
        connection, "ensure_geo_assets", lambda engine, geo_dir=None: geo_dir
    )

    ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path, geo_dir=geo_dir)
    status = ctl.connect(profile)
    assert status.state == "connected"
    assert captured["env"]["XRAY_LOCATION_ASSET"] == str(geo_dir)


def test_switch_and_disconnect(tmp_path):
    store = _store(tmp_path)
    a = store.add_profile(Profile(name="a", kind="socks", outbound=SOCKS))
    b = store.add_profile(Profile(name="b", kind="socks", outbound=SOCKS))
    binary = _fake(tmp_path, CHECK_GUARD + '\necho "started"\nexec sleep 30')
    store.config.engines["sing-box"] = {"binary_path": str(binary), "version": "x"}

    ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
    assert ctl.connect(a).target_name == "a"
    assert ctl.switch(b).target_name == "b"
    ctl.disconnect()
    assert ctl.status.state == "idle"
    assert not ctl.proc.is_running()
