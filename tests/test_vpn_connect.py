from v2portal.connection import ConnectionController
from v2portal.models import Profile
from v2portal.outbounds.vpn import add_openconnect, add_openvpn
from v2portal.storage import ConfigStore

from conftest import make_fake_script


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
    fake = make_fake_script(tmp_path, "openvpn", 'echo started\nexec sleep 30')
    monkeypatch.setattr("shutil.which", lambda name: fake if name == "openvpn" else None)

    config_path = tmp_path / "client.ovpn"
    config_path.write_text("client\n")
    profile = store.add_profile(add_openvpn("v", config_path=str(config_path)))
    ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
    status = ctl.connect(profile)
    assert status.state == "connected"
    assert status.engine == "openvpn"
    ctl.disconnect()


def test_inline_openvpn_config_removed_on_disconnect(tmp_path, monkeypatch):
    store = _store(tmp_path)
    fake = make_fake_script(tmp_path, "openvpn", "exec sleep 30")
    monkeypatch.setattr("shutil.which", lambda name: fake if name == "openvpn" else None)

    profile = store.add_profile(add_openvpn("v", inline="client\nsecret\n"))
    ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
    assert ctl.connect(profile).state == "connected"
    inline_path = tmp_path / f"{profile.id}.ovpn"
    assert inline_path.read_text(encoding="utf-8") == "client\nsecret\n"

    ctl.disconnect()

    assert not inline_path.exists()


def test_inline_openvpn_config_removed_after_launch_failure(tmp_path, monkeypatch):
    store = _store(tmp_path)
    fake = make_fake_script(tmp_path, "openvpn", "exit 1")
    monkeypatch.setattr("shutil.which", lambda name: fake if name == "openvpn" else None)

    profile = store.add_profile(add_openvpn("v", inline="client\nsecret\n"))
    ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)

    assert ctl.connect(profile).state == "error"
    assert not (tmp_path / f"{profile.id}.ovpn").exists()


def test_malformed_vpn_settings_map_error(tmp_path):
    store = _store(tmp_path)
    profile = store.add_profile(
        Profile(
            name="broken",
            kind="openvpn",
            vpn={"type": "openvpn", "inline": "client\n", "args": "--verb"},
        )
    )

    status = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path).connect(profile)

    assert status.state == "error"
    assert "args must be a list" in status.error


def test_vpn_missing_target_maps_error(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/openconnect")
    profile = store.add_profile(
        Profile(name="oc", kind="openconnect", vpn={"type": "openconnect", "server": ""})
    )

    status = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path).connect(profile)

    assert status.state == "error"
    assert "needs a server" in status.error


def test_vpn_missing_client_maps_error(tmp_path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr("shutil.which", lambda name: None)
    profile = store.add_profile(add_openconnect("oc", "vpn.example.com"))

    ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
    status = ctl.connect(profile)
    assert status.state == "error"
    assert "openconnect" in status.error
    assert "install" in status.error
