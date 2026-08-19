import json

import pytest

from v2raycli.models import Group, Profile, Subscription
from v2raycli.storage import ConfigStore
from v2raycli.outbounds.manual import (
    add_hysteria2,
    add_http_proxy,
    add_manual_config,
    add_socks_proxy,
    add_tuic,
    add_wireguard,
    edit_profile,
    remove_profile,
)


def test_add_manual_config():
    raw = json.dumps({"protocol": "vmess", "tag": "x", "settings": {"vnext": []}})
    p = add_manual_config(raw, "m")
    assert p.kind == "manual"
    assert p.engine == "xray"
    assert "tag" not in p.outbound
    assert p.outbound["protocol"] == "vmess"
    assert p.outbound["settings"]["vnext"] == []


def test_add_manual_config_rejects_invalid():
    with pytest.raises(ValueError):
        add_manual_config("not json", "m")
    with pytest.raises(ValueError):
        add_manual_config(json.dumps({"protocol": "socks", "listen": "0.0.0.0"}), "m")
    with pytest.raises(ValueError):
        add_manual_config(json.dumps({"protocol": "bogus"}), "m")
    with pytest.raises(ValueError, match="engine='xray'"):
        add_manual_config(
            json.dumps({"protocol": "vmess", "settings": {}}), "m", engine="sing-box"
        )


def test_manual_proxy_factories_reject_invalid_endpoints():
    with pytest.raises(ValueError, match="host"):
        add_socks_proxy("s", "", 1080)
    with pytest.raises(ValueError, match="between 1 and 65535"):
        add_http_proxy("h", "proxy.example.com", 0)
    with pytest.raises(ValueError, match="between 1 and 65535"):
        add_hysteria2("h2", "proxy.example.com", 65536, "pw")
    with pytest.raises(ValueError, match="integer"):
        add_tuic("tuic", "proxy.example.com", "bad", "u", "pw")
    with pytest.raises(ValueError, match="integer"):
        add_socks_proxy("s", "proxy.example.com", 1080.5)


def test_manual_singbox_factories_reject_invalid_credentials_and_rates():
    with pytest.raises(ValueError, match="hysteria2 password"):
        add_hysteria2("h2", "proxy.example.com", 443, "")
    with pytest.raises(ValueError, match="upload rate"):
        add_hysteria2("h2", "proxy.example.com", 443, "pw", up_mbps=0)
    with pytest.raises(ValueError, match="download rate"):
        add_hysteria2("h2", "proxy.example.com", 443, "pw", down_mbps=1.5)
    with pytest.raises(ValueError, match="UUID"):
        add_tuic("tuic", "proxy.example.com", 443, "", "pw")
    with pytest.raises(ValueError, match="tuic password"):
        add_tuic("tuic", "proxy.example.com", 443, "uuid", "")


def test_add_socks_http():
    p = add_socks_proxy("s", "1.2.3.4", 1080, "u", "p")
    srv = p.outbound["settings"]["servers"][0]
    assert p.kind == "socks"
    assert srv["address"] == "1.2.3.4"
    assert srv["users"] == [{"user": "u", "pass": "p"}]

    h = add_http_proxy("h", "1.2.3.4", 8080)
    assert h.kind == "http"
    assert "users" not in h.outbound["settings"]["servers"][0]


def test_wireguard_factory_rejects_incomplete_profile():
    with pytest.raises(ValueError, match="private key"):
        add_wireguard("wg", "", ["10.0.0.2/32"], [{"publicKey": "pk", "endpoint": "1.2.3.4:51820", "allowedIps": ["0.0.0.0/0"]}])
    with pytest.raises(ValueError, match="endpoint"):
        add_wireguard("wg", "k", ["10.0.0.2/32"], [{"publicKey": "pk", "allowedIps": ["0.0.0.0/0"]}])
    with pytest.raises(ValueError, match="host:port"):
        add_wireguard("wg", "k", ["10.0.0.2/32"], [{"publicKey": "pk", "endpoint": "not-an-endpoint", "allowedIps": ["0.0.0.0/0"]}])
    with pytest.raises(ValueError, match="allowed IPs"):
        add_wireguard("wg", "k", ["10.0.0.2/32"], [{"publicKey": "pk", "endpoint": "1.2.3.4:51820", "allowedIps": []}])


def test_add_wireguard_hysteria2_tuic():
    w = add_wireguard("wg", "k", ["10.0.0.2/32"], [{"publicKey": "pk", "endpoint": "1.2.3.4:51820", "allowedIps": ["0.0.0.0/0"]}])
    assert w.kind == "wireguard"
    assert w.outbound["settings"]["secretKey"] == "k"

    h = add_hysteria2(
        "h2", "1.2.3.4", 443, "pw", obfs="salamander", obfs_password="op", up_mbps=10, down_mbps=20
    )
    assert h.kind == "hysteria2"
    assert h.engine == "sing-box"
    assert h.outbound["obfs"]["type"] == "salamander"
    assert h.outbound["up_mbps"] == 10
    assert h.outbound["down_mbps"] == 20

    t = add_tuic("tuic", "1.2.3.4", 443, "u", "pw", alpn="h3")
    assert t.kind == "tuic"
    assert t.outbound["tls"]["alpn"] == ["h3"]


def test_edit_and_remove_profile(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    p = store.add_profile(Profile(name="a"))
    edit_profile(store, p.id, name="b")
    assert store.get_profile(p.id).name == "b"
    assert remove_profile(store, p.id) is True
    assert store.get_profile(p.id) is None


def test_remove_profile_prunes_refs(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    p = store.add_profile(Profile(name="p"))
    sub = store.add_subscription(Subscription(name="s", profile_ids=[p.id]))
    group = store.add_group(Group(name="g", type="balancer", profile_ids=[p.id]))

    assert remove_profile(store, p.id) is True
    assert p.id not in sub.profile_ids
    assert p.id not in group.profile_ids
