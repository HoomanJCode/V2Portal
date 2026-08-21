"""Split-routing rule editor."""

from __future__ import annotations

from ..routing.rules import add_rule, validate_rule
from ..models import RoutingRule
from . import widgets


def _split(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def _resolve_target_name(store, rule) -> str:
    """Return a human-readable label for a rule's target."""
    if rule.action == "direct":
        return "direct"
    if rule.action == "block":
        return "block"
    if not rule.target_id:
        return "(no target)"
    profile = store.get_profile(rule.target_id)
    if profile:
        return f"{profile.kind} {profile.name}"
    group = store.get_group(rule.target_id)
    if group:
        return f"group {group.name}"
    return rule.target_id[:8]


def _rule_label(store, rule) -> str:
    """Build a short display label for a routing rule."""
    target = _resolve_target_name(store, rule)
    parts: list[str] = []
    domains = rule.match.get("domains", [])
    ips = rule.match.get("ips", [])
    geoip = rule.match.get("geoip", [])
    geosite = rule.match.get("geosite", [])
    if domains:
        preview = ", ".join(domains[:2])
        if len(domains) > 2:
            preview += ", ..."
        parts.append(f"dom={preview}")
    if ips:
        preview = ", ".join(ips[:2])
        if len(ips) > 2:
            preview += ", ..."
        parts.append(f"ip={preview}")
    if geoip:
        parts.append(f"geoip={','.join(geoip)}")
    if geosite:
        parts.append(f"geosite={','.join(geosite)}")
    match_str = " ".join(parts) if parts else "(empty match)"
    return f"{rule.action} -> {target}  [{match_str}]"


def _pick_target(store):
    """Let the user pick a profile or group as a routing target. Returns the ID or None."""
    profiles = store.list_profiles()
    groups = store.list_groups()
    if not profiles and not groups:
        widgets.show_message("No targets", "Add a profile or group first.")
        return None
    selection = widgets.pick_profile(profiles, groups, include_vpn=False)
    if selection is None:
        return None
    _kind, key = selection
    return key


def run(store) -> None:
    routing = store.config.routing
    while True:
        mode = "split" if routing.mode == "split" else "all"
        action = widgets.menu(
            f"Routing (mode={mode})",
            [
                ("toggle", "Toggle mode (all/split)"),
                ("add", "Add rule"),
                ("edit", "Edit rule"),
                ("remove", "Remove rule"),
                ("move", "Move rule up/down"),
                ("back", "Back"),
            ],
        )
        if action is None or action == "back":
            return
        if action == "toggle":
            routing.mode = "all" if routing.mode == "split" else "split"
        elif action == "add":
            _add_rule(store)
        elif action == "edit":
            _edit_rule(store)
        elif action == "remove":
            _remove_rule(store)
        elif action == "move":
            _move_rule(routing)
        store.save()


def _add_rule(store) -> None:
    routing = store.config.routing
    action = widgets.menu("Action", [("proxy", "proxy"), ("direct", "direct"), ("block", "block")])
    if action is None:
        return

    target_id = None
    if action == "proxy":
        target_id = _pick_target(store)
        if target_id is None:
            return

    domains = widgets.input_text("Domains (comma separated; keyword:/regex:/geosite: prefixes)")
    ips = widgets.input_text("IPs/CIDRs (comma separated; geoip: prefix)")
    match = {"domains": _split(domains), "ips": _split(ips), "geoip": [], "geosite": []}
    try:
        rule = add_rule(action, match, target_id=target_id)
    except ValueError as exc:
        widgets.show_message("Invalid rule", str(exc))
        return
    routing.rules.append(rule)


def _edit_rule(store) -> None:
    routing = store.config.routing
    if not routing.rules:
        widgets.show_message("No rules", "Nothing to edit.")
        return
    choice = widgets.menu(
        "Edit rule",
        [(r.id, _rule_label(store, r)) for r in routing.rules],
    )
    if choice is None:
        return
    rule = next(r for r in routing.rules if r.id == choice)

    field = widgets.menu(
        "Field",
        [
            ("action", "Action"),
            ("target", "Target (profile/group)"),
            ("domains", "Domains"),
            ("ips", "IPs/CIDRs"),
            ("back", "Back"),
        ],
    )
    if field is None or field == "back":
        return

    if field == "action":
        new_action = widgets.menu(
            "Action", [("proxy", "proxy"), ("direct", "direct"), ("block", "block")]
        )
        if new_action is None:
            return
        rule.action = new_action
        # If switching to proxy and no target, ask for one.
        if new_action == "proxy" and not rule.target_id:
            rule.target_id = _pick_target(store)
        # If switching away from proxy, clear target.
        if new_action != "proxy":
            rule.target_id = None
    elif field == "target":
        if rule.action != "proxy":
            widgets.show_message("Not a proxy rule", "Only proxy rules have a target.")
            return
        new_target = _pick_target(store)
        if new_target is not None:
            rule.target_id = new_target
    elif field == "domains":
        current = ", ".join(rule.match.get("domains", []))
        raw = widgets.input_text("Domains", current)
        rule.match["domains"] = _split(raw)
    elif field == "ips":
        current = ", ".join(rule.match.get("ips", []))
        raw = widgets.input_text("IPs/CIDRs", current)
        rule.match["ips"] = _split(raw)

    try:
        validate_rule(rule)
    except ValueError as exc:
        widgets.show_message("Invalid rule", str(exc))


def _remove_rule(store) -> None:
    routing = store.config.routing
    if not routing.rules:
        widgets.show_message("No rules", "Nothing to remove.")
        return
    choice = widgets.menu(
        "Remove rule",
        [(r.id, _rule_label(store, r)) for r in routing.rules],
    )
    if choice is None:
        return
    store.remove_rule(choice)


def _move_rule(routing) -> None:
    if len(routing.rules) < 2:
        return
    choice = widgets.menu("Move rule", [(r.id, r.action) for r in routing.rules])
    if choice is None:
        return
    direction = widgets.menu("Direction", [("up", "Up"), ("down", "Down")])
    if direction is None:
        return
    index = next(i for i, r in enumerate(routing.rules) if r.id == choice)
    swap = index - 1 if direction == "up" else index + 1
    if 0 <= swap < len(routing.rules):
        routing.rules[index], routing.rules[swap] = routing.rules[swap], routing.rules[index]
