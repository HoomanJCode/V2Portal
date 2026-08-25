# Phase 03 — Servers on the universal reference model

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
  `v2raycli server add --port 1080 REF [--name X] [--protocol P] [--listen L]`
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

### 3.5 Tests (tests/test_servers.py, tests/test_cli_commands.py)

- `server add --outbound SUB_ID` → `outbound_type == "subscription"`.
- `server list` shows `subscription/001 (name)` (extend `_outbound_label`).
- Generated config resolves subscription profiles at start (mock binary
  path — reuse existing fake-binary test pattern).
- `server edit --outbound GROUP_ID` switches type; `--direct` clears.
- `--temp` with a subscription ref works.
- Back-compat: `server add --profile P --group G` still parses (aliases).

## Exit criteria

- No `--profile`/`--group` selector flags in `server add/edit` help.
- `pytest` green; commit `Point servers at universal outbound references`.