"""Tests for universal reference resolution (Phase 01)."""

from __future__ import annotations

import pytest

from v2raycli.models import Group, Profile, RoutingConfig, RoutingRule, Subscription
from v2raycli.outbounds.groups import (
    enrich_target_with_routing,
    resolve_refs,
    resolve_target,
    subscription_target,
)
from v2raycli.storage import ConfigStore


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