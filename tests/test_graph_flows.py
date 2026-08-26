"""End-to-end graph lifecycle tests (Phase 06).

Exercises the full universal-reference model on one store: subscription
refresh flows through servers/groups, nesting, dedup, and removals.
"""

from __future__ import annotations

import pytest

from v2raycli.models import Group, Profile, Server, Subscription
from v2raycli.outbounds.groups import resolve_refs, resolve_target
from v2raycli.storage import ConfigStore

SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}


def _store(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    return store


def _make_sub(store, name: str, count: int):
    """Create a subscription with *count* profiles; returns (sub, [profile ids])."""
    sub = store.add_subscription(Subscription(name=name))
    ids = []
    for i in range(count):
        p = store.add_profile(Profile(
            name=f"{name}-node{i}",
            kind="socks",
            outbound=SOCKS,
            subscription_id=sub.id,
        ))
        ids.append(p.id)
    sub.profile_ids = list(ids)  # copy: store mutations must not alias it
    return sub, ids


class _FakeServer:
    def __init__(self, outbound_id: str, outbound_type: str = "subscription"):
        self.id = "srv"
        self.outbound_id = outbound_id
        self.outbound_type = outbound_type


def _server_resolve(store, server):
    from v2raycli.servers import ServerManager
    return ServerManager(store).resolve_outbound_target(server)


def test_subscription_refresh_flows_into_server_target(tmp_path):
    store = _store(tmp_path)
    sub, ids = _make_sub(store, "provider", 2)
    server = _FakeServer(sub.id, "subscription")
    store.save()

    target = _server_resolve(store, server)
    assert target.type == "balancer"
    assert set(target.profile_ids) == set(ids)

    # Subscription refresh: drop node 0, add node 2.
    dropped = ids[0]
    store.remove_profile(dropped)
    new_node = store.add_profile(Profile(
        name="provider-node2", kind="socks", outbound=SOCKS, subscription_id=sub.id,
    ))
    sub.profile_ids = [ids[1], new_node.id]
    store.save()

    target = _server_resolve(store, server)
    assert target.profile_ids == [ids[1], new_node.id]
    # Old node no longer in the target.
    assert dropped not in target.profile_ids


def test_refresh_keeps_group_profiles_deduped(tmp_path):
    store = _store(tmp_path)
    sub, ids = _make_sub(store, "provider", 2)
    g = store.add_group(Group(name="g", type="balancer", strategy="latency",
                              subscription_ids=[sub.id]))
    store.save()

    assert {p.id for p in resolve_refs(store, [g.id])} == set(ids)

    # Refresh: one node re-added under the same id (dedup at resolve).
    store.remove_profile(ids[0])
    sub.profile_ids = [ids[1]]
    store.save()

    profiles = resolve_refs(store, [g.id])
    assert [p.id for p in profiles] == [ids[1]]


def test_nested_group_dedup_and_cycle(tmp_path):
    store = _store(tmp_path)
    p1 = store.add_profile(Profile(name="p1", kind="socks", outbound=SOCKS))
    p2 = store.add_profile(Profile(name="p2", kind="socks", outbound=SOCKS))
    leaf = store.add_group(Group(name="leaf", type="single", profile_ids=[p2.id]))
    parent = store.add_group(Group(
        name="parent", type="balancer", strategy="latency",
        profile_ids=[p1.id], group_ids=[leaf.id],
    ))
    store.save()

    t = resolve_target(store, parent, default_engine="sing-box")
    assert set(t.profile_ids) == {p1.id, p2.id}

    # Cycle is rejected by the resolver.
    leaf.group_ids.append(parent.id)
    with pytest.raises(ValueError, match="circular group reference"):
        resolve_refs(store, [parent.id])


def test_remove_subscription_prunes_group_and_server_errors_clearly(tmp_path):
    store = _store(tmp_path)
    sub, ids = _make_sub(store, "provider", 2)
    group = store.add_group(Group(name="g", subscription_ids=[sub.id]))
    server = _FakeServer(sub.id, "subscription")
    store.save()

    store.remove_subscription(sub.id)
    store.save()

    assert store.get_subscription(sub.id) is None
    assert store.get_profile(ids[0]) is None  # profiles deleted
    assert group.subscription_ids == []
    # Server still references the removed subscription: clear error, not crash.
    from v2raycli.outbounds.groups import resolve_outbound
    with pytest.raises(ValueError, match="unknown subscription id"):
        resolve_outbound(store, "subscription", sub.id)


def test_resolve_ref_entity_by_any_ref(tmp_path):
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="p", kind="socks", outbound=SOCKS))
    sub, _ = _make_sub(store, "s", 1)
    g = store.add_group(Group(name="g", type="single", profile_ids=[p.id]))
    sv = store.add_server(Server(name="local", port=1081))
    store.save()

    from v2raycli.outbounds.groups import resolve_ref_entity

    assert resolve_ref_entity(store, p.id) is p
    assert resolve_ref_entity(store, sub.id) is sub
    assert resolve_ref_entity(store, g.id) is g
    assert resolve_ref_entity(store, sv.id) is sv
    with pytest.raises(ValueError, match="unknown id"):
        resolve_ref_entity(store, "999")