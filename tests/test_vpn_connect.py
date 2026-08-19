from v2raycli.connection import ConnectionController
from v2raycli.outbounds.vpn import add_openconnect, add_openvpn
from v2raycli.storage import ConfigStore


def _store(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    return store


def test_vpn_argv_building(tmp_path):
    store = _store(tmp_path)
    p1 = store.add_profile(add_openvpn("v", config_path="/tmp/x.ovpn", args=["--verb", "3"]))
    p2 = store.add_profile(add_openconnect("oc", "vpn.example.com", args=["--user", "bob"]))

    ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
    assert ctl.vpn_argv("openvpn", "/usr/bin/openvpn", p1.vpn, p1) == [
        "/usr/bin/openvpn",
        "--verb",
        "3",
        "--config",
        "/tmp/x.ovpn",
    ]
    assert ctl.vpn_argv("openconnect", "/usr/bin/openconnect", p2.vpn, p2) == [
        "/usr/bin/openconnect",
        "--user",
        "bob",
        "vpn.example.com",
    ]


def test_connect_openvpn_mocked(tmp_path, monkeypatch):
    store = _store(tmp_path)
    fake = tmp_path / "openvpn"
    fake.write_text("#!/bin/sh\necho started\nexec sleep 30\n")
    fake.chmod(0o755)
    monkeypatch.setattr("shutil.which", lambda name: str(fake) if name == "openvpn" else None)

    profile = store.add_profile(add_openvpn("v", config_path="/tmp/x.ovpn"))
    ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
    status = ctl.connect(profile)
    assert status.state == "connected"
    assert status.engine == "openvpn"
    ctl.disconnect()


def test_vpn_missing_client_maps_error(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: None)
    profile = store.add_profile(add_openconnect("oc", "vpn.example.com"))

    ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
    status = ctl.connect(profile)
    assert status.state == "error"
    assert "openconnect" in status.error
    assert "install" in status.error
