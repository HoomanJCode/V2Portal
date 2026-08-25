import pytest

from v2raycli.models import Group, Profile
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
    group = Group(
        name="broken",
        type="chain",
        profile_ids=[manual.id, manual.id],
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

    with pytest.raises(ValueError, match="at least one profile"):
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
