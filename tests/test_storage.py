import json
import re

import pytest

from v2raycli.models import Group, Profile, Subscription
from v2raycli.storage import ConfigLoadError, ConfigStore


def test_first_run_creates_default(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = store.load()
    assert cfg.schema_version == 2
    assert cfg.settings.mixed_port == 1080
    assert cfg.settings.default_engine == "sing-box"
    assert cfg.profiles == []
    assert (tmp_path / "config.json").exists()


def test_load_rejects_malformed_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not-json")

    with pytest.raises(ConfigLoadError, match="could not load config"):
        ConfigStore(path).load()


def test_load_rejects_wrong_config_shape(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"profiles": {}}')

    with pytest.raises(ConfigLoadError, match="must be a list"):
        ConfigStore(path).load()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"settings": {"dns": {}}}, "settings.dns must be a list"),
        ({"engines": {"xray": {"binary_path": []}}}, "config engines.xray.binary_path must be text"),
        ({"profiles": [{"outbound": []}]}, "config profiles[0].outbound must be an object"),
        ({"profiles": [{"vpn": []}]}, "config profiles[0].vpn must be an object"),
        ({"subscriptions": [{"profile_ids": "profile-id"}]}, "subscriptions[0].profile_ids must be a list"),
        ({"groups": [{"profile_ids": [123]}]}, "groups[0].profile_ids[0] must be text"),
        ({"routing": {"rules": [{"match": {"ips": "10.0.0.0/8"}}]}}, "rules[0].match.ips must be a list"),
        ({"routing": {"rules": [{"enabled": "yes"}]}}, "rules[0].enabled must be boolean"),
    ],
)
def test_load_rejects_malformed_nested_shapes(tmp_path, payload, message):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(ConfigLoadError, match=re.escape(message)):
        ConfigStore(path).load()


def test_load_rejects_unsupported_schema_version(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schema_version": 999}))

    with pytest.raises(ConfigLoadError, match="unsupported schema_version"):
        ConfigStore(path).load()


def test_round_trip(tmp_path):
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    store.load()
    store.add_profile(Profile(name="A", kind="socks"))
    store.save()

    reloaded = ConfigStore(path)
    reloaded.load()
    assert len(reloaded.config.profiles) == 1
    assert reloaded.config.profiles[0].name == "A"


def test_atomic_write_leaves_no_temp_files(tmp_path):
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    store.load()
    store.save()
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_remove_subscription_unlinks_profiles(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    sub = store.add_subscription(Subscription(name="S"))
    store.add_profile(Profile(name="P", subscription_id=sub.id))

    assert store.remove_subscription(sub.id) is True
    assert store.config.profiles[0].subscription_id is None
    assert store.remove_subscription("missing") is False


def test_profile_and_group_crud(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    p = store.add_profile(Profile(name="P"))
    g = store.add_group(Group(name="G", profile_ids=[p.id]))

    assert store.get_profile(p.id) is p
    assert store.get_group(g.id) is g
    assert store.remove_group(g.id) is True
    assert store.remove_profile(p.id) is True
    assert store.get_profile(p.id) is None


def test_update_settings_and_engine(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    store.update_settings(mixed_port=9999)
    store.update_engine("sing-box", binary_path="/usr/bin/sing-box")

    assert store.config.settings.mixed_port == 9999
    assert store.config.engines["sing-box"]["binary_path"] == "/usr/bin/sing-box"


def test_remove_profile_cleans_routing_rules(tmp_path):
    """Routing rules targeting a deleted profile are removed."""
    from v2raycli.models import RoutingRule

    store = ConfigStore(tmp_path / "config.json")
    store.load()
    p1 = store.add_profile(Profile(name="A"))
    p2 = store.add_profile(Profile(name="B"))
    store.config.routing.rules = [
        RoutingRule(action="proxy", target_id=p1.id, match={"domains": ["a.com"]}),
        RoutingRule(action="proxy", target_id=p2.id, match={"domains": ["b.com"]}),
        RoutingRule(action="direct", match={"domains": ["local.dev"]}),
    ]

    store.remove_profile(p1.id)

    remaining = store.config.routing.rules
    assert len(remaining) == 2
    assert all(r.target_id != p1.id for r in remaining)
    # p2's rule and the direct rule are untouched.
    assert any(r.target_id == p2.id for r in remaining)
    assert any(r.action == "direct" for r in remaining)


def test_remove_group_cleans_routing_rules(tmp_path):
    """Routing rules targeting a deleted group are removed."""
    from v2raycli.models import RoutingRule

    store = ConfigStore(tmp_path / "config.json")
    store.load()
    g = store.add_group(Group(name="G", profile_ids=[]))
    store.config.routing.rules = [
        RoutingRule(action="proxy", target_id=g.id, match={"domains": ["x.com"]}),
        RoutingRule(action="direct", match={"domains": ["y.com"]}),
    ]

    store.remove_group(g.id)

    remaining = store.config.routing.rules
    assert len(remaining) == 1
    assert remaining[0].action == "direct"


def test_remove_profile_cleans_group_profile_ids_and_routing(tmp_path):
    """Removing a profile cleans it from groups and routing rules."""
    from v2raycli.models import RoutingRule

    store = ConfigStore(tmp_path / "config.json")
    store.load()
    p = store.add_profile(Profile(name="P"))
    g = store.add_group(Group(name="G", profile_ids=[p.id, "other-id"]))
    store.config.routing.rules = [
        RoutingRule(action="proxy", target_id=p.id, match={"domains": ["p.com"]}),
    ]

    store.remove_profile(p.id)

    assert g.profile_ids == ["other-id"]
    assert store.config.routing.rules == []
