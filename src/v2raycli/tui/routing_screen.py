"""Split-routing rule editor."""

from __future__ import annotations

from ..routing.rules import add_rule
from . import widgets


def _split(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def run(store) -> None:
    routing = store.config.routing
    while True:
        mode = "split" if routing.mode == "split" else "all"
        action = widgets.menu(
            f"Routing (mode={mode})",
            [
                ("toggle", "Toggle mode (all/split)"),
                ("add", "Add rule"),
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
            _add_rule(routing)
        elif action == "remove":
            _remove_rule(store)
        elif action == "move":
            _move_rule(routing)
        store.save()


def _add_rule(routing) -> None:
    action = widgets.menu("Action", [("proxy", "proxy"), ("direct", "direct"), ("block", "block")])
    if action is None:
        return
    domains = widgets.input_text("Domains (comma separated; keyword:/regex:/geosite: prefixes)")
    ips = widgets.input_text("IPs/CIDRs (comma separated; geoip: prefix)")
    match = {"domains": _split(domains), "ips": _split(ips), "geoip": [], "geosite": []}
    try:
        rule = add_rule(action, match)
    except ValueError as exc:
        widgets.show_message("Invalid rule", str(exc))
        return
    routing.rules.append(rule)


def _remove_rule(store) -> None:
    routing = store.config.routing
    if not routing.rules:
        widgets.show_message("No rules", "Nothing to remove.")
        return
    choice = widgets.menu("Remove rule", [(r.id, r.action) for r in routing.rules])
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
