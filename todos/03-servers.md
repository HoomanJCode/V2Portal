# Phase 03 — Servers on the universal reference model ✅

**Goal:** a server's outbound is any reference (profile | subscription |
group), resolved dynamically at start/restart time. No more `--profile` /
`--group` selector flags in the CLI.

## Tasks

### 3.1 Model & validation

- `Server.outbound_type` accepts: `profile` | `subscription` | `group` |
  `direct` (persisted `profile`/`group` unchanged; new writes may set
  `subscription`).
- `Server.outbound_id` holds the referenced id (globally unique — one field
  suffices). Keep `outbound_type` for display/back-compat.
- Storage validation accepts `subscription` as a valid `outbound_type`.

### 3.2 CLI — `server add` / `server edit`

- Replace `--profile` / `--group` flags with a single positional:
  `v2portal server add --port 1080 REF [--name X] [--protocol P] [--listen L]`
  - REF auto-detected via `classify_id` (profile | subscription | group).
  - `--direct` flag (existing) still forces `direct`; mutually exclusive
    with REF positional.
- `server edit ID [--outbound REF] [--name ...] [--port ...] ...`
  - `--outbound` auto-detects too; `--direct` clears to direct.
- `_temp_server_start` (`server start --temp`): accept `--profile/--group`
  (back-compat) AND a new positional `REF`; unify through the same helper.

### 3.3 Resolution

- `ServerManager._generate_server_config` uses the Phase-01 universal
  `resolve_outbound(store, server) -> Target` helper:
  - `subscription` → `subscription_target` (balancer at connect time).
- Add `ServerManager.resolve_target(server)` public wrapper (used by CLI
  display too — `server list` already shows `outbound_id`).

### 3.4 Running servers pick up updates

- When a server edit changes the outbound ref, the existing "restart if
  running" behavior already handles regeneration; ensure the new ref path
  stores `outbound_type="subscription"` and restarts work.

### 3.5 Tests ✅

- `server add REF` (subscription, group, profile positional).
- `server list` shows `subscription/001 (name)`.
- `resolve_outbound_target` resolves a subscription to a balancer target.
- `server edit --outbound` switches type; legacy `--profile` still parses.
- `--temp` accepts `--outbound` (legacy flags stay).

## Exit criteria

- No `--profile`/`--group` selector flags in `server add/edit` help ✅
  (kept as hidden back-compat flags).
- `pytest` green (522 passed); commit: `Point servers at universal outbound references` ✅