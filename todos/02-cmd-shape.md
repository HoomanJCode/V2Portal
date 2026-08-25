# Phase 02 — Uniform command structure

**Goal:** every resource has the same action verbs and the same options.
`add` is the universal create verb; `edit` exists for every resource; target
IDs are positional and auto-detected everywhere.

## The standard shape

```
v2raycli <resource> list [--json] [filters]
v2raycli <resource> add   <...args> [options]
v2raycli <resource> edit  ID [--name ...] [--fields...]
v2raycli <resource> remove ID
```

- `resource` ∈ {profile, subscription, group, server, routing(rule)}.
- Every `remove` accepts the id positionally and prints the removed id.
- Every `list` shows ids (already largely true).
- Target references are **positional** and auto-detected via `classify_id`
  (profile | subscription | group | server — extended in Phase 01/03).
- No `--profile` / `--group` / `--subscription` flags remain as *selectors*
  for targets; they may remain as *filters* (`profile list --subscription`).

## Tasks

### 2.1 `group add` replaces `group create`

- Rename subcommand `create` → `add`, keep `create` as a hidden alias so old
  muscle memory/scripts keep working (deprecate in help text).
- `group add single NAME PROFILE_ID` (new; wraps 1 profile).
- `group add balancer NAME REF... [--strategy S] [--engine E]`
- `group add chain NAME REF... [--engine E]`
- REF is auto-detected (profile | subscription | group). All positionals.
- Remove `--subscription` flag from balancer/chain (covered by auto-detect).
- Help examples updated to the new form.

### 2.2 Uniform `edit`

- `profile edit` — already exists; expand fields: `--name`, `--host`,
  `--port`, `--username`, `--password`, `--enabled` (new), `--engine` (new
  for supported kinds), and `--move-to-subscription SUB_ID` (re-link) —
  keep it minimal; the point is the *shape*, not a field explosion.
- `group edit <id> --name ... --strategy ... --engine ... --enabled ...`
  (new).
- `subscription edit <id> --name ... --url ... --user-agent ... --proxy ...
  --auto-update-days ... --enabled ...` (new).
- `server edit` — already exists; add `--outbound REF` (auto-detected single
  positional-like flag since `--target` conflicts with existing `--profile/
  --group`; Phase 3 replaces the flags entirely).
- `routing` rules: add `--enabled` toggle to `routing edit` (new) — or reuse
  existing enable/disable; document both.

### 2.3 `subscription` parity

- `subscription rename <id> <name>` (new; mirrors `profile rename`).
- `subscription update` stays (special resource action).
- `subscription list --expired/--expiring` filters (new, thin) optional.

### 2.4 Aliases & deprecation

- `group create` → alias of `group add`.
- `server sv` alias already exists.
- `subscription sub` alias already exists.
- `group remove-sub`/`add-sub`: keep but the help says "deprecated — use
  `add-member`/`remove-member`".
- `profile add share` / `profile add raw` keep (type sub-parsers are fine).

### 2.5 Help text & docs pass

- Every command's `--help` shows the uniform verbs and auto-detected ID
  rules.
- README command reference updated.

## Exit criteria

- All existing tests updated to new verbs (aliases keep old tests passing).
- New tests: `group add` from CLI; `subscription edit`; `group edit`; auto-
  detected REF in `group add`; help shows examples.
- `pytest` green; commit `Unify resource command shape (add/edit/remove)`.