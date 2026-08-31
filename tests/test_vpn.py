import pytest

from v2portal.models import Profile
from v2portal.outbounds.vpn import (
    add_openconnect,
    add_openvpn,
    detect_clients,
    is_vpn,
    validate_vpn_profile,
)


def test_add_openvpn_path_and_inline():
    p = add_openvpn("ovpn", config_path="/tmp/x.ovpn", args=["--verb", "3"])
    assert p.kind == "openvpn"
    assert p.vpn["config_path"] == "/tmp/x.ovpn"
    assert p.vpn["args"] == ["--verb", "3"]

    p2 = add_openvpn("ovpn2", inline="client\nremote 1.2.3.4")
    assert p2.vpn["inline"].startswith("client")


def test_add_openvpn_requires_config():
    with pytest.raises(ValueError):
        add_openvpn("ovpn")


def test_add_openconnect():
    p = add_openconnect("oc", "vpn.example.com", args=["--user", "bob"], auth_hint="token")
    assert p.kind == "openconnect"
    assert p.vpn["server"] == "vpn.example.com"
    assert p.vpn["auth_hint"] == "token"


def test_add_openconnect_requires_server():
    with pytest.raises(ValueError):
        add_openconnect("oc", " ")


def test_is_vpn():
    assert is_vpn(add_openvpn("x", config_path="/tmp/x.ovpn"))
    assert not is_vpn(Profile(kind="socks"))


def test_detect_clients_keys():
    d = detect_clients()
    assert set(d) == {"openvpn", "openconnect"}
    assert all(v is None or isinstance(v, str) for v in d.values())


def test_validate_persisted_vpn_profile():
    valid = add_openvpn("v", inline="client\n")
    assert validate_vpn_profile(valid)["type"] == "openvpn"

    with pytest.raises(ValueError, match="missing vpn settings"):
        validate_vpn_profile(Profile(kind="openvpn", vpn=None))

    malformed_args = Profile(
        kind="openvpn",
        vpn={"type": "openvpn", "inline": "client\n", "args": "--verb"},
    )
    with pytest.raises(ValueError, match="args must be a list"):
        validate_vpn_profile(malformed_args)

    mismatched_type = Profile(
        kind="openvpn",
        vpn={"type": "openconnect", "server": "vpn.example.com", "args": []},
    )
    with pytest.raises(ValueError, match="invalid VPN type"):
        validate_vpn_profile(mismatched_type)

    malformed_server = Profile(
        kind="openconnect",
        vpn={"type": "openconnect", "server": 443, "args": []},
    )
    with pytest.raises(ValueError, match="needs a server"):
        validate_vpn_profile(malformed_server)
