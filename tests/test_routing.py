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


def test_normalize_validates_persisted_rules():
    cfg = RoutingConfig(mode="split", rules=[RoutingRule(action="proxy", match=None)])
    with pytest.raises(ValueError, match="match must be an object"):
        normalize_rules(cfg, selected_target_id="T")

    cfg.rules = [RoutingRule(action="proxy", match={"domains": "example.com"})]
    with pytest.raises(ValueError, match="domains matcher must be a list"):
        normalize_rules(cfg, selected_target_id="T")

    cfg.rules = [RoutingRule(action="wat", match={})]
    with pytest.raises(ValueError, match="invalid action"):
        normalize_rules(cfg, selected_target_id="T")

    cfg.rules = [RoutingRule(action="direct", target_id=123, match={})]
    with pytest.raises(ValueError, match="target_id"):
        normalize_rules(cfg, selected_target_id="T")

    cfg.rules = "bad"
    with pytest.raises(ValueError, match="routing rules must be a list"):
        normalize_rules(cfg, selected_target_id="T")

    cfg.rules = [RoutingRule(action="proxy", match={})]
    with pytest.raises(ValueError, match="proxy rule requires a target"):
        normalize_rules(cfg, selected_target_id=None)

    with pytest.raises(ValueError, match="selected target id"):
        normalize_rules(cfg, selected_target_id=123)


def test_normalize_rejects_unknown_target_id():
    """Proxy rule targeting a non-existent profile/group is rejected."""
    cfg = RoutingConfig(
        mode="split",
        rules=[RoutingRule(action="proxy", target_id="dead-id", match={"domains": ["x.com"]})],
    )
    known = {"direct", "block", "live-profile"}
    with pytest.raises(ValueError, match="unknown id"):
        normalize_rules(cfg, selected_target_id=None, known_target_ids=known)


def test_normalize_accepts_known_target_id():
    """Proxy rule targeting a known ID passes validation."""
    cfg = RoutingConfig(
        mode="split",
        rules=[RoutingRule(action="proxy", target_id="live-profile", match={"domains": ["x.com"]})],
    )
    known = {"direct", "block", "live-profile"}
    out = normalize_rules(cfg, selected_target_id=None, known_target_ids=known)
    assert out[0].target_id == "live-profile"


def test_normalize_accepts_server_target_id():
    """Proxy rule targeting a server ID passes validation."""
    cfg = RoutingConfig(
        mode="split",
        rules=[RoutingRule(action="proxy", target_id="server-007", match={"domains": ["x.com"]})],
    )
    known = {"direct", "block", "server-007"}
    out = normalize_rules(cfg, selected_target_id=None, known_target_ids=known)
    assert out[0].target_id == "server-007"


def test_normalize_known_ids_includes_direct_block():
    """Direct/block actions are always valid even with known_target_ids set."""
    cfg = RoutingConfig(
        mode="split",
        rules=[
            RoutingRule(action="direct", match={"domains": ["local.dev"]}),
            RoutingRule(action="block", match={"domains": ["ads.dev"]}),
        ],
    )
    known = {"direct", "block"}
    out = normalize_rules(cfg, selected_target_id=None, known_target_ids=known)
    assert len(out) == 2
    assert out[0].action == "direct"
    assert out[1].action == "block"


def test_normalize_skips_unknown_check_when_none():
    """known_target_ids=None disables the unknown-id check (backward compat)."""
    cfg = RoutingConfig(
        mode="split",
        rules=[RoutingRule(action="proxy", target_id="any-id", match={"domains": ["x.com"]})],
    )
    # Should not raise even though 'any-id' is not a known profile.
    out = normalize_rules(cfg, selected_target_id=None, known_target_ids=None)
    assert out[0].target_id == "any-id"


def test_normalize_null_target_resolves_to_selected_then_checked():
    """Null target resolves to selected_target_id, then is checked against known."""
    cfg = RoutingConfig(
        mode="split",
        rules=[RoutingRule(action="proxy", target_id=None, match={"domains": ["x.com"]})],
    )
    known = {"direct", "block", "ok-id"}
    # selected_target_id resolves to 'missing-id', which is not in known.
    with pytest.raises(ValueError, match="unknown id"):
        normalize_rules(cfg, selected_target_id="missing-id", known_target_ids=known)
    # But 'ok-id' is in known, so it passes.
    out = normalize_rules(cfg, selected_target_id="ok-id", known_target_ids=known)
    assert out[0].target_id == "ok-id"


def test_normalize_skips_disabled_rules():
    """Disabled rules are excluded from normalized output."""
    cfg = RoutingConfig(
        mode="split",
        rules=[
            RoutingRule(action="direct", enabled=True, match={"domains": ["a.com"]}),
            RoutingRule(action="block", enabled=False, match={"domains": ["b.com"]}),
            RoutingRule(action="direct", enabled=True, match={"domains": ["c.com"]}),
        ],
    )
    out = normalize_rules(cfg, selected_target_id=None)
    assert len(out) == 2
    assert out[0].match["domains"] == ["a.com"]
    assert out[1].match["domains"] == ["c.com"]


def test_disabled_rule_default_enabled():
    """New rules default to enabled=True."""
    rule = RoutingRule(action="direct", match={"domains": ["x.com"]})
    assert rule.enabled is True


def test_disabled_rule_in_config():
    """A rule with enabled=False persists correctly."""
    rule = RoutingRule(action="block", enabled=False, match={"domains": ["ads.dev"]})
    data = rule.to_dict()
    assert data["enabled"] is False
    restored = RoutingRule.from_dict(data)
    assert restored.enabled is False
