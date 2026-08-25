# Refactor Roadmap — Unified ID & Resource Model

> **Read `PLAN.md` first.** This index describes the full refactor backlog.
> Phases build on each other and must be executed **in numeric order**.
> Every phase ends with `pytest` green and a commit.

## Design goals (locked with the user)

1. **One universal ID space.** Profiles, subscriptions, groups, and servers
   all share one counter — an ID alone is unambiguous. Every target-ID
   argument auto-detects its type; no `--profile` vs `--group` vs
   `--subscription` flags anywhere.
2. **Dynamic graph, resolved at use time.** Any entity that *contains*
   outbounds (server, group, routing rule, connect target, service) accepts
   **profile | subscription | group** as input. At connect/start/test the
   graph is resolved recursively to concrete profiles. Subscriptions refresh
   → new profiles automatically flow through. Resolution dedups profiles.
3. **Subscription as outbound target** = strategy-based balancer over its
   current profiles (strategy configurable, default `latency`).
4. **Nested groups allowed** — groups can hold profiles + subscriptions +
   groups; resolved recursively, cycles rejected.
5. **Uniform command shape**: every resource (`profile`, `subscription`,
   `group`, `server`, `routing`) exposes the same action set — `list`,
   `add`, `edit`, `remove`, plus resource-specific actions. `add` replaces
   `create`; flags that duplicate positionals are removed; output lines
   always include IDs.

---

## Phase index

| Phase | File | What it delivers |
|---|---|---|
| 01 | `todos/01-model-core.md` | ✅ `resolve_target` v2 (any ref → profiles), `subscription_target()`, nested-group expansion, cycle detection, dedup |
| 02 | `todos/02-cmd-shape.md` | ✅ CLI rework: `group create`→`group add`, unified `edit`, `subscription edit`, aliases, per-resource help, removed legacy |
| 03 | `todos/03-servers.md` | ✅ Server outbound = universal ref (profile/sub/group), auto-detect ID in add/edit/temp, running-engine reconfig |
| 04 | `todos/04-references.md` | ✅ Referential integrity: `profile remove`, `subscription remove`, `group remove`, `server remove`, `routing` targets — refs kept/resolved/rejected consistently |
| 05 | `todos/05-connect-tui-service.md` | ✅ `connector` unification for CLI/TUI/service; subscription targets in TUI connect; per-ref tests |
| 06 | `todos/06-tests-docs.md` | ✅ Test sweep (exhaustive graph CLI flows), docs + README updates, final verification |