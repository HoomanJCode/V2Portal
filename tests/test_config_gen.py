import pytest

from v2raycli.engines import get_adapter
from v2raycli.models import Group, Profile, RoutingConfig, RoutingRule
from v2raycli.storage import ConfigStore
from v2raycli.outbounds.groups import resolve_target


def _vmess(name="a"):
    return Profile(
        name=name,
        kind="vmess",
        outbound={
            "settings": {
                "vnext": [
                    {
                        "address": "1.2.3.4",
                        "port": 443,
                        "users": [{"id": "u1", "alterId": 0, "security": "auto"}],
                    }
                ]
            },
            "streamSettings": {"network": "tcp"},
        },
    )


def _store(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    return store


def _generate(store, selection, default="sing-box"):
    target = resolve_target(store, selection, default_engine=default)
    adapter = get_adapter(target.engine)
    return adapter.generate(store.config.settings, store.config.routing, target)


def _wireguard(name="wg"):
    return Profile(
        name=name,
        kind="wireguard",
        outbound={
            "settings": {
                "secretKey": "k1",
                "address": ["10.0.0.2/32"],
                "peers": [
                    {
                        "publicKey": "pk1",
                        "endpoint": "1.2.3.4:51820",
                        "allowedIps": ["0.0.0.0/0"],
                        "preSharedKey": "psk1",
                    }
                ],
                "mtu": 1408,
            }
        },
    )


def test_singbox_wireguard_is_endpoint(tmp_path):
    store = _store(tmp_path)
    p = store.add_profile(_wireguard())
    cfg = _generate(store, p, default="sing-box")

    # Not an outbound anymore -- it lives in the top-level endpoints array.
    assert not any(o.get("type") == "wireguard" for o in cfg["outbounds"])
    ep = next(e for e in cfg["endpoints"] if e.get("tag") == p.id)
    assert ep["type"] == "wireguard"
    assert ep["private_key"] == "k1"
    assert ep["address"] == ["10.0.0.2/32"]
    assert ep["mtu"] == 1408
    peer = ep["peers"][0]
    assert peer["address"] == "1.2.3.4"
    assert peer["port"] == 51820
    assert peer["public_key"] == "pk1"
    assert peer["pre_shared_key"] == "psk1"
    assert peer["allowed_ips"] == ["0.0.0.0/0"]
    # route.final may point directly at the endpoint tag
    assert cfg["route"]["final"] == p.id


def test_singbox_rejects_malformed_stream_mappings(tmp_path):
    store = _store(tmp_path)
    malformed_stream = _vmess("bad-stream")
    malformed_stream.outbound["streamSettings"] = "invalid"
    malformed_stream = store.add_profile(malformed_stream)
    with pytest.raises(ValueError, match="streamSettings must be an object"):
        _generate(store, malformed_stream, default="sing-box")

    malformed_tls = _vmess("bad-tls")
    malformed_tls.outbound["streamSettings"] = {"security": "tls", "tlsSettings": []}
    malformed_tls = store.add_profile(malformed_tls)
    with pytest.raises(ValueError, match="tlsSettings must be an object"):
        _generate(store, malformed_tls, default="sing-box")

    malformed_ws = _vmess("bad-ws")
    malformed_ws.outbound["streamSettings"] = {"network": "ws", "wsSettings": []}
    malformed_ws = store.add_profile(malformed_ws)
    with pytest.raises(ValueError, match="wsSettings must be an object"):
        _generate(store, malformed_ws, default="sing-box")


def test_singbox_rejects_malformed_native_outbounds(tmp_path):
    store = _store(tmp_path)
    malformed_hysteria = store.add_profile(
        Profile(name="bad-h2", kind="hysteria2", outbound=[])
    )
    with pytest.raises(ValueError, match="must be an object"):
        _generate(store, malformed_hysteria, default="sing-box")

    missing_tuic_credentials = store.add_profile(
        Profile(
            name="bad-tuic",
            kind="tuic",
            outbound={"server": "1.2.3.4", "server_port": 443, "uuid": "", "password": "pw"},
        )
    )
    with pytest.raises(ValueError, match="tuic UUID"):
        _generate(store, missing_tuic_credentials, default="sing-box")

    invalid_rate = store.add_profile(
        Profile(
            name="bad-rate",
            kind="hysteria2",
            outbound={
                "server": "1.2.3.4",
                "server_port": 443,
                "password": "pw",
                "up_mbps": 0,
            },
        )
    )
    with pytest.raises(ValueError, match="upload rate"):
        _generate(store, invalid_rate, default="sing-box")


def test_singbox_native_outbound_shape_is_preserved(tmp_path):
    store = _store(tmp_path)
    profile = store.add_profile(
        Profile(
            name="h2",
            kind="hysteria2",
            outbound={"server": "1.2.3.4", "server_port": 443, "password": "pw", "up_mbps": "10"},
        )
    )
    cfg = _generate(store, profile, default="sing-box")
    outbound = next(o for o in cfg["outbounds"] if o.get("tag") == profile.id)
    assert outbound["type"] == "hysteria2"
    assert outbound["up_mbps"] == 10


def test_singbox_rejects_malformed_wireguard_endpoint(tmp_path):
    store = _store(tmp_path)
    missing_settings = store.add_profile(Profile(name="bad", kind="wireguard", outbound={}))
    with pytest.raises(ValueError, match="missing settings"):
        _generate(store, missing_settings, default="sing-box")

    malformed_peer = store.add_profile(
        Profile(
            name="bad-peer",
            kind="wireguard",
            outbound={
                "settings": {
                    "secretKey": "key",
                    "address": ["10.0.0.2/32"],
                    "peers": [
                        {
                            "publicKey": "peer",
                            "endpoint": "not-an-endpoint",
                            "allowedIps": ["0.0.0.0/0"],
                        }
                    ],
                }
            },
        )
    )
    with pytest.raises(ValueError, match="endpoint must be host:port"):
        _generate(store, malformed_peer, default="sing-box")

    non_text_peer = store.add_profile(
        Profile(
            name="non-text-peer",
            kind="wireguard",
            outbound={
                "settings": {
                    "secretKey": "key",
                    "address": ["10.0.0.2/32"],
                    "peers": [
                        {
                            "publicKey": "peer",
                            "endpoint": 51820,
                            "allowedIps": ["0.0.0.0/0"],
                        }
                    ],
                }
            },
        )
    )
    with pytest.raises(ValueError, match="endpoint must be host:port"):
        _generate(store, non_text_peer, default="sing-box")

    malformed_cidr = store.add_profile(
        Profile(
            name="bad-cidr",
            kind="wireguard",
            outbound={
                "settings": {
                    "secretKey": "key",
                    "address": ["10.0.0.2/32"],
                    "peers": [
                        {
                            "publicKey": "peer",
                            "endpoint": "1.2.3.4:51820",
                            "allowedIps": ["not-a-cidr"],
                        }
                    ],
                }
            },
        )
    )
    with pytest.raises(ValueError, match="peer allowed IP.*CIDR"):
        _generate(store, malformed_cidr, default="sing-box")

    invalid_mtu = _wireguard("bad-mtu")
    invalid_mtu.outbound["settings"]["mtu"] = 1
    invalid_mtu = store.add_profile(invalid_mtu)
    with pytest.raises(ValueError, match="MTU"):
        _generate(store, invalid_mtu, default="sing-box")


def test_singbox_wireguard_in_chain_and_balancer(tmp_path):
    store = _store(tmp_path)
    a = store.add_profile(_vmess("a"))
    w = store.add_profile(_wireguard("w"))

    # Chain: vmess detours through the wireguard endpoint.
    chain = store.add_group(Group(name="chain", type="chain", profile_ids=[a.id, w.id]))
    cfg = _generate(store, chain, default="sing-box")
    ep = next(e for e in cfg["endpoints"] if e.get("tag") == w.id)
    assert ep["detour"] == a.id
    assert cfg["route"]["final"] == w.id

    # Chain in the other order: wireguard endpoint detours through vmess.
    chain2 = store.add_group(Group(name="chain2", type="chain", profile_ids=[w.id, a.id]))
    cfg2 = _generate(store, chain2, default="sing-box")
    ep2 = next(e for e in cfg2["endpoints"] if e.get("tag") == w.id)
    assert "detour" not in ep2
    a_ob = next(o for o in cfg2["outbounds"] if o.get("tag") == a.id)
    assert a_ob["detour"] == w.id

    # Balancer: the group lists the endpoint tag like any other.
    bal = store.add_group(Group(name="bal", type="balancer", strategy="latency", profile_ids=[a.id, w.id]))
    cfg3 = _generate(store, bal, default="sing-box")
    urltest = next(o for o in cfg3["outbounds"] if o.get("type") == "urltest")
    assert set(urltest["outbounds"]) == {a.id, w.id}


def test_xray_single(tmp_path):
    store = _store(tmp_path)
    p = store.add_profile(_vmess())
    cfg = _generate(store, p, default="xray")

    outbound = next(o for o in cfg["outbounds"] if o.get("tag") == p.id)
    assert outbound["protocol"] == "vmess"
    assert cfg["inbounds"][0]["protocol"] == "socks"
    assert cfg["inbounds"][1]["protocol"] == "http"
    assert cfg["inbounds"][1]["port"] == 1081
    assert cfg["routing"]["rules"][-1]["inboundTag"] == ["mixed-in", "http-in"]
    assert cfg["routing"]["rules"][-1]["outboundTag"] == p.id


def test_xray_balancer_and_chain(tmp_path):
    store = _store(tmp_path)
    a = store.add_profile(_vmess("a"))
    b = store.add_profile(_vmess("b"))

    bal = store.add_group(Group(name="bal", type="balancer", strategy="latency", profile_ids=[a.id, b.id]))
    cfg = _generate(store, bal, default="xray")
    assert cfg["routing"]["balancers"][0]["strategy"]["type"] == "leastPing"
    assert cfg["routing"]["rules"][-1]["outboundTag"] == "balancer"

    chain = store.add_group(Group(name="chain", type="chain", profile_ids=[a.id, b.id]))
    cfg2 = _generate(store, chain, default="xray")
    b_ob = next(o for o in cfg2["outbounds"] if o.get("tag") == b.id)
    assert b_ob["proxySettings"]["tag"] == a.id
    assert cfg2["routing"]["rules"][-1]["outboundTag"] == b.id


def test_singbox_rejects_malformed_server_shape(tmp_path):
    store = _store(tmp_path)
    missing_server = store.add_profile(
        Profile(name="bad", kind="socks", outbound={"settings": {"servers": []}})
    )
    with pytest.raises(ValueError, match="missing a server"):
        _generate(store, missing_server, default="sing-box")

    invalid_port = store.add_profile(
        Profile(
            name="bad-port",
            kind="trojan",
            outbound={"settings": {"servers": [{"address": "1.2.3.4", "port": 0}]}},
        )
    )
    with pytest.raises(ValueError, match="invalid server port"):
        _generate(store, invalid_port, default="sing-box")


def test_singbox_rejects_malformed_vmess_shape(tmp_path):
    store = _store(tmp_path)
    missing_vnext = store.add_profile(Profile(name="bad", kind="vmess", outbound={}))
    with pytest.raises(ValueError, match="settings.vnext"):
        _generate(store, missing_vnext, default="sing-box")

    missing_user = store.add_profile(
        Profile(
            name="no-user",
            kind="vless",
            outbound={
                "settings": {
                    "vnext": [{"address": "1.2.3.4", "port": 443, "users": []}]
                }
            },
        )
    )
    with pytest.raises(ValueError, match="missing a user"):
        _generate(store, missing_user, default="sing-box")


def test_singbox_single_mixed_inbound(tmp_path):
    store = _store(tmp_path)
    p = store.add_profile(_vmess())
    cfg = _generate(store, p, default="sing-box")

    inbound = cfg["inbounds"][0]
    assert inbound["type"] == "mixed"
    assert inbound["listen_port"] == 1080

    outbound = next(o for o in cfg["outbounds"] if o.get("tag") == p.id)
    assert outbound["type"] == "vmess"
    assert outbound["server"] == "1.2.3.4"
    assert cfg["route"]["final"] == p.id


def test_allow_lan_false_binds_both_engines_to_loopback(tmp_path):
    store = _store(tmp_path)
    store.config.settings.allow_lan = False
    profile = store.add_profile(_vmess())

    singbox = _generate(store, profile, default="sing-box")
    assert singbox["inbounds"][0]["listen"] == "127.0.0.1"

    xray = _generate(store, profile, default="xray")
    assert xray["inbounds"][0]["listen"] == "127.0.0.1"
    assert xray["inbounds"][1]["listen"] == "127.0.0.1"


def test_xray_balancer_observatory(tmp_path):
    store = _store(tmp_path)
    a = store.add_profile(_vmess("a"))
    b = store.add_profile(_vmess("b"))
    bal = store.add_group(Group(name="bal", type="balancer", strategy="latency", profile_ids=[a.id, b.id]))
    cfg = _generate(store, bal, default="xray")

    assert cfg["observatory"]["subjectSelector"] == [a.id, b.id]
    assert cfg["observatory"]["probeURL"] == store.config.settings.test_url


def test_singbox_balancer_urltest_and_chain_detour(tmp_path):
    store = _store(tmp_path)
    a = store.add_profile(_vmess("a"))
    b = store.add_profile(_vmess("b"))

    bal = store.add_group(Group(name="bal", type="balancer", strategy="latency", profile_ids=[a.id, b.id]))
    cfg = _generate(store, bal, default="sing-box")
    urltest = next(o for o in cfg["outbounds"] if o.get("type") == "urltest")
    assert set(urltest["outbounds"]) == {a.id, b.id}
    assert cfg["route"]["final"] == "balancer"

    chain = store.add_group(Group(name="chain", type="chain", profile_ids=[a.id, b.id]))
    cfg2 = _generate(store, chain, default="sing-box")
    b_ob = next(o for o in cfg2["outbounds"] if o.get("tag") == b.id)
    assert b_ob["detour"] == a.id
    assert cfg2["route"]["final"] == b.id


def test_singbox_dns_typed_format(tmp_path):
    store = _store(tmp_path)
    p = store.add_profile(_vmess())
    cfg = _generate(store, p, default="sing-box")

    servers = cfg["dns"]["servers"]
    assert servers[0]["type"] == "udp"
    assert servers[0]["tag"] == "dns-1"
    assert servers[0]["server"] == "1.1.1.1"
    assert cfg["route"]["default_domain_resolver"] == "dns-1"


def test_singbox_traffic_api_enabled(tmp_path):
    store = _store(tmp_path)
    p = store.add_profile(_vmess())
    store.config.settings.traffic_api = True
    store.config.settings.traffic_api_port = 1234
    cfg = _generate(store, p, default="sing-box")
    assert cfg["experimental"]["clash_api"]["external_controller"] == "127.0.0.1:1234"


def test_singbox_traffic_api_disabled_by_default(tmp_path):
    store = _store(tmp_path)
    p = store.add_profile(_vmess())
    cfg = _generate(store, p, default="sing-box")
    assert "experimental" not in cfg


def test_singbox_geo_rules_use_rule_sets(tmp_path):
    store = _store(tmp_path)
    p = store.add_profile(_vmess())
    store.config.routing = RoutingConfig(
        mode="split",
        rules=[
            RoutingRule(action="direct", match={"geosite": ["category-ads"]}),
            RoutingRule(action="proxy", match={"geoip": ["cn"]}),
        ],
    )
    cfg = _generate(store, p, default="sing-box")

    tags = {rs["tag"] for rs in cfg["route"]["rule_set"]}
    assert tags == {"geosite-category-ads", "geoip-cn"}

    geosite_rs = next(rs for rs in cfg["route"]["rule_set"] if rs["tag"] == "geosite-category-ads")
    assert geosite_rs["type"] == "remote"
    assert geosite_rs["url"].endswith("geosite-category-ads.srs")
    assert geosite_rs["download_detour"] == "direct"

    rule = cfg["route"]["rules"][0]
    assert rule["rule_set"] == ["geosite-category-ads"]
    assert "geosite" not in rule and "geoip" not in rule


def test_singbox_no_rule_sets_without_geo_rules(tmp_path):
    store = _store(tmp_path)
    p = store.add_profile(_vmess())
    cfg = _generate(store, p, default="sing-box")
    assert "rule_set" not in cfg["route"]


def test_split_routing_rules(tmp_path):
    store = _store(tmp_path)
    p = store.add_profile(_vmess())
    store.config.routing = RoutingConfig(
        mode="split",
        rules=[RoutingRule(action="direct", match={"domains": ["example.com"]})],
    )
    cfg = _generate(store, p, default="sing-box")
    rule = cfg["route"]["rules"][0]
    assert rule["outbound"] == "direct"
    assert rule["domain_suffix"] == ["example.com"]


def test_xray_rejects_malformed_manual_outbound(tmp_path):
    store = _store(tmp_path)
    malformed = store.add_profile(Profile(name="bad", kind="manual", outbound=[]))
    with pytest.raises(ValueError, match="must be an object"):
        _generate(store, malformed, default="xray")

    unsupported = store.add_profile(
        Profile(name="unsupported", kind="manual", outbound={"protocol": "not-a-protocol"})
    )
    with pytest.raises(ValueError, match="does not support manual protocol"):
        _generate(store, unsupported, default="xray")


def test_xray_rejects_malformed_typed_outbound(tmp_path):
    store = _store(tmp_path)
    malformed = store.add_profile(Profile(name="bad", kind="vmess", outbound=[]))
    with pytest.raises(ValueError, match="must be an object"):
        _generate(store, malformed, default="xray")

    missing_settings = store.add_profile(Profile(name="no-settings", kind="vless", outbound={}))
    with pytest.raises(ValueError, match="missing settings"):
        _generate(store, missing_settings, default="xray")

    missing_vnext = store.add_profile(
        Profile(name="no-vnext", kind="vmess", outbound={"settings": {}})
    )
    with pytest.raises(ValueError, match="settings.vnext"):
        _generate(store, missing_vnext, default="xray")

    missing_user = store.add_profile(
        Profile(
            name="no-user",
            kind="vless",
            outbound={
                "settings": {
                    "vnext": [{"address": "1.2.3.4", "port": 443, "users": []}]
                }
            },
        )
    )
    with pytest.raises(ValueError, match="missing a user"):
        _generate(store, missing_user, default="xray")


def test_xray_rejects_malformed_server_shape(tmp_path):
    store = _store(tmp_path)
    for kind in ("socks", "http", "trojan", "ss", "ssr"):
        missing_server = store.add_profile(
            Profile(name=f"missing-{kind}", kind=kind, outbound={"settings": {"servers": []}})
        )
        with pytest.raises(ValueError, match="missing a server"):
            _generate(store, missing_server, default="xray")

    malformed_server = store.add_profile(
        Profile(
            name="malformed-server",
            kind="socks",
            outbound={"settings": {"servers": ["not-an-object"]}},
        )
    )
    with pytest.raises(ValueError, match="missing a server"):
        _generate(store, malformed_server, default="xray")

    missing_address = store.add_profile(
        Profile(
            name="missing-address",
            kind="trojan",
            outbound={"settings": {"servers": [{"port": 443}]}},
        )
    )
    with pytest.raises(ValueError, match="missing a server address"):
        _generate(store, missing_address, default="xray")

    invalid_port = store.add_profile(
        Profile(
            name="invalid-port",
            kind="ss",
            outbound={"settings": {"servers": [{"address": "1.2.3.4", "port": 65536}]}},
        )
    )
    with pytest.raises(ValueError, match="invalid server port"):
        _generate(store, invalid_port, default="xray")

    fractional_port = store.add_profile(
        Profile(
            name="fractional-port",
            kind="http",
            outbound={"settings": {"servers": [{"address": "1.2.3.4", "port": 443.5}]}},
        )
    )
    with pytest.raises(ValueError, match="invalid server port"):
        _generate(store, fractional_port, default="xray")


def test_xray_wireguard_shape_is_preserved(tmp_path):
    store = _store(tmp_path)
    profile = store.add_profile(_wireguard())
    cfg = _generate(store, profile, default="xray")
    outbound = next(o for o in cfg["outbounds"] if o.get("tag") == profile.id)
    assert outbound["protocol"] == "wireguard"
    assert outbound["settings"]["secretKey"] == "k1"
    assert outbound["settings"]["peers"][0]["endpoint"] == "1.2.3.4:51820"


def test_xray_rejects_malformed_wireguard_shape(tmp_path):
    store = _store(tmp_path)
    missing_settings = store.add_profile(Profile(name="missing-settings", kind="wireguard", outbound={}))
    with pytest.raises(ValueError, match="missing settings"):
        _generate(store, missing_settings, default="xray")

    missing_key = store.add_profile(
        Profile(
            name="missing-key",
            kind="wireguard",
            outbound={"settings": {"address": ["10.0.0.2/32"], "peers": []}},
        )
    )
    with pytest.raises(ValueError, match="private key"):
        _generate(store, missing_key, default="xray")

    malformed_address = store.add_profile(
        Profile(
            name="malformed-address",
            kind="wireguard",
            outbound={
                "settings": {
                    "secretKey": "key",
                    "address": ["not-a-cidr"],
                    "peers": [{"publicKey": "peer", "endpoint": "1.2.3.4:51820", "allowedIps": ["0.0.0.0/0"]}],
                }
            },
        )
    )
    with pytest.raises(ValueError, match="address.*CIDR"):
        _generate(store, malformed_address, default="xray")

    malformed_peer = store.add_profile(
        Profile(
            name="malformed-peer",
            kind="wireguard",
            outbound={
                "settings": {
                    "secretKey": "key",
                    "address": ["10.0.0.2/32"],
                    "peers": [{"publicKey": "peer", "endpoint": "not-an-endpoint", "allowedIps": ["0.0.0.0/0"]}],
                }
            },
        )
    )
    with pytest.raises(ValueError, match="endpoint must be host:port"):
        _generate(store, malformed_peer, default="xray")

    malformed_allowed = store.add_profile(
        Profile(
            name="malformed-allowed",
            kind="wireguard",
            outbound={
                "settings": {
                    "secretKey": "key",
                    "address": ["10.0.0.2/32"],
                    "peers": [{"publicKey": "peer", "endpoint": "1.2.3.4:51820", "allowedIps": ["bad-cidr"]}],
                }
            },
        )
    )
    with pytest.raises(ValueError, match="peer allowed IP.*CIDR"):
        _generate(store, malformed_allowed, default="xray")


def test_xray_stream_shape_is_preserved(tmp_path):
    store = _store(tmp_path)
    profile = store.add_profile(_vmess("stream"))
    profile.outbound["streamSettings"] = {
        "network": "ws",
        "wsSettings": {"path": "/proxy", "headers": {"Host": "example.com"}},
        "security": "tls",
        "tlsSettings": {"serverName": "example.com", "alpn": ["h2"]},
    }
    cfg = _generate(store, profile, default="xray")
    outbound = next(o for o in cfg["outbounds"] if o.get("tag") == profile.id)
    assert outbound["streamSettings"]["wsSettings"]["path"] == "/proxy"
    assert outbound["streamSettings"]["tlsSettings"]["serverName"] == "example.com"


def test_xray_rejects_malformed_stream_mappings(tmp_path):
    store = _store(tmp_path)
    malformed_stream = _vmess("bad-stream")
    malformed_stream.outbound["streamSettings"] = []
    malformed_stream = store.add_profile(malformed_stream)
    with pytest.raises(ValueError, match="streamSettings must be an object"):
        _generate(store, malformed_stream, default="xray")

    malformed_tls = _vmess("bad-tls")
    malformed_tls.outbound["streamSettings"] = {"security": "tls", "tlsSettings": []}
    malformed_tls = store.add_profile(malformed_tls)
    with pytest.raises(ValueError, match="tlsSettings must be an object"):
        _generate(store, malformed_tls, default="xray")

    malformed_ws = _vmess("bad-ws")
    malformed_ws.outbound["streamSettings"] = {"network": "ws", "wsSettings": []}
    malformed_ws = store.add_profile(malformed_ws)
    with pytest.raises(ValueError, match="wsSettings must be an object"):
        _generate(store, malformed_ws, default="xray")

    malformed_grpc = _vmess("bad-grpc")
    malformed_grpc.outbound["streamSettings"] = {"network": "grpc", "grpcSettings": {"serviceName": 1}}
    malformed_grpc = store.add_profile(malformed_grpc)
    with pytest.raises(ValueError, match="gRPC serviceName"):
        _generate(store, malformed_grpc, default="xray")

    malformed_http = _vmess("bad-http2")
    malformed_http.outbound["streamSettings"] = {"network": "h2", "httpSettings": {"host": "example.com"}}
    malformed_http = store.add_profile(malformed_http)
    with pytest.raises(ValueError, match="HTTP/2 host"):
        _generate(store, malformed_http, default="xray")


def test_xray_settings_shape_is_preserved(tmp_path):
    store = _store(tmp_path)
    profile = store.add_profile(_vmess("auth"))
    store.config.settings.inbound_auth = {
        "enabled": True,
        "username": "user",
        "password": "pass",
    }
    cfg = _generate(store, profile, default="xray")
    assert cfg["inbounds"][0]["settings"]["accounts"] == [{"user": "user", "pass": "pass"}]
    assert cfg["inbounds"][1]["settings"]["accounts"] == [{"user": "user", "pass": "pass"}]


def test_xray_rejects_malformed_settings(tmp_path):
    store = _store(tmp_path)
    profile = store.add_profile(_vmess("settings"))

    store.config.settings.inbound_auth = []
    with pytest.raises(ValueError, match="inbound_auth must be an object"):
        _generate(store, profile, default="xray")

    store.config.settings.inbound_auth = {"enabled": True, "username": "user"}
    with pytest.raises(ValueError, match="inbound_auth.password"):
        _generate(store, profile, default="xray")

    store.config.settings.inbound_auth = {"enabled": False, "username": "", "password": ""}
    store.config.settings.dns = "1.1.1.1"
    with pytest.raises(ValueError, match="DNS servers must be a list"):
        _generate(store, profile, default="xray")

    store.config.settings.dns = ["1.1.1.1", ""]
    with pytest.raises(ValueError, match="DNS servers must contain"):
        _generate(store, profile, default="xray")

    store.config.settings.dns = ["1.1.1.1"]
    store.config.settings.mixed_port = 0
    with pytest.raises(ValueError, match="mixed_port must be between"):
        _generate(store, profile, default="xray")

    store.config.settings.mixed_port = 1080
    store.config.settings.allow_lan = "yes"
    with pytest.raises(ValueError, match="allow_lan must be boolean"):
        _generate(store, profile, default="xray")


def test_manual_xray_outbound(tmp_path):
    store = _store(tmp_path)
    p = store.add_profile(
        Profile(name="m", kind="manual", outbound={"protocol": "vmess", "settings": {"vnext": []}})
    )
    cfg = _generate(store, p, default="xray")
    outbound = next(o for o in cfg["outbounds"] if o.get("tag") == p.id)
    assert outbound["protocol"] == "vmess"
