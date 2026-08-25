# Phase 06 — Test sweep, docs & final verification

**Goal:** prove the whole refactor with a comprehensive test pass and
document the new uniform model.

## Tasks

### 6.1 Exhaustive graph flow tests (tests/test_graph_flows.py, new)

Write scenario tests that exercise the *entire* lifecycle on one store:

1. subscription → add (2 nodes) → `group add balancer` (refs: profile +
   subscription + group nested) → server pointing at the group.
2. Update the subscription (add 1 node, remove 1) → same server/group still
   resolves; dedup keeps no stale profiles; `server list`/`group list` show
   current counts.
3. Rename / edit every resource type; verify persistent and JSON output.
4. Remove a nested group → parent group resolves without it; remove a
   subscription → refs pruned everywhere.
5. `connect`/`service install` accept all three ref types (mocked engine).
6. Cycle in groups (`a→b→a`) rejected by create AND by resolve.

### 6.2 CLI surface parity check (tests/test_cli_surface.py, new)

- Table-driven test that every resource exposes: `list`, `add`, `edit`,
  `remove` (and that `--help` exits 0 and shows examples).
- No `--profile`/`--group`/`--subscription` *selector* flags remain in
  `server add/edit` / `group add` help (scan help text in test).

### 6.3 Docs

- `PLAN.md`: new data-model section — universal id space, dynamic graph
  resolution, subscription-as-target rule, nested groups, uniform command
  shape.
- `README.md`: rewrite command reference table (uniform verbs), the
  "references" concept, examples: server/group/connect by any id,
  subscription-as-balancer.
- `todos.md` (root checklist): mark the whole refactor done with a summary
  of what changed.

### 6.4 Final verification

- `pytest` full suite green.
- Manual smoke: `v2raycli group add`, `v2raycli server add --port 1080
  <subid>`, `v2raycli connect <subid>` (temp), `v2raycli subscription edit`,
  TUI connect picker shows subs/groups.
- Commit: `Refactor: universal id model, dynamic resolution, uniform CLI`.

## Exit criteria

- Everything above, committed; suite green; README/PLAN updated.
- The refactor is user-visible only as: simpler commands, more acceptance
  of ids everywhere, dynamic servers/groups, no per-purpose flags.