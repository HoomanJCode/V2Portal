import pytest

from v2raycli.models import Profile
from v2raycli.storage import ConfigStore
from v2raycli.outbounds.groups import (
    create_balancer_group,
    create_chain_group,
    create_single_group,
    resolve_target,
)
from v2raycli.outbounds.vpn import add_openvpn


def _store(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    a = store.add_profile(Profile(name="a", kind="vmess"))
    b = store.add_profile(Profile(name="b", kind="trojan"))
    return store, a, b


def test_balancer_requires_two_profiles(tmp_path):
    store, a, b = _store(tmp_path)
    g = create_balancer_group("bal", "latency", [a.id, b.id], store)
    assert g.type == "balancer"
    assert g.strategy == "latency"
    with pytest.raises(ValueError):
        create_balancer_group("bal", "latency", [a.id], store)


def test_least_load_resolves_to_xray(tmp_path):
    store, a, b = _store(tmp_path)
    g = create_balancer_group("bal", "leastLoad", [a.id, b.id], store, engine="auto")
    assert resolve_target(store, g, default_engine="sing-box").engine == "xray"


def test_chain_group_and_resolve(tmp_path):
    store, a, b = _store(tmp_path)
    g = create_chain_group("chain", [a.id, b.id], store)
    t = resolve_target(store, g, default_engine="sing-box")
    assert t.type == "chain"
    assert t.profile_ids == [a.id, b.id]


def test_single_group(tmp_path):
    store, a, _ = _store(tmp_path)
    g = create_single_group("one", a.id)
    t = resolve_target(store, g, default_engine="sing-box")
    assert t.type == "single"
    assert t.profile_ids == [a.id]


def test_vpn_cannot_join_balancer(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    a = store.add_profile(Profile(name="a", kind="vmess"))
    v = store.add_profile(add_openvpn("v", config_path="/tmp/x.ovpn"))
    with pytest.raises(ValueError):
        create_balancer_group("bal", "latency", [a.id, v.id], store)


def test_resolve_single_profile(tmp_path):
    store, a, _ = _store(tmp_path)
    t = resolve_target(store, a, default_engine="sing-box")
    assert t.type == "single"
    assert t.engine == "sing-box"
