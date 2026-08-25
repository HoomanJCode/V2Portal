import json
import re

import pytest

from v2raycli.models import Group, Profile, Subscription
from v2raycli.storage import ConfigLoadError, ConfigStore


def test_first_run_creates_default(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = store.load()
    assert cfg.schema_version == 3
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


def test_remove_subscription_deletes_profiles_and_prunes_groups(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    sub = store.add_subscription(Subscription(name="S"))
    store.add_profile(Profile(name="P", subscription_id=sub.id))
    g = store.add_group(Group(name="G", subscription_ids=[sub.id]))

    summary = store.remove_subscription(sub.id)
    assert summary["deleted_profiles"] == 1
    assert summary["pruned_groups"] == 1
    assert store.config.profiles == []
    assert g.subscription_ids == []
    assert store.remove_subscription("missing") == {}


def test_profile_and_group_crud(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    p = store.add_profile(Profile(name="P"))
    g = store.add_group(Group(name="G", profile_ids=[p.id]))

    assert store.get_profile(p.id) is p
    assert store.get_group(g.id) is g
    assert store.remove_group(g.id)  # truthy summary dict
    assert store.remove_profile(p.id)  # truthy summary dict
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


def test_remove_profile_prunes_nested_group_members(tmp_path):
    """A profile used as a nested group member is pruned from group_ids."""
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    p = store.add_profile(Profile(name="P"))
    g = store.add_group(Group(name="nested", group_ids=[p.id]))

    store.remove_profile(p.id)
    assert g.group_ids == []


def test_remove_group_prunes_nested_members(tmp_path):
    """Removing a group prunes it from other groups' nested members."""
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    a = store.add_group(Group(name="a"))
    b = store.add_group(Group(name="b", group_ids=[a.id]))

    summary = store.remove_group(a.id)
    assert summary["pruned_groups"] == 1
    assert b.group_ids == []


# -- numeric ID generation --------------------------------------------------


def test_new_id_is_short_numeric():
    from v2raycli.models import new_id

    ids = [new_id() for _ in range(5)]
    assert all(len(i) <= 4 for i in ids)
    assert ids[0] != ids[1]  # sequential
    # all-numeric
    assert all(i.isdigit() for i in ids)


def test_store_next_id_is_sequential(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    id1 = store.next_id()
    id2 = store.next_id()
    id3 = store.next_id()
    assert id1 == "001"
    assert id2 == "002"
    assert id3 == "003"


# -- schema migration -------------------------------------------------------


def test_migrate_v2_uuid_ids_to_v3_numeric(tmp_path):
    """A v2 config with UUID ids is migrated to v3 with short numeric ids."""
    from v2raycli.models import RoutingRule

    path = tmp_path / "config.json"
    sub_id = "aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb"
    profile_id = "cccccccc-4444-5555-6666-dddddddddddd"
    group_id = "eeeeeeee-7777-8888-9999-ffffffffffff"
    server_id = "11111111-aaaa-bbbb-cccc-dddddddddddd"
    rule_id = "22222222-aaaa-bbbb-cccc-dddddddddddd"

    raw = {
        "schema_version": 2,
        "settings": {"mixed_port": 1080},
        "routing": {
            "mode": "split",
            "rules": [
                {
                    "id": rule_id,
                    "action": "proxy",
                    "target_id": profile_id,
                    "enabled": True,
                    "match": {"domains": [], "ips": [], "geoip": [], "geosite": []},
                }
            ],
        },
        "engines": {},
        "profiles": [
            {
                "id": profile_id,
                "name": "test",
                "kind": "socks",
                "engine": "auto",
                "source": "manual",
                "subscription_id": sub_id,
                "outbound": {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}},
                "created_at": "2024-01-01T00:00:00",
                "updated_at": "2024-01-01T00:00:00",
            }
        ],
        "subscriptions": [
            {
                "id": sub_id,
                "name": "test-sub",
                "url": "https://example.com/sub",
                "profile_ids": [profile_id],
            }
        ],
        "groups": [
            {
                "id": group_id,
                "name": "test-group",
                "type": "single",
                "strategy": "latency",
                "profile_ids": [profile_id],
                "engine": "auto",
            }
        ],
        "servers": [
            {
                "id": server_id,
                "name": "test-server",
                "port": 1080,
                "protocol": "mixed",
                "outbound_id": profile_id,
                "outbound_type": "profile",
                "listen": "0.0.0.0",
            }
        ],
    }
    path.write_text(json.dumps(raw), encoding="utf-8")

    store = ConfigStore(path)
    cfg = store.load()

    # schema version bumped
    assert cfg.schema_version == 3

    # IDs are now short numeric
    assert cfg.profiles[0].id.isdigit()
    assert cfg.subscriptions[0].id.isdigit()
    assert cfg.groups[0].id.isdigit()
    assert cfg.servers[0].id.isdigit()
    assert cfg.routing.rules[0].id.isdigit()

    # cross-references remapped
    assert cfg.profiles[0].subscription_id == cfg.subscriptions[0].id
    assert cfg.subscriptions[0].profile_ids == [cfg.profiles[0].id]
    assert cfg.groups[0].profile_ids == [cfg.profiles[0].id]
    assert cfg.routing.rules[0].target_id == cfg.profiles[0].id
    assert cfg.servers[0].outbound_id == cfg.profiles[0].id


def test_v3_config_loaded_without_migration(tmp_path):
    """A fresh v3 config is loaded directly without migration."""
    store = ConfigStore(tmp_path / "config.json")
    cfg = store.load()
    assert cfg.schema_version == 3
    # IDs should be short numeric from the start
    p = store.add_profile(Profile(name="p"))
    assert p.id.isdigit()
    assert len(p.id) <= 4
