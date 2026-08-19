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


def test_xray_single(tmp_path):
    store = _store(tmp_path)
    p = store.add_profile(_vmess())
    cfg = _generate(store, p, default="xray")

    outbound = next(o for o in cfg["outbounds"] if o.get("tag") == p.id)
    assert outbound["protocol"] == "vmess"
    assert cfg["inbounds"][0]["protocol"] == "socks"
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


def test_manual_xray_outbound(tmp_path):
    store = _store(tmp_path)
    p = store.add_profile(
        Profile(name="m", kind="manual", outbound={"protocol": "vmess", "settings": {"vnext": []}})
    )
    cfg = _generate(store, p, default="xray")
    outbound = next(o for o in cfg["outbounds"] if o.get("tag") == p.id)
    assert outbound["protocol"] == "vmess"
