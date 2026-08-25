# Phase 04 — Referential integrity ✅

**Goal:** removing any entity leaves the config consistent and resolvable;
dangling references are either pruned, re-pointed, or produce a clear error
— never a silent crash. Every `remove` prints what it pruned.

## Tasks

### 4.1 `profile remove`

- Today: storage already prunes the profile from `subscription.profile_ids`,
  `group.profile_ids`, and routing rules targeting it.
- NEW: also prune from `group.group_ids` (nested members, Phase 01).
- Print summary: `removed profile 002; pruned from 2 group(s), 1 rule(s)`.

### 4.2 `subscription remove`

- Today: unlinks `profile.subscription_id` but leaves `group.subscription_ids`
  hanging.
- NEW behavior: **delete the subscription's profiles** (they are ephemeral
  subscription artifacts — the user already confirmed "remove and its
  profiles"), then prune `group.subscription_ids` of the id.
- Keep `Server.outbound_id`? No — server would resolve to unknown. Print:
  `removed subscription 001 (3 profiles; pruned from 2 group(s), 1 server(s))`.

### 4.3 `group remove`

- Today: prunes routing rules only.
- NEW: prune from `group.group_ids` of other groups (nested), keep server
  refs (they resolve like any target), print `removed group 003 (pruned
  from group 004)`.

### 4.4 `server remove`

- Keep as-is (stops + removes + prints id).

### 4.5 Routing rules

- `routing remove` / `profile remove` already prune rule targets.
- `routing add --target REF` accepts profile | subscription | group — REF
  resolved at runtime by `enrich_target_with_routing` (Phase 01).
- `routing list` shows the target id + resolved type.

## Tasks

1. Storage `remove_profile` / `remove_subscription` / `remove_group` updates
   + counts (return a small summary dict, not just bool).
2. CLI `remove` handlers print the summary lines above.
3. `classify_id` now also knows `group`; used by every target-accepting path
   (`resolve_refs`, `server`, `routing add`).
4. Tests ✅: `subscription remove` prunes group refs + deletes profiles;
   `profile remove` prunes nested group refs; `group remove` prunes nested
   refs; remove-path summaries asserted.
   (routing `--target` already resolves subscriptions from Phase 01.)

## Exit criteria

- `pytest` green (526 passed); commit `Scope references consistently on removal` ✅