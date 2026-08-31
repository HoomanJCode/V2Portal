"""Tests for universal reference resolution (Phase 01)."""

from __future__ import annotations

import pytest

from v2portal.models import Group, Profile, RoutingConfig, RoutingRule, Server, Subscription
from v2portal.outbounds.groups import (
    enrich_target_with_routing,
    resolve_refs,
    resolve_target,
    subscription_target,
)
from v2portal.storage import ConfigStore


def _store(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    p1 = store.add_profile(Profile(name="p1", kind="vmess"))
    p2 = store.add_profile(Profile(name="p2", kind="trojan"))
    return store, p1, p2


def test_resolve_refs_mixed_dedup(tmp_path):
    store, p1, p2 = _store(tmp_path)
    sub = store.add_subscription(Subscription(name="sub", profile_ids=[p2.id]))
    g = store.add_group(Group(name="g", type="single", profile_ids=[p1.id]))

    out = resolve_refs(store, [p1.id, sub.id, g.id, p1.id])
    assert [p.id for p in out] == [p1.id, p2.id]  # deduped, ordered


def test_resolve_refs_unknown(tmp_path):
    store, p1, _ = _store(tmp_path)
    with pytest.raises(ValueError, match="unknown id: 999"):
        resolve_refs(store, [p1.id, "999"])


def test_resolve_refs_subscription_missing_profile(tmp_path):
    store, _, _ = _store(tmp_path)
    sub = store.add_subscription(Subscription(name="sub", profile_ids=["nope"]))
    with pytest.raises(ValueError, match="references unknown profile nope"):
        resolve_refs(store, [sub.id])


def test_resolve_refs_nested_group_dedup(tmp_path):
    store, p1, p2 = _store(tmp_path)
    leaf = store.add_group(Group(name="leaf", type="single", profile_ids=[p2.id]))
    parent = store.add_group(Group(
        name="parent", type="balancer", strategy="latency",
        profile_ids=[p1.id], group_ids=[leaf.id],
    ))
    out = resolve_refs(store, [parent.id, p2.id])
    assert [p.id for p in out] == [p1.id, p2.id]


def test_resolve_refs_cycle_detection(tmp_path):
    store, p1, _ = _store(tmp_path)
    a = store.add_group(Group(name="a", type="single", profile_ids=[p1.id]))
    b = store.add_group(Group(name="b", type="single"))
    a.group_ids.append(b.id)
    b.group_ids.append(a.id)
    with pytest.raises(ValueError, match="circular group reference"):
        resolve_refs(store, [a.id])


def test_subscription_target_balancer(tmp_path):
    store, p1, p2 = _store(tmp_path)
    sub = store.add_subscription(Subscription(name="sub", profile_ids=[p1.id, p2.id]))
    t = subscription_target(store, sub.id, strategy="random")
    assert t.type == "balancer"
    assert t.strategy == "random"
    assert t.profile_ids == [p1.id, p2.id]
    assert t.name == "sub"


def test_subscription_target_no_profiles(tmp_path):
    store, _, _ = _store(tmp_path)
    sub = store.add_subscription(Subscription(name="empty"))
    with pytest.raises(ValueError, match="has no profiles"):
        subscription_target(store, sub.id)


def test_resolve_target_accepts_subscription_model(tmp_path):
    store, p1, p2 = _store(tmp_path)
    sub = store.add_subscription(Subscription(name="sub", profile_ids=[p1.id, p2.id]))
    t = resolve_target(store, sub, default_engine="sing-box")
    assert t.type == "balancer"
    assert t.profile_ids == [p1.id, p2.id]


def test_resolve_target_nested_group(tmp_path):
    store, p1, p2 = _store(tmp_path)
    leaf = store.add_group(Group(name="leaf", type="single", profile_ids=[p2.id]))
    parent = store.add_group(Group(
        name="parent", type="balancer", strategy="latency",
        profile_ids=[p1.id], group_ids=[leaf.id],
    ))
    t = resolve_target(store, parent, default_engine="sing-box")
    assert t.type == "balancer"
    assert set(t.profile_ids) == {p1.id, p2.id}


def test_enrich_target_with_routing_subscription_target(tmp_path):
    store, p1, p2 = _store(tmp_path)
    sub = store.add_subscription(Subscription(name="sub", profile_ids=[p2.id]))
    base = resolve_target(store, store.get_profile(p1.id), default_engine="sing-box")
    routing = RoutingConfig(mode="split", rules=[RoutingRule(action="proxy", target_id=sub.id)])
    t = enrich_target_with_routing(base, routing, store)
    assert t.extra_profiles
    assert {p.id for p in t.extra_profiles} == {p2.id}


# -- server refs -----------------------------------------------------------


def _store_with_server(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    sv = store.add_server(Server(name="local", port=1081, protocol="mixed"))
    http_sv = store.add_server(Server(name="local-http", port=8080, protocol="http"))
    return store, sv, http_sv


def test_resolve_refs_server_member_socks_profile(tmp_path):
    store, sv, _ = _store_with_server(tmp_path)
    out = resolve_refs(store, [sv.id])
    assert len(out) == 1
    p = out[0]
    assert p.id == sv.id
    assert p.kind == "socks"  # mixed protocol → socks profile
    assert p.outbound["settings"]["servers"][0]["address"] == sv.listen
    assert p.outbound["settings"]["servers"][0]["port"] == sv.port


def test_resolve_refs_http_server_member(tmp_path):
    store, _, http_sv = _store_with_server(tmp_path)
    out = resolve_refs(store, [http_sv.id])
    assert out[0].kind == "http"


def test_resolve_refs_server_via_nested_group_dedup(tmp_path):
    store, sv, _ = _store_with_server(tmp_path)
    leaf = store.add_group(Group(name="leaf", type="single", server_ids=[sv.id]))
    parent = store.add_group(Group(name="parent", type="single", group_ids=[leaf.id]))
    out = resolve_refs(store, [parent.id, sv.id])
    assert [p.id for p in out] == [sv.id]  # deduped


def test_resolve_refs_server_chain_loop_rejected(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    sv1 = store.add_server(Server(name="s1", port=1081))
    sv2 = store.add_server(Server(name="s2", port=1082))
    sv1.outbound_type = "server"
    sv1.outbound_id = sv2.id
    sv2.outbound_type = "server"
    sv2.outbound_id = sv1.id
    with pytest.raises(ValueError, match="circular server reference"):
        resolve_refs(store, [sv1.id])


def test_resolve_target_group_with_server_member(tmp_path):
    store, sv, _ = _store_with_server(tmp_path)
    g = store.add_group(Group(name="g", type="single", server_ids=[sv.id]))
    t = resolve_target(store, g, default_engine="sing-box")
    assert t.type == "single"
    assert t.profile_ids == [sv.id]
    assert t.profiles[0].kind == "socks"


def test_resolve_target_accepts_server_model(tmp_path):
    store, sv, _ = _store_with_server(tmp_path)
    t = resolve_target(store, sv, default_engine="sing-box")
    assert t.type == "single"
    assert t.profile_ids == [sv.id]
    assert t.profiles[0].kind == "socks"
    assert t.profiles[0].outbound["settings"]["servers"][0]["port"] == sv.port