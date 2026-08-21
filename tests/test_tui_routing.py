import pytest

pytest.importorskip("prompt_toolkit")

from v2raycli.models import Group, Profile, RoutingConfig, RoutingRule
from v2raycli.storage import ConfigStore
from v2raycli.tui import routing_screen


SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}


def _store(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    return store


def test_add_proxy_rule_with_target(tmp_path, monkeypatch):
    """Adding a proxy rule lets the user pick a target profile."""
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="Netflix", kind="vmess", outbound=SOCKS))
    routing = store.config.routing

    # Simulate UI: action=proxy, target=p, domains=netflix.com, ips=""
    actions = iter(["proxy"])
    targets = iter([("profile", p.id)])
    inputs = iter(["netflix.com", ""])
    messages = []

    monkeypatch.setattr(routing_screen.widgets, "menu", lambda *args: next(actions))
    monkeypatch.setattr(
        routing_screen.widgets, "pick_profile", lambda *a, **kw: next(targets)
    )
    monkeypatch.setattr(routing_screen.widgets, "input_text", lambda *args: next(inputs))
    monkeypatch.setattr(
        routing_screen.widgets, "show_message", lambda t, m: messages.append((t, m))
    )

    routing_screen._add_rule(store)

    assert len(routing.rules) == 1
    rule = routing.rules[0]
    assert rule.action == "proxy"
    assert rule.target_id == p.id
    assert rule.match["domains"] == ["netflix.com"]
    assert not messages


def test_add_direct_rule_no_target(tmp_path, monkeypatch):
    """Direct/block rules do not prompt for a target."""
    store = _store(tmp_path)
    routing = store.config.routing

    actions = iter(["direct"])
    inputs = iter(["local.dev", ""])
    messages = []

    monkeypatch.setattr(routing_screen.widgets, "menu", lambda *args: next(actions))
    monkeypatch.setattr(routing_screen.widgets, "input_text", lambda *args: next(inputs))
    monkeypatch.setattr(
        routing_screen.widgets, "show_message", lambda t, m: messages.append((t, m))
    )

    routing_screen._add_rule(store)

    assert len(routing.rules) == 1
    rule = routing.rules[0]
    assert rule.action == "direct"
    assert rule.target_id is None


def test_add_proxy_rule_cancelled_target(tmp_path, monkeypatch):
    """If user cancels target selection, rule is not added."""
    store = _store(tmp_path)
    store.add_profile(Profile(name="A", kind="vmess", outbound=SOCKS))
    routing = store.config.routing

    actions = iter(["proxy"])
    # pick_profile returns None (user cancelled)

    monkeypatch.setattr(routing_screen.widgets, "menu", lambda *args: next(actions))
    monkeypatch.setattr(routing_screen.widgets, "pick_profile", lambda *a, **kw: None)

    routing_screen._add_rule(store)

    assert len(routing.rules) == 0


def test_edit_rule_changes_target(tmp_path, monkeypatch):
    """Editing a rule's target updates it."""
    store = _store(tmp_path)
    p1 = store.add_profile(Profile(name="A", kind="vmess", outbound=SOCKS))
    p2 = store.add_profile(Profile(name="B", kind="vmess", outbound=SOCKS))
    routing = store.config.routing
    rule = RoutingRule(action="proxy", target_id=p1.id, match={"domains": ["a.com"]})
    routing.rules.append(rule)

    # Simulate: pick rule, choose 'target', pick new target
    choices = iter([rule.id])
    fields = iter(["target"])
    targets = iter([("profile", p2.id)])
    messages = []

    monkeypatch.setattr(routing_screen.widgets, "menu", lambda *args: next(choices))
    monkeypatch.setattr(
        routing_screen.widgets, "pick_profile", lambda *a, **kw: next(targets)
    )
    # For the inner field menu and the edit-rule menu, we need a combined sequence
    # Actually, the flow is: menu (pick rule) -> menu (pick field) -> pick_profile
    # Let me fix: the first menu call is _edit_rule's rule picker, second is field picker
    call_count = [0]
    original_menu = routing_screen.widgets.menu

    def fake_menu(title, values, *a, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            return rule.id  # pick the rule
        if call_count[0] == 2:
            return "target"  # pick field
        return next(actions)

    actions = iter([])
    monkeypatch.setattr(routing_screen.widgets, "menu", fake_menu)
    monkeypatch.setattr(
        routing_screen.widgets, "show_message", lambda t, m: messages.append((t, m))
    )

    routing_screen._edit_rule(store)

    assert rule.target_id == p2.id


def test_edit_rule_changes_action_to_direct(tmp_path, monkeypatch):
    """Editing action from proxy to direct clears target_id."""
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="A", kind="vmess", outbound=SOCKS))
    routing = store.config.routing
    rule = RoutingRule(action="proxy", target_id=p.id, match={"domains": ["a.com"]})
    routing.rules.append(rule)

    call_count = [0]

    def fake_menu(title, values, *a, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            return rule.id
        if call_count[0] == 2:
            return "action"
        if call_count[0] == 3:
            return "direct"
        return None

    monkeypatch.setattr(routing_screen.widgets, "menu", fake_menu)

    routing_screen._edit_rule(store)

    assert rule.action == "direct"
    assert rule.target_id is None


def test_rule_label_shows_target_and_match(tmp_path):
    """_rule_label formats a readable label."""
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="Netflix", kind="vmess", outbound=SOCKS))
    rule = RoutingRule(
        action="proxy",
        target_id=p.id,
        match={"domains": ["netflix.com", "nflxvideo.net", "nflxext.com"], "ips": ["10.0.0.0/8"]},
    )
    label = routing_screen._rule_label(store, rule)
    assert "proxy" in label
    assert "Netflix" in label
    assert "netflix.com" in label
    assert "..." in label  # domains truncated (>2)
    assert "10.0.0.0/8" in label


def test_resolve_target_name_direct_block():
    """Direct and block rules show their action as target name."""
    from types import SimpleNamespace

    store = SimpleNamespace(
        get_profile=lambda id: None,
        get_group=lambda id: None,
    )
    assert routing_screen._resolve_target_name(store, RoutingRule(action="direct")) == "direct"
    assert routing_screen._resolve_target_name(store, RoutingRule(action="block")) == "block"


def test_resolve_target_name_profile(tmp_path):
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="US-01", kind="vmess", outbound=SOCKS))
    rule = RoutingRule(action="proxy", target_id=p.id)
    assert "US-01" in routing_screen._resolve_target_name(store, rule)


def test_resolve_target_name_group(tmp_path):
    store = _store(tmp_path)
    g = store.add_group(Group(name="Auto", type="balancer", strategy="latency", profile_ids=[]))
    rule = RoutingRule(action="proxy", target_id=g.id)
    assert "Auto" in routing_screen._resolve_target_name(store, rule)


def test_edit_rule_no_rules_shows_message(tmp_path, monkeypatch):
    store = _store(tmp_path)
    messages = []
    monkeypatch.setattr(
        routing_screen.widgets, "show_message", lambda t, m: messages.append((t, m))
    )
    routing_screen._edit_rule(store)
    assert messages == [("No rules", "Nothing to edit.")]


def test_remove_rule_shows_label(tmp_path, monkeypatch):
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="A", kind="vmess", outbound=SOCKS))
    rule = RoutingRule(action="proxy", target_id=p.id, match={"domains": ["a.com"]})
    store.config.routing.rules.append(rule)

    choices = []
    original_menu = routing_screen.widgets.menu

    def capture_menu(title, values, *a, **kw):
        choices.extend(values)
        return rule.id

    monkeypatch.setattr(routing_screen.widgets, "menu", capture_menu)

    routing_screen._remove_rule(store)

    # The menu should show the rule label with target info
    assert any("proxy" in label for _, label in choices)
    assert any("A" in label for _, label in choices)
