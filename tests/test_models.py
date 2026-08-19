import json

from v2raycli.models import (
    Config,
    Group,
    Profile,
    RoutingConfig,
    RoutingRule,
    Settings,
    Subscription,
)


def _round(obj):
    return json.loads(json.dumps(obj.to_dict()))


def test_profile_round_trip():
    p = Profile(name="US-01", kind="vmess", outbound={"settings": {"vnext": []}})
    assert Profile.from_dict(_round(p)) == p


def test_subscription_round_trip():
    s = Subscription(name="Provider", url="https://example.com/sub", profile_ids=["a", "b"])
    assert Subscription.from_dict(_round(s)) == s


def test_group_round_trip():
    g = Group(name="Auto", type="balancer", strategy="latency", profile_ids=["a", "b"])
    assert Group.from_dict(_round(g)) == g


def test_settings_round_trip():
    s = Settings(mixed_port=9999, listen="127.0.0.1")
    assert Settings.from_dict(_round(s)) == s


def test_routing_round_trip():
    r = RoutingConfig(mode="split", rules=[RoutingRule(action="direct")])
    d = _round(r)
    assert RoutingConfig.from_dict(d) == r


def test_config_round_trip():
    c = Config(
        profiles=[Profile(name="P")],
        subscriptions=[Subscription(name="S")],
        groups=[Group(name="G")],
    )
    assert Config.from_dict(_round(c)) == c


def test_defaults_have_ids_and_timestamps():
    p = Profile()
    assert p.id
    assert p.created_at
    assert p.updated_at
    assert p.engine == "auto"
    assert p.kind == "manual"
