import base64
import json

import pytest

from v2portal.models import Profile
from v2portal.subs.share import ShareLinkError, decode_link, encode_link


def _b64(data) -> str:
    if isinstance(data, dict):
        data = json.dumps(data).encode()
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _ss_link(method, password, host, port, name="ss-node"):
    userinfo = _b64(f"{method}:{password}".encode())
    return f"ss://{userinfo}@{host}:{port}#{name}"


def test_vmess():
    link = "vmess://" + _b64(
        {
            "v": "2",
            "ps": "vmess-node",
            "add": "1.2.3.4",
            "port": "443",
            "id": "00000000-0000-0000-0000-000000000001",
            "aid": "0",
            "net": "ws",
            "type": "none",
            "host": "example.com",
            "path": "/ws",
            "tls": "tls",
            "sni": "example.com",
        }
    )
    p = decode_link(link)
    assert p.kind == "vmess"
    assert p.name == "vmess-node"
    vnext = p.outbound["settings"]["vnext"][0]
    assert vnext["address"] == "1.2.3.4"
    assert vnext["port"] == 443
    assert p.outbound["streamSettings"]["wsSettings"]["path"] == "/ws"
    assert p.outbound["streamSettings"]["security"] == "tls"


def test_vless():
    link = (
        "vless://00000000-0000-0000-0000-000000000002@5.6.7.8:443"
        "?security=tls&sni=vl.example.com&type=ws&path=%2Fvless#vless-node"
    )
    p = decode_link(link)
    assert p.kind == "vless"
    assert p.name == "vless-node"
    vnext = p.outbound["settings"]["vnext"][0]
    assert vnext["address"] == "5.6.7.8"
    assert p.outbound["streamSettings"]["security"] == "tls"
    assert p.outbound["streamSettings"]["wsSettings"]["path"] == "/vless"


def test_trojan():
    link = "trojan://password123@9.10.11.12:443?security=tls&sni=tj.example.com#trojan-node"
    p = decode_link(link)
    assert p.kind == "trojan"
    srv = p.outbound["settings"]["servers"][0]
    assert srv["password"] == "password123"
    assert p.outbound["streamSettings"]["security"] == "tls"


def test_ss_legacy_and_sip002():
    p = decode_link(_ss_link("aes-256-gcm", "pass123", "13.14.15.16", "8388"))
    srv = p.outbound["settings"]["servers"][0]
    assert (srv["method"], srv["password"]) == ("aes-256-gcm", "pass123")

    sip = "ss://chacha20-ietf-poly1305:pw%40ss@1.1.1.1:443#sip-node"
    p2 = decode_link(sip)
    srv2 = p2.outbound["settings"]["servers"][0]
    assert srv2["method"] == "chacha20-ietf-poly1305"
    assert srv2["password"] == "pw@ss"


def test_ssr():
    main = (
        "host.com:8388:auth_aes128_md5:aes-128-cfb:tls1.2_ticket_auth:"
        + _b64(b"pwd")
    )
    link = "ssr://" + _b64(main.encode())
    p = decode_link(link)
    srv = p.outbound["settings"]["servers"][0]
    assert srv["address"] == "host.com"
    assert srv["method"] == "aes-128-cfb"
    assert srv["password"] == "pwd"
    assert srv["protocol"] == "auth_aes128_md5"


def test_socks_and_http():
    p = decode_link("socks://user:pass@17.18.19.20:1080#socks-node")
    assert p.kind == "socks"
    srv = p.outbound["settings"]["servers"][0]
    assert srv["address"] == "17.18.19.20"
    assert srv["users"][0]["user"] == "user"

    p2 = decode_link("http://user:pass@21.22.23.24:8080#http-node")
    assert p2.kind == "http"


def test_hysteria2_tuic_wireguard():
    p = decode_link("hysteria2://h2pass@31.32.33.34:443?insecure=1&sni=h2.example.com#h2-node")
    assert p.kind == "hysteria2"
    assert p.engine == "sing-box"
    assert p.outbound["password"] == "h2pass"
    assert p.outbound["tls"]["insecure"] is True

    t = decode_link(
        "tuic://00000000-0000-0000-0000-000000000003:tuicpass@35.36.37.38:443"
        "?congestion_control=bbr&alpn=h3&sni=tuic.example.com#tuic-node"
    )
    assert t.kind == "tuic"
    assert t.engine == "sing-box"
    assert t.outbound["uuid"].startswith("00000000")
    assert t.outbound["congestion_control"] == "bbr"

    wg = _b64(
        {
            "private_key": "k",
            "address": ["10.0.0.2/32"],
            "peers": [{"public_key": "pk", "endpoint": "1.2.3.4:51820", "allowed_ips": ["0.0.0.0/0"]}],
        }
    )
    w = decode_link("wireguard://" + wg)
    assert w.kind == "wireguard"
    assert w.outbound["settings"]["secretKey"] == "k"


def test_wireguard_binary_payload_reports_clean_error():
    # base64 of raw binary that is not UTF-8 text (corrupt subscription link)
    payload = base64.b64encode(b"7P\xa1'>\xa6\xd0\xc0A\x11\x9f\xe0\xcd\xbf\x8f8<V").decode()
    with pytest.raises(ShareLinkError, match="not valid base64-encoded JSON"):
        decode_link("wireguard://" + payload)


def test_unknown_scheme_raises():
    with pytest.raises(ShareLinkError):
        decode_link("foo://bar")


@pytest.mark.parametrize(
    "link",
    [
        "vmess://not-base64",
        "vless://uuid@host:not-port",
        "trojan://pw@host:not-port",
        "ss://not-a-link",
        "ssr://not-base64",
        "hysteria2://pw@host:not-port",
        "tuic://uuid:pw@host:not-port",
        "wireguard://not-json",
    ],
)
def test_malformed_links_raise_typed_error(link):
    with pytest.raises(ShareLinkError):
        decode_link(link)


@pytest.mark.parametrize(
    "link",
    [
        "vless://uuid@host:0",
        "trojan://@host:443",
        "ss://method:password@:443",
        "socks://user:pass@:1080",
        "hysteria2://@host:443",
        "tuic://uuid:pw@host:65536",
        "wireguard://eyJwcml2YXRlX2tleSI6ICJrIiwgInBlZXJzIjogW3siZW5kcG9pbnQiOiAiaG9zdDpub3QtcG9ydCJ9XX0",
    ],
)
def test_decoded_links_reject_invalid_endpoints_or_credentials(link):
    with pytest.raises(ShareLinkError):
        decode_link(link)


def test_vmess_rejects_fractional_json_port():
    link = "vmess://" + _b64(
        {
            "add": "host.example",
            "port": 443.5,
            "id": "00000000-0000-0000-0000-000000000001",
        }
    )
    with pytest.raises(ShareLinkError, match="port"):
        decode_link(link)


def test_non_text_link_raises_typed_error():
    with pytest.raises(ShareLinkError, match="must be text"):
        decode_link(None)


def test_encode_malformed_profile_raises_typed_error():
    profile = Profile(kind="vmess", outbound={})

    with pytest.raises(ShareLinkError, match="cannot encode kind vmess"):
        encode_link(profile)


def test_encode_non_profile_raises_typed_error():
    with pytest.raises(ShareLinkError, match="must be a Profile"):
        encode_link(None)


def test_encode_ss_round_trip():
    p = decode_link(_ss_link("aes-256-gcm", "pw", "1.2.3.4", "8388"))
    p2 = decode_link(encode_link(p))
    srv2 = p2.outbound["settings"]["servers"][0]
    assert srv2["address"] == "1.2.3.4"
    assert srv2["password"] == "pw"
