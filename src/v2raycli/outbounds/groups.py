"""Group builders (balancer/chain) and target resolution."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..engines import AUTO, SINGBOX, XRAY, get_adapter, resolve_engine, strategy_supported
from ..models import Group, Profile, RoutingConfig, Server, Subscription
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
    health_interval: int = 0  # seconds between engine health probes (0 = disabled)


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
    group_ids: list[str] | None = None, server_ids: list[str] | None = None,
) -> Group:
    """Shared validation/construction for balancer and chain groups.

    *refs* are the concrete profile ids; *subscription_ids* / *group_ids*
    / *server_ids* are the dynamic members that are resolved at use time
    (kept on the Group for refreshability). Servers are validated to exist
    and to not forward (transitively) back into this group.
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
    if server_ids:
        # Validate servers exist and their outbound chains stay acyclic.
        for sid in server_ids:
            if store.get_server(sid) is None:
                raise ValueError(f"unknown server id: {sid}")
            validate_server_chain(store, sid)
            if server_reaches_group(store, sid, None):
                raise ValueError(
                    f"server {sid} forwards (transitively) to a group that contains it"
                )
    if not refs and not subscription_ids and not group_ids and not server_ids:
        raise ValueError(
            "group requires at least one profile, subscription, group, or server"
        )
    # A single profile or single server is not a group-like entity.
    # Check the direct member count (before subscription expansion).
    n_direct = (
        len(refs)
        + (len(subscription_ids) if subscription_ids else 0)
        + (len(group_ids) if group_ids else 0)
        + (len(server_ids) if server_ids else 0)
    )
    if n_direct == 1:
        if refs and not subscription_ids and not group_ids and not server_ids:
            raise ValueError(
                "a single profile is not a group — add another profile or "
                "use a subscription or group as the sole member"
            )
        if server_ids and not refs and not subscription_ids and not group_ids:
            raise ValueError(
                "a single server is not a group — add another profile/server or "
                "use a subscription or group as the sole member"
            )
    profiles = resolve_refs(store, all_ids) if all_ids else []
    if server_ids:
        # Server members resolve to socks/http profiles — include them in the
        # engine-compatibility checks so a forced engine is validated.
        profiles.extend(server_profile(store, sid) for sid in server_ids)
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
        server_ids=list(server_ids) if server_ids else [],
        engine=engine,
    )


def create_balancer_group(
    name: str, strategy: str, profile_ids: list[str], store, engine: str = AUTO,
    subscription_ids: list[str] | None = None, group_ids: list[str] | None = None,
    server_ids: list[str] | None = None,
) -> Group:
    if strategy not in VALID_STRATEGIES:
        raise ValueError(f"invalid strategy: {strategy}")
    return _group_ref(
        name, "balancer", strategy, list(profile_ids), store,
        engine=engine, subscription_ids=subscription_ids, group_ids=group_ids,
        server_ids=server_ids,
    )


def create_chain_group(
    name: str, ordered_profile_ids: list[str], store, engine: str = AUTO,
    subscription_ids: list[str] | None = None, group_ids: list[str] | None = None,
    server_ids: list[str] | None = None,
) -> Group:
    return _group_ref(
        name, "chain", "", list(ordered_profile_ids), store,
        engine=engine, subscription_ids=subscription_ids, group_ids=group_ids,
        server_ids=server_ids,
    )



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
    """Return the entity type of an ID: profile|subscription|group|server, or None.

    IDs are globally unique across entity types (single counter), so the
    type can be detected by looking the ID up in the store.
    """
    if store.get_profile(entity_id) is not None:
        return "profile"
    if store.get_subscription(entity_id) is not None:
        return "subscription"
    if store.get_group(entity_id) is not None:
        return "group"
    if store.get_server(entity_id) is not None:
        return "server"
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
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Split IDs into (profile_ids, subscription_ids, group_ids, server_ids).

    Raises ValueError for any ID that matches no known entity type.
    """
    if not isinstance(ids, list):
        raise ValueError("ids must be a list")
    profile_ids: list[str] = []
    subscription_ids: list[str] = []
    group_ids: list[str] = []
    server_ids: list[str] = []
    for entity_id in ids:
        kind = classify_id(store, entity_id)
        if kind == "profile":
            profile_ids.append(entity_id)
        elif kind == "subscription":
            subscription_ids.append(entity_id)
        elif kind == "group":
            group_ids.append(entity_id)
        elif kind == "server":
            server_ids.append(entity_id)
        else:
            raise ValueError(
                f"unknown id: {entity_id} (not a profile, subscription, group, or server)"
            )
    return profile_ids, subscription_ids, group_ids, server_ids


def resolve_ref_entity(store, ref: str):
    """Return the Profile / Subscription / Group / Server for ``ref``.

    Type is auto-detected from the globally unique ID space. Raises
    ValueError for unknown ids.
    """
    if not isinstance(ref, str) or not ref:
        raise ValueError("ref must be a non-empty id string")
    kind = classify_id(store, ref)
    if kind == "profile":
        return store.get_profile(ref)
    if kind == "subscription":
        return store.get_subscription(ref)
    if kind == "group":
        return store.get_group(ref)
    if kind == "server":
        return store.get_server(ref)
    raise ValueError(
        f"unknown id: {ref} (not a profile, subscription, group, or server)"
    )


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
    """Resolve a mixed list of profile | subscription | group | server IDs
    into the deduped, ordered list of concrete profiles.

    - profile id   -> that profile
    - sub id       -> subscription's current profile_ids (dynamic)
    - group id     -> that group's members (recursive, deduped)
    - server id    -> a socks/http profile pointing at that server's local
                      inbound (traffic passes through the server; its own
                      outbound chain is loop-checked)

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
            # Preserve member order: profiles, subscriptions, groups, servers.
            for member_ref in (
                list(group.profile_ids)
                + list(group.subscription_ids)
                + list(group.group_ids)
                + list(group.server_ids)
            ):
                _walk(member_ref, visiting | {ref})
            return
        server = store.get_server(ref)
        if server is not None:
            # A server member is a leaf: a socks/http hop to its inbound.
            # Its own outbound chain is validated for server→server loops;
            # group cycles through it are rejected when the member is added.
            validate_server_chain(store, ref)
            _append(server_profile(store, ref))
            return
        raise ValueError(
            f"unknown id: {ref} (not a profile, subscription, group, or server)"
        )

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


def validate_server_chain(
    store, start_id: str, from_server_id: str | None = None
) -> None:
    """Raise ValueError if a server outbound reference loops.

    Walks server → server outbound edges (``outbound_type == "server"``)
    starting at *start_id*. Revisiting any server — including
    *from_server_id*, the server whose outbound is being configured — is a
    cycle. Also rejects forwarding a server to itself.
    """
    if not isinstance(start_id, str) or not start_id:
        raise ValueError("server reference must be a non-empty string")
    chain: list[str] = [from_server_id] if from_server_id else []
    seen: set[str] = set(chain)
    cur = start_id
    while True:
        if cur in seen:
            chain.append(cur)
            if len(chain) == 2 and chain[0] == chain[1]:
                raise ValueError(f"server {cur} cannot forward to itself")
            raise ValueError(f"circular server reference: {' -> '.join(chain)}")
        seen.add(cur)
        chain.append(cur)
        server = store.get_server(cur)
        if server is None:
            raise ValueError(f"unknown server id: {cur}")
        if server.outbound_type != "server":
            return
        cur = server.outbound_id


def server_profile(store, server_id: str, name: str | None = None) -> Profile:
    """Build a socks/http Profile that points at a server's local inbound.

    Used when a server joins a group or is added as a profile: traffic goes
    to the server's listen address/port, so it physically passes through the
    server's configured outbound ("localhost calling"). mixed → socks.
    """
    server = store.get_server(server_id)
    if server is None:
        raise ValueError(f"unknown server id: {server_id}")
    kind = "http" if server.protocol == "http" else "socks"  # mixed → socks
    entry: dict = {"address": server.listen, "port": server.port}
    auth = server.auth or {}
    if auth.get("enabled") and auth.get("username") and auth.get("password"):
        entry["users"] = [{"user": auth["username"], "pass": auth["password"]}]
    return Profile(
        id=server.id,
        name=name or server.name or server.id,
        kind=kind,
        engine=AUTO,
        outbound={"settings": {"servers": [entry]}},
    )


def server_reaches_group(store, server_id: str, group_id: str | None) -> bool:
    """True if a server's outbound chain reaches *group_id* (or any group).

    Walks server → server outbound edges and, for every group hop, the
    group's nested ``group_ids`` closure. Passing ``group_id=None`` checks
    for any group that already contains the server (a self-containing
    group); passing an id checks whether the chain reaches that exact
    group. Cycle-guarded, so it never loops on malformed configs.
    """
    seen_servers: set[str] = set()
    seen_groups: set[str] = set()
    cur = server_id
    while True:
        if cur in seen_servers:
            return False  # server chain cycles are rejected elsewhere
        seen_servers.add(cur)
        server = store.get_server(cur)
        if server is None:
            return False
        if server.outbound_type == "server":
            cur = server.outbound_id
            continue
        if server.outbound_type == "group":
            # Walk the group's nested-group closure looking for group_id (or
            # any group containing this server when group_id is None).
            stack = [server.outbound_id]
            while stack:
                gid = stack.pop()
                if gid in seen_groups:
                    continue
                seen_groups.add(gid)
                group = store.get_group(gid)
                if group is None:
                    continue
                if group_id is not None and gid == group_id:
                    return True
                if group_id is None and server_id in group.server_ids:
                    return True
                stack.extend(group.group_ids)
            return False
        return False


def server_outbound_target(
    store, server_id: str, default_engine: str = SINGBOX,
    from_server_id: str | None = None,
) -> Target:
    """Build a single-hop Target that forwards to another server's inbound.

    The target is a socks/http outbound pointing at the referenced server's
    listen address and port, so traffic physically passes through that server.
    The referenced server's own outbound chain is validated for loops.
    """
    validate_server_chain(store, server_id, from_server_id=from_server_id)
    server = store.get_server(server_id)
    assert server is not None  # validate_server_chain raises for unknown ids
    profile = server_profile(store, server_id)
    return Target(
        type="single",
        name=server.name or server.id,
        engine=default_engine,
        profile_ids=[server.id],
        profiles=[profile],
    )


def resolve_outbound(store, outbound_type: str, outbound_id: str,
                     default_engine: str = SINGBOX,
                     from_server_id: str | None = None) -> Target:
    """Resolve a server's outbound reference into a Target.

    ``outbound_type`` ∈ {profile, subscription, group, server, direct}.
    Direct returns an empty target (engine = default); server returns a
    socks/http hop to that server's inbound (loop-checked via
    *from_server_id*, the server being configured).
    """
    if outbound_type == "direct":
        return Target(type="single", engine=default_engine, profiles=[])
    if outbound_type == "server":
        return server_outbound_target(
            store, outbound_id, default_engine, from_server_id=from_server_id
        )
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
    """Resolve a Profile, Subscription, Group, or Server into a Target."""
    if isinstance(selection, Subscription):
        return subscription_target(store, selection.id, default_engine=default_engine)
    if isinstance(selection, Server):
        return server_outbound_target(store, selection.id, default_engine)
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
            + list(selection.server_ids)
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
            if len(profiles) < 1:
                raise ValueError("a chain requires at least 1 profile")
            strategy = ""
            target_type = "chain"
        else:
            if len(profiles) < 1:
                raise ValueError("a balancer requires at least 1 profile")
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
    raise TypeError("selection must be a Profile, Subscription, Group, or Server")


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


# -- hierarchy tree ----------------------------------------------------------

TREE_BRANCH = "├── "
TREE_LAST = "└── "
TREE_PIPE = "│   "
TREE_SPACE = "    "


def _tree_label_group(g: Group) -> str:
    suffix = f" ({g.strategy})" if g.type == "balancer" else ""
    return f"{g.id}  {g.type} {g.name}{suffix}"


def _tree_label_subscription(s: Subscription) -> str:
    return f"{s.id}  subscription {s.name} ({len(s.profile_ids)} profiles)"


def _tree_label_server(store, server_id: str) -> str:
    sv = store.get_server(server_id)
    if sv is None:
        return f"{server_id}  <missing server>"
    label = f"{sv.id}  server {sv.name or sv.id} :{sv.port}"
    if sv.outbound_type != "direct" and sv.outbound_id:
        label += f"  → {sv.outbound_type}/{sv.outbound_id}"
    return label


def _tree_label_profile(store, profile_id: str) -> str:
    p = store.get_profile(profile_id)
    if p is None:
        return f"{profile_id}  <missing profile>"
    return f"{p.id}  {p.kind} {p.name}"


def _tree_render_member_refs(store, refs: list[str], prefix: str, lines: list[str], visited: set[str]) -> None:
    """Render a list of mixed refs (profile|subscription|server|group)."""
    for index, ref in enumerate(refs):
        branch = TREE_LAST if index == len(refs) - 1 else TREE_BRANCH
        child_prefix = prefix + (TREE_SPACE if index == len(refs) - 1 else TREE_PIPE)
        group = store.get_group(ref)
        if group is not None:
            _tree_render_group(store, group, prefix, index == len(refs) - 1, lines, visited)
            continue
        sub = store.get_subscription(ref)
        if sub is not None:
            lines.append(prefix + branch + _tree_label_subscription(sub))
            _tree_render_member_refs(store, list(sub.profile_ids), child_prefix, lines, visited)
            continue
        sv = store.get_server(ref)
        if sv is not None:
            lines.append(prefix + branch + _tree_label_server(store, ref))
            continue
        p = store.get_profile(ref)
        if p is not None:
            lines.append(prefix + branch + _tree_label_profile(store, ref))
            continue
        lines.append(prefix + branch + f"{ref}  <missing>")


def _tree_render_group(
    store, group: Group, prefix: str, is_last: bool, lines: list[str], visited: set[str]
) -> None:
    branch = TREE_LAST if is_last else TREE_BRANCH
    child_prefix = prefix + (TREE_SPACE if is_last else TREE_PIPE)
    lines.append(prefix + branch + _tree_label_group(group))
    if group.id in visited:
        lines.append(child_prefix + TREE_LAST + "(cycle — not expanded)")
        return
    visited = visited | {group.id}
    refs = (
        list(group.profile_ids)
        + list(group.subscription_ids)
        + list(group.server_ids)
        + list(group.group_ids)
    )
    _tree_render_member_refs(store, refs, child_prefix, lines, visited)


def group_tree_lines(store) -> list[str]:
    """Render the nested group / subscription / server hierarchy as text lines.

    Roots are the top-level groups (groups not nested inside another group)
    followed by any subscription / server / profile that no group references,
    so nothing is hidden. Members are expanded recursively: a subscription
    shows its current profiles, a server shows its local inbound (and its
    outbound reference as a hint). Group cycles — possible only in
    hand-edited configs — are truncated and marked.
    """
    groups = store.list_groups()
    subs = store.list_subscriptions()
    servers = store.list_servers()
    profiles = store.list_profiles()

    contained_groups: set[str] = set()
    referenced_subs: set[str] = set()
    referenced_servers: set[str] = set()
    referenced_profiles: set[str] = set()
    sub_profiles: set[str] = set()
    for group in groups:
        contained_groups.update(group.group_ids)
        referenced_subs.update(group.subscription_ids)
        referenced_servers.update(group.server_ids)
        referenced_profiles.update(group.profile_ids)
    for sub in subs:
        sub_profiles.update(sub.profile_ids)

    roots: list[str] = [g.id for g in groups if g.id not in contained_groups]
    roots += [s.id for s in subs if s.id not in referenced_subs]
    roots += [sv.id for sv in servers if sv.id not in referenced_servers]
    roots += [
        p.id
        for p in profiles
        if p.id not in referenced_profiles and p.id not in sub_profiles
    ]

    lines: list[str] = []
    visited: set[str] = set()
    _tree_render_member_refs(store, roots, "", lines, visited)
    return lines
