"""Group builders (balancer/chain/single) and target resolution."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..engines import AUTO, SINGBOX, XRAY, get_adapter, resolve_engine, strategy_supported
from ..models import Group, Profile, RoutingConfig, Subscription
from .vpn import is_vpn

VALID_STRATEGIES = {"latency", "random", "roundRobin", "leastLoad"}


@dataclass
class Target:
    """A resolved connect target, consumed by config-gen/runner/tester."""

    type: str = "single"  # single | balancer | chain
    name: str = ""
    engine: str = AUTO
    strategy: str = ""
    profile_ids: list[str] = field(default_factory=list)
    profiles: list[Profile] = field(default_factory=list)
    extra_profiles: list[Profile] = field(default_factory=list)
    extra_groups: list[Group] = field(default_factory=list)


def _resolve_members(store, profile_ids) -> list[Profile]:
    if not isinstance(profile_ids, list) or not profile_ids:
        raise ValueError("group requires at least one profile")
    profiles: list[Profile] = []
    for pid in profile_ids:
        if not isinstance(pid, str) or not pid:
            raise ValueError("group profile ids must be non-empty strings")
        profile = store.get_profile(pid)
        if profile is None:
            raise ValueError(f"unknown profile id: {pid}")
        profiles.append(profile)
    return profiles


def _resolve_group_engine(
    profiles: list[Profile], strategy: str, explicit: str, default: str
) -> str:
    if explicit and explicit != AUTO:
        engine = explicit
    else:
        required = {
            resolve_engine(p.kind, "", p.engine, AUTO)
            for p in profiles
        }
        required.discard(AUTO)
        if len(required) > 1:
            raise ValueError("a group cannot mix profiles that need different engines")
        engine = required.pop() if required else default
        if strategy == "leastLoad":
            engine = XRAY
    _assert_engine_compatible(profiles, engine)
    if strategy and not strategy_supported(engine, strategy):
        raise ValueError(f"engine {engine} does not support strategy {strategy}")
    return engine


def _assert_non_vpn(profiles: list[Profile]) -> None:
    for profile in profiles:
        if is_vpn(profile):
            raise ValueError(f"VPN profile {profile.name!r} cannot join a balancer/chain")


def _assert_engine_compatible(profiles: list[Profile], engine: str) -> None:
    """Reject members that the selected engine cannot translate."""
    supported = get_adapter(engine).supported_kinds
    for profile in profiles:
        if profile.kind not in supported:
            raise ValueError(f"engine {engine} does not support profile kind {profile.kind}")


def _group_ref(
    name: str, gtype: str, strategy: str, refs: list[str], store,
    engine: str = AUTO, subscription_ids: list[str] | None = None,
    group_ids: list[str] | None = None,
) -> Group:
    """Shared validation/construction for balancer and chain groups.

    *refs* are the concrete profile ids; *subscription_ids* / *group_ids*
    are the dynamic members that are resolved at use time (kept on the
    Group for refreshability).
    """
    if gtype == "balancer" and strategy not in VALID_STRATEGIES:
        raise ValueError(f"invalid strategy: {strategy}")
    all_ids = list(refs)
    if subscription_ids:
        all_ids.extend(_resolve_subscription_profiles(store, subscription_ids))
    if group_ids:
        # Validate nested groups exist; their profiles resolve at use time.
        for gid in group_ids:
            if store.get_group(gid) is None:
                raise ValueError(f"unknown group id: {gid}")
    if not all_ids and not group_ids:
        raise ValueError("group requires at least one profile, subscription, or group")
    profiles = resolve_refs(store, all_ids) if all_ids else []
    _assert_non_vpn(profiles)
    if gtype == "balancer":
        _resolve_group_engine(profiles, strategy, engine, SINGBOX)  # validates strategy support
    else:
        _resolve_group_engine(profiles, "", engine, SINGBOX)
    return Group(
        name=name, type=gtype, strategy=strategy,
        profile_ids=list(refs),
        subscription_ids=list(subscription_ids) if subscription_ids else [],
        group_ids=list(group_ids) if group_ids else [],
        engine=engine,
    )


def create_balancer_group(
    name: str, strategy: str, profile_ids: list[str], store, engine: str = AUTO,
    subscription_ids: list[str] | None = None, group_ids: list[str] | None = None,
) -> Group:
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"invalid strategy: {strategy}")
    return _group_ref(
        name, "balancer", strategy, list(profile_ids), store,
        engine=engine, subscription_ids=subscription_ids, group_ids=group_ids,
    )


def create_chain_group(
    name: str, ordered_profile_ids: list[str], store, engine: str = AUTO,
    subscription_ids: list[str] | None = None, group_ids: list[str] | None = None,
) -> Group:
    return _group_ref(
        name, "chain", "", list(ordered_profile_ids), store,
        engine=engine, subscription_ids=subscription_ids, group_ids=group_ids,
    )


def create_single_group(name: str, profile_id: str) -> Group:
    return Group(name=name, type="single", profile_ids=[profile_id])


def rename_group(group: Group, name: str) -> Group:
    group.name = name
    return group


def add_member(group: Group, profile_id: str) -> Group:
    if profile_id not in group.profile_ids:
        group.profile_ids.append(profile_id)
    return group


def remove_member(group: Group, profile_id: str) -> Group:
    if profile_id in group.profile_ids:
        group.profile_ids.remove(profile_id)
    return group


def classify_id(store, entity_id: str) -> str | None:
    """Return the entity type of an ID: "profile", "subscription", "group", or None.

    IDs are globally unique across entity types (single counter), so the
    type can be detected by looking the ID up in the store.
    """
    if store.get_profile(entity_id) is not None:
        return "profile"
    if store.get_subscription(entity_id) is not None:
        return "subscription"
    if store.get_group(entity_id) is not None:
        return "group"
    return None


def classify_ids(store, ids: list[str]) -> tuple[list[str], list[str]]:
    """Split IDs into (profile_ids, subscription_ids), detecting the type.

    Raises ValueError for any ID that matches neither a profile nor a
    subscription. Nested-group IDs are rejected here; use ``classify_refs``
    when group members are allowed.
    """
    if not isinstance(ids, list):
        raise ValueError("ids must be a list")
    profile_ids: list[str] = []
    subscription_ids: list[str] = []
    for entity_id in ids:
        kind = classify_id(store, entity_id)
        if kind == "subscription":
            subscription_ids.append(entity_id)
        elif kind == "profile":
            profile_ids.append(entity_id)
        else:
            raise ValueError(
                f"unknown id: {entity_id} (not a profile or subscription)"
            )
    return profile_ids, subscription_ids


def classify_refs(
    store, ids: list[str]
) -> tuple[list[str], list[str], list[str]]:
    """Split IDs into (profile_ids, subscription_ids, group_ids).

    Raises ValueError for any ID that matches no known entity type.
    """
    if not isinstance(ids, list):
        raise ValueError("ids must be a list")
    profile_ids: list[str] = []
    subscription_ids: list[str] = []
    group_ids: list[str] = []
    for entity_id in ids:
        kind = classify_id(store, entity_id)
        if kind == "profile":
            profile_ids.append(entity_id)
        elif kind == "subscription":
            subscription_ids.append(entity_id)
        elif kind == "group":
            group_ids.append(entity_id)
        else:
            raise ValueError(f"unknown id: {entity_id} (not a profile, subscription, or group)")
    return profile_ids, subscription_ids, group_ids


def _resolve_subscription_profiles(store, subscription_ids: list[str]) -> list[str]:
    """Expand subscription IDs into their current profile IDs."""
    profile_ids: list[str] = []
    for sub_id in subscription_ids:
        sub = store.get_subscription(sub_id)
        if sub is None:
            raise ValueError(f"unknown subscription id: {sub_id}")
        profile_ids.extend(sub.profile_ids)
    return profile_ids


def resolve_refs(store, refs: list[str]) -> list[Profile]:
    """Resolve a mixed list of profile | subscription | group IDs into the
    deduped, ordered list of concrete profiles.

    - profile id   -> that profile
    - sub id       -> subscription's current profile_ids (dynamic)
    - group id     -> that group's members (recursive, deduped)

    Raises ValueError for unknown ids and for reference cycles.
    """
    if not isinstance(refs, list):
        raise ValueError("refs must be a list")
    seen: set[str] = set()
    result: list[Profile] = []

    def _append(profile: Profile) -> None:
        if profile.id in seen:
            return
        seen.add(profile.id)
        result.append(profile)

    def _walk(ref: str, visiting: set[str]) -> None:
        if not isinstance(ref, str) or not ref:
            raise ValueError("refs must be non-empty strings")
        profile = store.get_profile(ref)
        if profile is not None:
            _append(profile)
            return
        sub = store.get_subscription(ref)
        if sub is not None:
            for pid in sub.profile_ids:
                p = store.get_profile(pid)
                if p is not None:
                    _append(p)
                else:
                    raise ValueError(f"subscription {ref} references unknown profile {pid}")
            return
        group = store.get_group(ref)
        if group is not None:
            if ref in visiting:
                raise ValueError(f"circular group reference: {' -> '.join(visiting | {ref})}")
            # Preserve member order: profiles, subscriptions, then nested groups.
            for member_ref in (
                list(group.profile_ids)
                + list(group.subscription_ids)
                + list(group.group_ids)
            ):
                _walk(member_ref, visiting | {ref})
            return
        raise ValueError(f"unknown id: {ref} (not a profile, subscription, or group)")

    for ref in refs:
        _walk(ref, set())
    return result


def subscription_target(
    store, sub_id: str, strategy: str = "latency", engine: str = AUTO,
    default_engine: str = SINGBOX,
) -> Target:
    """Resolve a subscription into a balancer target over its current profiles."""
    sub = store.get_subscription(sub_id)
    if sub is None:
        raise ValueError(f"unknown subscription id: {sub_id}")
    profiles = resolve_refs(store, list(sub.profile_ids))
    if not profiles:
        raise ValueError(f"subscription {sub_id} has no profiles")
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"invalid strategy: {strategy}")
    resolved_engine = _resolve_group_engine(profiles, strategy, engine, default_engine)
    return Target(
        type="balancer",
        name=sub.name,
        engine=resolved_engine,
        strategy=strategy,
        profile_ids=[p.id for p in profiles],
        profiles=profiles,
    )


def resolve_outbound(store, outbound_type: str, outbound_id: str,
                     default_engine: str = SINGBOX) -> Target:
    """Resolve a server's outbound reference into a Target.

    ``outbound_type`` ∈ {profile, subscription, group, direct}. Direct
    returns an empty target (engine = default).
    """
    if outbound_type == "direct":
        return Target(type="single", engine=default_engine, profiles=[])
    if outbound_type == "profile":
        profile = store.get_profile(outbound_id)
        if profile is None:
            raise ValueError(f"unknown profile id: {outbound_id}")
        return resolve_target(store, profile, default_engine)
    if outbound_type == "subscription":
        return subscription_target(store, outbound_id, default_engine=default_engine)
    if outbound_type == "group":
        group = store.get_group(outbound_id)
        if group is None:
            raise ValueError(f"unknown group id: {outbound_id}")
        return resolve_target(store, group, default_engine)
    raise ValueError(f"unknown outbound type: {outbound_type}")


def resolve_target(store, selection, default_engine: str = SINGBOX) -> Target:
    """Resolve a Profile, Subscription, or Group into a concrete Target."""
    if isinstance(selection, Subscription):
        return subscription_target(store, selection.id, default_engine=default_engine)
    if isinstance(selection, Profile):
        return Target(
            type="single",
            name=selection.name,
            engine=resolve_engine(selection.kind, "", selection.engine, default_engine),
            profile_ids=[selection.id],
            profiles=[selection],
        )
    if isinstance(selection, Group):
        if selection.type not in ("single", "balancer", "chain"):
            raise ValueError(f"unsupported group type: {selection.type}")
        # Resolve ALL members dynamically (profiles + subs + nested groups),
        # deduped, ordered.
        refs = (
            list(selection.profile_ids)
            + list(selection.subscription_ids)
            + list(selection.group_ids)
        )
        profiles = resolve_refs(store, refs)
        if not profiles:
            raise ValueError(f"group {selection.name!r} resolves to no profiles")
        if selection.type == "single":
            if len(profiles) != 1:
                raise ValueError("a single group requires exactly 1 profile")
            strategy = ""
            target_type = "single"
        elif selection.type == "chain":
            if len(profiles) < 2:
                raise ValueError("a chain requires at least 2 profiles")
            strategy = ""
            target_type = "chain"
        else:
            if len(profiles) < 2:
                raise ValueError("a balancer requires at least 2 profiles")
            if not isinstance(selection.strategy, str) or selection.strategy not in VALID_STRATEGIES:
                raise ValueError(f"invalid strategy: {selection.strategy}")
            strategy = selection.strategy
            target_type = "balancer"
        engine = _resolve_group_engine(profiles, strategy, selection.engine, default_engine)
        return Target(
            type=target_type,
            name=selection.name,
            engine=engine,
            strategy=strategy,
            profile_ids=[p.id for p in profiles],
            profiles=profiles,
        )
    raise TypeError("selection must be a Profile, Subscription, or Group")


def enrich_target_with_routing(target: Target, routing: RoutingConfig, store) -> Target:
    """Enrich a target with profiles/groups referenced by split-routing rules.

    This ensures the engine config includes outbounds for every profile and
    group that a split-routing rule routes to, even if they aren't part of
    the main connection target.  References are resolved through the same
    universal resolution, so subscriptions and nested groups work too.
    """
    if routing.mode != "split" or not routing.rules:
        return target

    main_ids = set(target.profile_ids)
    extra_profiles_by_id: dict[str, Profile] = {
        p.id: p for p in target.extra_profiles
    }
    extra_groups_by_id: dict[str, Group] = {
        g.id: g for g in target.extra_groups
    }

    # Collect referenced target ids from routing rules.
    rule_target_ids = {
        rule.target_id
        for rule in routing.rules
        if rule.action == "proxy" and rule.target_id
    }
    rule_target_ids -= main_ids
    rule_target_ids -= set(extra_profiles_by_id)
    rule_target_ids -= set(extra_groups_by_id)
    if not rule_target_ids:
        return target

    # For each target id, resolve its full profile tree via resolve_refs.
    for tid in rule_target_ids:
        group = store.get_group(tid)
        if group is not None:
            extra_groups_by_id[tid] = group
        try:
            resolved = resolve_refs(store, [tid])
        except ValueError:
            # Unknown/dangling reference — skip; resolution at connect will
            # surface it with a clear error.
            continue
        for profile in resolved:
            if profile.id in main_ids or profile.id in extra_profiles_by_id:
                continue
            extra_profiles_by_id[profile.id] = profile

    return Target(
        type=target.type,
        name=target.name,
        engine=target.engine,
        strategy=target.strategy,
        profile_ids=target.profile_ids,
        profiles=target.profiles,
        extra_profiles=list(extra_profiles_by_id.values()),
        extra_groups=list(extra_groups_by_id.values()),
    )
