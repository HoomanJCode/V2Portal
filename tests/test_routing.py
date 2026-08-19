import pytest

from v2raycli.models import RoutingConfig, RoutingRule
from v2raycli.routing.rules import add_rule, normalize_rules, reorder_rules


def test_add_rule_validates():
    r = add_rule("proxy", {"domains": ["example.com"], "ips": ["10.0.0.0/8"]})
    assert r.action == "proxy"
    assert r.match["ips"] == ["10.0.0.0/8"]


def test_invalid_action_and_cidr():
    with pytest.raises(ValueError):
        add_rule("wat", {"domains": ["x"]})
    with pytest.raises(ValueError):
        add_rule("proxy", {"ips": ["not-an-ip"]})
    with pytest.raises(ValueError):
        add_rule("proxy", {"bogus": ["x"]})


def test_reorder_rules():
    a = RoutingRule(action="direct")
    b = RoutingRule(action="proxy")
    assert reorder_rules([a, b], [b.id, a.id]) == [b, a]
    with pytest.raises(ValueError):
        reorder_rules([a, b], [a.id])


def test_normalize_resolves_null_target():
    cfg = RoutingConfig(
        mode="split",
        rules=[
            RoutingRule(action="proxy", target_id=None),
            RoutingRule(action="direct", target_id="explicit"),
        ],
    )
    out = normalize_rules(cfg, selected_target_id="T")
    assert out[0].target_id == "T"
    assert out[1].target_id == "explicit"
    assert out[0].id == cfg.rules[0].id
