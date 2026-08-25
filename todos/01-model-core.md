# Phase 01 — Universal target resolution core ✅

**Goal:** one function resolves *any* reference (profile | subscription |
group) into the concrete profile list at use time — dynamic, deduped,
cycle-safe. This is the foundation every other phase builds on.

## Context

- `outbounds/groups.py` today has `resolve_target(store, selection, default_engine)`
  that only handles `Profile | Group` and expands only `group.subscription_ids`.
- `ServerManager._generate_server_config` and `connection.py` hand-roll
  profile-vs-group branching — this must become one call.
- IDs are globally unique (single counter), so lookups are unambiguous.

## Tasks

### 1.1 Resolution engine (profile-first, deduped)

Add to `outbounds/groups.py`:

```
def resolve_refs(store, refs: list[str]) -> list[Profile]:
    """Resolve a mixed list of profile | subscription | group IDs into the
    deduped, ordered list of concrete profiles.

    - profile id  -> that profile
    - sub id      -> subscription's current profile_ids (dynamic)
    - group id    -> that group's members (recursive, deduped)
    Raises ValueError for unknown ids and for reference cycles.
    """
```

Behavior details:

- Iterate refs **in order**; dedup by `profile.id` while preserving first-seen
  order (user: "filter dups").
- Group → profiles where group members are resolved via the *same* recursive
  routine. Groups expand `profile_ids` + `subscription_ids` (dynamic) +
  `group_ids` (new in Phase 01).
- Cycle detection: maintain a `visiting` set of group ids; raise
  `ValueError("circular group reference: ...")` on revisit.
- Unknown id raises `ValueError("unknown id: {id} (not a profile, subscription, or group)")`.

### 1.2 Subscription-as-target resolution

```
def subscription_target(store, sub_id: str, strategy: str = "latency",
                        engine: str = AUTO) -> Target
```

- Profiles = subscription's current `profile_ids` resolved to `Profile`.
- `Target.type = "balancer"`; `strategy` per the passed value (default
  `latency`).
- Engine resolved via existing `_resolve_group_engine` (leastLoad→xray etc).
- 0 profiles at resolve time → `ValueError("subscription {id} has no profiles")`.
- 1 profile still allowed (balancer over 1 = that profile; engines handle it).

### 1.3 `resolve_target` v2 switch

- `resolve_target(store, selection, default_engine)` accepts:
  - `Profile` → single (unchanged)
  - `Subscription` → `subscription_target`
  - `Group` → expand via `resolve_refs` (nested groups included),
    then existing balancer/chain/single logic; `subscription_ids` still
    honored (now redundant but harmless).
- Keep `enrich_target_with_routing` signature; have it resolve its referenced
  target ids via `resolve_refs` so a routing rule pointing at a *subscription*
  contributes the right profiles.
- `extra_groups` expansion: use `resolve_refs` per group so nested groups in
  routing targets work.

### 1.4 Server outbound resolution helper

```
def resolve_outbound(store, server) -> Target
```

- `server.outbound_type` in {profile, group} maps to id lookup; `subscription`
  → `subscription_target`; `direct` → target with no profiles.
- Actually: standalone helper (or fold into `resolve_target` by constructing
  the model-wrapped selection). Phase 3 wires servers onto it; for now add a
  thin helper so Phase 3 is trivial.

### 1.5 Tests (tests/test_groups.py, new tests/test_resolve_refs.py) ✅

- `resolve_refs` mixed (profile+sub+group), dedup in-place. ✅
- subscription → `subscription_target` balancer; strategy honored; no-profiles error. ✅
- nested group: balancer > group > profiles; dedup across branches. ✅
- cycle: `a→b→a` → ValueError circular. ✅
- `resolve_target` with a `Subscription` model → balancer target. ✅
- routing enrichment with a subscription target id resolves its profiles. ✅

## Exit criteria

- `pytest` green ✅ (511 passed).
- Commit: `Add universal ref resolution for profiles/subscriptions/groups` ✅