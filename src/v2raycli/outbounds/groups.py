"""Group builders (balancer/chain/single) and target resolution."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..engines import AUTO, SINGBOX, XRAY, get_adapter, resolve_engine, strategy_supported
from ..models import Group, Profile
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


def _resolve_members(store, profile_ids) -> list[Profile]:
    profiles: list[Profile] = []
    for pid in profile_ids:
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
        profiles = _resolve_members(store, selection.profile_ids)
        if selection.type == "chain":
            engine = _resolve_group_engine(profiles, "", selection.engine, default_engine)
            return Target(
                type="chain",
                name=selection.name,
                engine=engine,
                profile_ids=[p.id for p in profiles],
                profiles=profiles,
            )
        target_type = "single" if selection.type == "single" else "balancer"
        strategy = selection.strategy if target_type == "balancer" else ""
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
