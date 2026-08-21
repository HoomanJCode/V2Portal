"""Group builders (balancer/chain/single) and target resolution."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..engines import AUTO, SINGBOX, XRAY, get_adapter, resolve_engine, strategy_supported
from ..models import Group, Profile, RoutingConfig
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


def create_balancer_group(
    name: str, strategy: str, profile_ids: list[str], store, engine: str = AUTO
) -> Group:
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"invalid strategy: {strategy}")
    if len(set(profile_ids)) < 2:
        raise ValueError("a balancer requires at least 2 profiles")
    profiles = _resolve_members(store, profile_ids)
    _assert_non_vpn(profiles)
    _resolve_group_engine(profiles, strategy, engine, SINGBOX)  # validates strategy support
    return Group(name=name, type="balancer", strategy=strategy, profile_ids=list(profile_ids), engine=engine)


def create_chain_group(
    name: str, ordered_profile_ids: list[str], store, engine: str = AUTO
) -> Group:
    if len(ordered_profile_ids) < 2:
        raise ValueError("a chain requires at least 2 profiles")
    profiles = _resolve_members(store, ordered_profile_ids)
    _assert_non_vpn(profiles)
    _resolve_group_engine(profiles, "", engine, SINGBOX)
    return Group(name=name, type="chain", profile_ids=list(ordered_profile_ids), engine=engine)


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


def resolve_target(store, selection, default_engine: str = SINGBOX) -> Target:
    """Resolve a Profile or Group into a concrete Target."""
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
        profiles = _resolve_members(store, selection.profile_ids)
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
    raise TypeError("selection must be a Profile or Group")


def enrich_target_with_routing(target: Target, routing: RoutingConfig, store) -> Target:
    """Enrich a target with profiles/groups referenced by split-routing rules.

    This ensures the engine config includes outbounds for every profile and
    group that a split-routing rule routes to, even if they aren't part of
    the main connection target.  Group members are also resolved so the
    engine can emit the required outbounds for balancers/chains.
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

    for rule in routing.rules:
        if rule.action != "proxy" or not rule.target_id:
            continue
        tid = rule.target_id
        if tid in main_ids:
            continue
        if tid in extra_profiles_by_id or tid in extra_groups_by_id:
            continue
        profile = store.get_profile(tid)
        if profile is not None:
            extra_profiles_by_id[tid] = profile
            continue
        group = store.get_group(tid)
        if group is not None:
            extra_groups_by_id[tid] = group

    # Resolve members of referenced groups so their outbounds are available.
    for group in list(extra_groups_by_id.values()):
        for pid in group.profile_ids:
            if pid in main_ids or pid in extra_profiles_by_id:
                continue
            profile = store.get_profile(pid)
            if profile is not None:
                extra_profiles_by_id[pid] = profile

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
