"""Split-routing rule helpers: validation, ordering, normalization."""

from __future__ import annotations

import ipaddress

from ..models import RoutingConfig, RoutingRule

ACTIONS = {"proxy", "direct", "block"}
MATCH_KEYS = {"domains", "ips", "geoip", "geosite"}


def _validate_cidr(ip: str) -> None:
    try:
        ipaddress.ip_network(ip, strict=False)
    except ValueError as exc:
        raise ValueError(f"invalid CIDR: {ip}") from exc


def validate_rule(rule: RoutingRule) -> None:
    if not isinstance(rule, RoutingRule):
        raise ValueError("routing rule must be a RoutingRule")
    if not isinstance(rule.action, str) or rule.action not in ACTIONS:
        raise ValueError(f"invalid action: {rule.action}")
    if rule.target_id is not None and (
        not isinstance(rule.target_id, str) or not rule.target_id.strip()
    ):
        raise ValueError("rule target_id must be non-empty text")
    if not isinstance(rule.match, dict):
        raise ValueError("rule match must be an object")
    unknown = set(rule.match) - MATCH_KEYS
    if unknown:
        raise ValueError(f"unknown match keys: {sorted(unknown, key=str)}")
    for key in MATCH_KEYS:
        values = rule.match.get(key, [])
        if not isinstance(values, list):
            raise ValueError(f"rule {key} matcher must be a list")
        for item in values:
            if not isinstance(item, str) or not item.strip():
                raise ValueError(f"invalid {key} entry: {item!r}")
    for ip in rule.match.get("ips", []):
        _validate_cidr(ip)
    for domain in rule.match.get("domains", []):
        if domain.startswith("regex:") and domain == "regex:":
            raise ValueError("empty regex matcher")


def add_rule(action: str, match: dict, target_id: str | None = None) -> RoutingRule:
    rule = RoutingRule(action=action, target_id=target_id, match=match)
    validate_rule(rule)
    return rule


def reorder_rules(rules: list[RoutingRule], ordered_ids: list[str]) -> list[RoutingRule]:
    by_id = {r.id: r for r in rules}
    if set(ordered_ids) != set(by_id):
        raise ValueError("ordered_ids must match the rule set")
    return [by_id[i] for i in ordered_ids]


def uses_geo(routing: RoutingConfig) -> bool:
    """True if split routing references any geoip/geosite assets."""
    if routing.mode != "split":
        return False
    for rule in routing.rules:
        if rule.match.get("geoip") or rule.match.get("geosite"):
            return True
        if any(d.startswith("geosite:") for d in rule.match.get("domains", [])):
            return True
        if any(i.startswith("geoip:") for i in rule.match.get("ips", [])):
            return True
    return False


def normalize_rules(
    routing: RoutingConfig,
    selected_target_id: str | None,
    known_target_ids: set[str] | None = None,
) -> list[RoutingRule]:
    """Return a validated copy of rules with null targets resolved.

    When *known_target_ids* is provided, every proxy rule's target_id must
    be present in that set.  This catches rules that reference profiles or
    groups that were deleted or never existed.
    """
    if not isinstance(routing, RoutingConfig):
        raise ValueError("routing config must be a RoutingConfig")
    if not isinstance(routing.rules, list):
        raise ValueError("routing rules must be a list")
    if selected_target_id is not None and (
        not isinstance(selected_target_id, str) or not selected_target_id.strip()
    ):
        raise ValueError("selected target id must be non-empty text")

    normalized: list[RoutingRule] = []
    for rule in routing.rules:
        if not rule.enabled:
            continue
        validate_rule(rule)
        target_id = rule.target_id if rule.target_id is not None else selected_target_id
        if rule.action == "proxy" and target_id is None:
            raise ValueError("proxy rule requires a target")
        if (
            known_target_ids is not None
            and rule.action == "proxy"
            and target_id is not None
            and target_id not in known_target_ids
        ):
            raise ValueError(
                f"rule targets unknown id {target_id!r}; "
                f"the profile or group may have been removed"
            )
        normalized.append(
            RoutingRule(
                id=rule.id,
                action=rule.action,
                target_id=target_id,
                match={k: list(v) for k, v in rule.match.items()},
            )
        )
    return normalized
