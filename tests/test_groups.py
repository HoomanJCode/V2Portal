import pytest

from v2raycli.models import Group, Profile, Server, Subscription
from v2raycli.storage import ConfigStore
from v2raycli.outbounds.groups import (
    classify_id,
    classify_ids,
    classify_refs,
    create_balancer_group,
    create_chain_group,
    create_single_group,
    group_tree_lines,
    resolve_ref_entity,
    resolve_refs,
    resolve_target,
    server_profile,
    server_reaches_group,
)
from v2raycli.outbounds.vpn import add_openvpn


def _store(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    a = store.add_profile(Profile(name="a", kind="vmess"))
    b = store.add_profile(Profile(name="b", kind="trojan"))
    return store, a, b


def test_balancer_requires_two_profiles_at_resolve(tmp_path):
    """Balancer creation allows 1 profile, but resolve requires 2+."""
    store, a, b = _store(tmp_path)
    g = create_balancer_group("bal", "latency", [a.id, b.id], store)
    assert g.type == "balancer"
    assert g.strategy == "latency"
    # Creating with 1 profile is allowed now (subscription may add more later).
    g_single = create_balancer_group("bal", "latency", [a.id], store)
    assert g_single.type == "balancer"
    # But resolving a balancer with only 1 profile should fail.
    with pytest.raises(ValueError, match="at least 2"):
        resolve_target(store, g_single, default_engine="sing-box")


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


def test_resolve_single_profile_honors_explicit_engine(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    manual = store.add_profile(
        Profile(
            name="raw",
            kind="manual",
            engine="xray",
            outbound={"protocol": "vmess", "settings": {}},
        )
    )

    target = resolve_target(store, manual, default_engine="sing-box")

    assert target.engine == "xray"


def test_auto_group_honors_explicit_member_engine(tmp_path):
    store, a, b = _store(tmp_path)
    a.engine = "xray"
    group = create_chain_group("chain", [a.id, b.id], store)

    assert resolve_target(store, group, default_engine="sing-box").engine == "xray"


def test_auto_group_rejects_conflicting_member_engines(tmp_path):
    store, a, b = _store(tmp_path)
    a.engine = "xray"
    b.engine = "sing-box"

    with pytest.raises(ValueError, match="different engines"):
        create_chain_group("chain", [a.id, b.id], store)


def test_explicit_group_engine_rejects_unsupported_member(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    manual = store.add_profile(
        Profile(
            name="raw",
            kind="manual",
            engine="xray",
            outbound={"protocol": "vmess", "settings": {}},
        )
    )

    with pytest.raises(ValueError, match="sing-box.*manual"):
        create_chain_group("chain", [manual.id, manual.id], store, engine="sing-box")


def test_persisted_group_engine_rejects_unsupported_member(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    manual = store.add_profile(
        Profile(
            name="raw",
            kind="manual",
            engine="xray",
            outbound={"protocol": "vmess", "settings": {}},
        )
    )
    manual2 = store.add_profile(
        Profile(
            name="raw2",
            kind="manual",
            engine="xray",
            outbound={"protocol": "vmess", "settings": {}},
        )
    )
    group = Group(
        name="broken",
        type="chain",
        profile_ids=[manual.id, manual2.id],
        engine="sing-box",
    )

    with pytest.raises(ValueError, match="sing-box.*manual"):
        resolve_target(store, group)


def test_add_member(tmp_path):
    store, a, b = _store(tmp_path)
    g = create_single_group("single", a.id)
    store.add_group(g)
    from v2raycli.outbounds.groups import add_member

    add_member(g, b.id)
    assert g.profile_ids == [a.id, b.id]


def test_remove_member(tmp_path):
    store, a, b = _store(tmp_path)
    g = create_single_group("single", a.id)
    g.profile_ids.append(b.id)
    from v2raycli.outbounds.groups import remove_member

    remove_member(g, b.id)
    assert g.profile_ids == [a.id]


def test_subscription_membership(tmp_path):
    store, a, b = _store(tmp_path)
    from v2raycli.models import Subscription

    sub = store.add_subscription(Subscription(name="sub1", profile_ids=[b.id]))
    g = create_balancer_group("bal", "latency", [a.id], store, subscription_ids=[sub.id])
    assert sub.id in g.subscription_ids
    t = resolve_target(store, g, default_engine="sing-box")
    assert b.id in t.profile_ids
    assert a.id in t.profile_ids


def test_persisted_group_shape_is_validated(tmp_path):
    store, a, b = _store(tmp_path)

    with pytest.raises(ValueError, match="resolves to no profiles"):
        resolve_target(store, Group(name="empty", type="single", profile_ids=[]))

    with pytest.raises(ValueError, match="non-empty strings"):
        resolve_target(store, Group(name="bad-ids", type="single", profile_ids=[None]))

    with pytest.raises(ValueError, match="exactly 1 profile"):
        resolve_target(store, Group(name="too-many", type="single", profile_ids=[a.id, b.id]))

    with pytest.raises(ValueError, match="chain requires at least 2"):
        resolve_target(store, Group(name="short-chain", type="chain", profile_ids=[a.id]))

    with pytest.raises(ValueError, match="balancer requires at least 2"):
        resolve_target(
            store,
            Group(name="short-balancer", type="balancer", strategy="latency", profile_ids=[a.id]),
        )

    # Creating a group with 1 profile is allowed (subscription may expand later).
    g_ok = create_balancer_group("ok", "latency", [a.id], store)
    assert g_ok.type == "balancer"

    with pytest.raises(ValueError, match="invalid strategy"):
        resolve_target(
            store,
            Group(name="bad-strategy", type="balancer", strategy="weighted", profile_ids=[a.id, b.id]),
        )

    with pytest.raises(ValueError, match="unsupported group type"):
        resolve_target(store, Group(name="bad-type", type="selector", profile_ids=[a.id]))


# -- ID auto-detection -----------------------------------------------------


def test_classify_id_detects_profile_subscription_and_unknown(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    p = store.add_profile(Profile(name="p", kind="vmess"))
    s = store.add_subscription(Subscription(name="s"))
    assert classify_id(store, p.id) == "profile"
    assert classify_id(store, s.id) == "subscription"
    assert classify_id(store, "999") is None


def test_classify_ids_splits_mixed_ids_and_rejects_unknown(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    p = store.add_profile(Profile(name="p", kind="vmess"))
    s = store.add_subscription(Subscription(name="s"))
    profile_ids, sub_ids = classify_ids(store, [s.id, p.id])
    assert profile_ids == [p.id]
    assert sub_ids == [s.id]
    with pytest.raises(ValueError, match="unknown id: 999"):
        classify_ids(store, [p.id, "999"])


def test_balancer_accepts_subscription_id_positionally(tmp_path):
    """A subscription ID can be passed where profile IDs are expected."""
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    a = store.add_profile(Profile(name="a", kind="vmess"))
    b = store.add_profile(Profile(name="b", kind="trojan"))
    sub = store.add_subscription(Subscription(name="sub", profile_ids=[b.id]))
    profile_ids, sub_ids = classify_ids(store, [a.id, sub.id])
    g = create_balancer_group("pool", "latency", profile_ids, store, subscription_ids=sub_ids)
    assert g.profile_ids == [a.id]
    assert g.subscription_ids == [sub.id]


# -- server members --------------------------------------------------------


def _store_with_server(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    a = store.add_profile(Profile(name="a", kind="vmess"))
    b = store.add_profile(Profile(name="b", kind="trojan"))
    sv = store.add_server(Server(name="local", port=1081, protocol="mixed"))
    http_sv = store.add_server(Server(name="local-http", port=8080, protocol="http"))
    return store, a, b, sv, http_sv


def test_classify_id_detects_server(tmp_path):
    store, _, _, sv, _ = _store_with_server(tmp_path)
    assert classify_id(store, sv.id) == "server"
    assert classify_id(store, "999") is None


def test_resolve_ref_entity_detects_kind(tmp_path):
    store, a, _, sv, _ = _store_with_server(tmp_path)
    sub = store.add_subscription(Subscription(name="sub"))
    g = store.add_group(Group(name="g"))
    assert resolve_ref_entity(store, a.id) is a
    assert resolve_ref_entity(store, sub.id) is sub
    assert resolve_ref_entity(store, g.id) is g
    assert resolve_ref_entity(store, sv.id) is sv
    with pytest.raises(ValueError, match="unknown id: 999"):
        resolve_ref_entity(store, "999")


def test_classify_refs_splits_four_ways(tmp_path):
    store, a, _, sv, _ = _store_with_server(tmp_path)
    sub = store.add_subscription(Subscription(name="sub"))
    g = store.add_group(Group(name="g"))
    profile_ids, sub_ids, group_ids, server_ids = classify_refs(
        store, [a.id, sub.id, g.id, sv.id]
    )
    assert profile_ids == [a.id]
    assert sub_ids == [sub.id]
    assert group_ids == [g.id]
    assert server_ids == [sv.id]
    with pytest.raises(ValueError, match="unknown id: 999"):
        classify_refs(store, [a.id, "999"])


def test_server_profile_kind_and_endpoint(tmp_path):
    store, _, _, sv, http_sv = _store_with_server(tmp_path)
    p = server_profile(store, sv.id)
    assert p.id == sv.id
    assert p.kind == "socks"  # mixed → socks
    assert p.outbound["settings"]["servers"][0]["address"] == sv.listen
    assert p.outbound["settings"]["servers"][0]["port"] == sv.port
    assert server_profile(store, http_sv.id).kind == "http"
    with pytest.raises(ValueError, match="unknown server id"):
        server_profile(store, "999")


def test_balancer_with_server_member(tmp_path):
    store, a, _, sv, _ = _store_with_server(tmp_path)
    g = create_balancer_group(
        "bal", "latency", [a.id], store, server_ids=[sv.id]
    )
    assert g.server_ids == [sv.id]
    t = resolve_target(store, g, default_engine="sing-box")
    assert t.type == "balancer"
    assert t.profile_ids == [a.id, sv.id]
    server_node = next(p for p in t.profiles if p.id == sv.id)
    assert server_node.kind == "socks"
    assert server_node.outbound["settings"]["servers"][0]["port"] == 1081


def test_chain_with_server_member(tmp_path):
    store, a, _, sv, _ = _store_with_server(tmp_path)
    g = create_chain_group("chain", [a.id], store, server_ids=[sv.id])
    t = resolve_target(store, g, default_engine="sing-box")
    assert t.type == "chain"
    assert t.profile_ids == [a.id, sv.id]


def test_single_group_with_server_ref(tmp_path):
    store, _, _, sv, _ = _store_with_server(tmp_path)
    g = create_single_group("one", sv.id, store)
    assert g.server_ids == [sv.id]
    t = resolve_target(store, g, default_engine="sing-box")
    assert t.type == "single"
    assert t.profile_ids == [sv.id]


def test_single_group_legacy_profile_only_without_store(tmp_path):
    g = create_single_group("one", "007")
    assert g.profile_ids == ["007"]


def test_resolve_refs_expands_server_member(tmp_path):
    store, a, _, sv, _ = _store_with_server(tmp_path)
    g = store.add_group(Group(name="g", profile_ids=[a.id], server_ids=[sv.id]))
    profiles = resolve_refs(store, [g.id])
    assert [p.id for p in profiles] == [a.id, sv.id]


def test_group_with_unknown_server_rejected(tmp_path):
    store, a, _, _, _ = _store_with_server(tmp_path)
    with pytest.raises(ValueError, match="unknown server id: 999"):
        create_balancer_group("bal", "latency", [a.id], store, server_ids=["999"])


def test_server_chain_loop_rejected_in_group(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    a = store.add_profile(Profile(name="a", kind="vmess"))
    sv1 = store.add_server(Server(name="s1", port=1081))
    sv2 = store.add_server(Server(name="s2", port=1082))
    sv1.outbound_type = "server"
    sv1.outbound_id = sv2.id
    sv2.outbound_type = "server"
    sv2.outbound_id = sv1.id
    with pytest.raises(ValueError, match="circular server reference"):
        create_balancer_group("bal", "latency", [a.id], store, server_ids=[sv1.id])


def test_server_forwarding_to_group_containing_it_rejected(tmp_path):
    """Creating a group with a server that forwards to a group already
    containing that server is rejected (a runtime loop)."""
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    a = store.add_profile(Profile(name="a", kind="vmess"))
    sv = store.add_server(Server(name="s1", port=1081))
    g = store.add_group(Group(name="g", profile_ids=[a.id], server_ids=[sv.id]))
    sv.outbound_type = "group"
    sv.outbound_id = g.id
    assert server_reaches_group(store, sv.id, g.id)
    assert server_reaches_group(store, sv.id, None)
    with pytest.raises(ValueError, match="forwards"):
        create_balancer_group("bal", "latency", [a.id], store, server_ids=[sv.id])


# -- hierarchy tree ---------------------------------------------------------


def _tree_store(tmp_path):
    """A small nested config: group G1 (balancer) contains a profile, a
    subscription, a server, and nested group G2; plus standalone entities."""
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    p1 = store.add_profile(Profile(name="p1", kind="vmess"))
    p2 = store.add_profile(Profile(name="p2", kind="vless"))
    p3 = store.add_profile(Profile(name="p3", kind="trojan"))
    p4 = store.add_profile(Profile(name="p4", kind="socks"))
    p5 = store.add_profile(Profile(name="p5", kind="http"))
    s1 = store.add_subscription(Subscription(name="sub1", profile_ids=[p2.id, p3.id]))
    s2 = store.add_subscription(Subscription(name="sub2", profile_ids=[p5.id]))
    sv1 = store.add_server(Server(name="local", port=1081))
    sv2 = store.add_server(Server(name="other", port=1082))
    g2 = store.add_group(Group(name="inner", type="single", profile_ids=[p4.id]))
    g1 = store.add_group(Group(
        name="fast", type="balancer", strategy="latency",
        profile_ids=[p1.id], subscription_ids=[s1.id],
        server_ids=[sv1.id], group_ids=[g2.id],
    ))
    return store, (p1, p2, p3, p4, p5), (s1, s2), (sv1, sv2), (g1, g2)


def test_group_tree_empty(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    assert group_tree_lines(store) == []


def test_group_tree_renders_nested_hierarchy(tmp_path):
    store, (p1, p2, p3, p4, p5), (s1, s2), (sv1, sv2), (g1, g2) = _tree_store(tmp_path)
    lines = group_tree_lines(store)

    text = "\n".join(lines)
    # Top-level group root with its strategy.
    assert f"{g1.id}  balancer fast (latency)" in text
    # Nested members, in order: profile, subscription(+profiles), server, group.
    assert f"{p1.id}  vmess p1" in text
    assert f"{s1.id}  subscription sub1 (2 profiles)" in text
    assert f"{p2.id}  vless p2" in text
    assert f"{p3.id}  trojan p3" in text
    assert f"{sv1.id}  server local :1081" in text
    assert f"{g2.id}  single inner" in text
    assert f"{p4.id}  socks p4" in text
    # Standalone subscription, server, and profile are roots too.
    assert f"{s2.id}  subscription sub2 (1 profiles)" in text
    assert f"{sv2.id}  server other :1082" in text
    assert f"{p5.id}  http p5" in text
    # The standalone profile must appear once (its subscription ref is a root,
    # and it is not duplicated as a standalone).
    assert text.count(f"{p5.id}  http p5") == 1


def test_group_tree_nesting_depths_and_branches(tmp_path):
    store, _, _, _, (g1, _) = _tree_store(tmp_path)
    lines = group_tree_lines(store)
    text = "\n".join(lines)
    # The profile member sits one level under the group root.
    assert "├── " + f"{g1.id}  balancer fast (latency)" in text
    assert "│   ├── " in text
    assert "│   └── " in text


def test_group_tree_server_outbound_hint(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    p = store.add_profile(Profile(name="p", kind="vmess"))
    sv = store.add_server(Server(name="local", port=1081))
    sv.outbound_type = "group"
    sv.outbound_id = p.id  # fake a group ref for display
    store.add_group(Group(name="g", type="single", server_ids=[sv.id]))
    text = "\n".join(group_tree_lines(store))
    assert f"→ group/{p.id}" in text


def test_group_tree_truncates_cycles(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    a = store.add_group(Group(name="a", type="single"))
    b = store.add_group(Group(name="b", type="single"))
    a.group_ids.append(b.id)
    b.group_ids.append(a.id)
    # A top-level group reaches the a↔b cycle (hand-edited config).
    x = store.add_group(Group(name="x", type="single", group_ids=[a.id]))
    lines = group_tree_lines(store)
    text = "\n".join(lines)
    assert f"{x.id}  single x" in text
    assert "(cycle — not expanded)" in text
    # Terminates: a cycle must not blow the recursion.
    assert len(lines) < 10
