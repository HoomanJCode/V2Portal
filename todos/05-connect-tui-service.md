# Phase 05 — Connect, TUI & service on the universal model ✅

> **Superseded (historical):** the ad-hoc `connect` command and the thin
> `connector` module this phase planned were later removed — proxy connections
> are now persistent **servers** (`src/v2portal/connection.py` +
> `src/v2portal/servers.py` + `service.py`), and `resolve_ref_entity` lives in
> `src/v2portal/outbounds/groups.py`. Kept as a record of what Phase 05 delivered.

**Goal:** one `connector` code path is used by CLI connect, the TUI connect
screen, and the boot service; all accept any reference
(profile | subscription | group).

## Tasks

### 5.1 `connector` module (new, thin)

- Create `src/v2portal/connector.py`:
  - `resolve_connection(store, ref: str, controller) -> ConnectionStatus`
  - `ref` is a string id; type auto-detected; resolution via Phase-01
    `resolve_refs` / `resolve_target`; returns the connection status.
- `connection.py` keeps `ConnectionController.connect(selection)` but gains
  `connect_ref(store, ref: str)` delegating to `connector`.

### 5.2 CLI — `connect`

- Add `v2portal connect REF` subcommand (new):
  - REF auto-detected; connects until Ctrl+C / `--stop`.
  - `v2portal connect --help` documents REF = profile | subscription | group.
- `service install REF` — now accepts subscription too (validation via
  `classify_id`).

### 5.3 TUI connect screen

- `tui/app_screen.py` / `widgets.pick_profile`:
  - Include subscriptions and groups in the picker (grouped, ids shown).
  - Selection returns (kind, id); connect via `connector.resolve_connection`.
- `connection_screen` shows the resolved target name/engine as today
  (balancer name for subscriptions = sub name + strategy).

### 5.4 Tests ✅

- `tests/test_connector.py`: ref detection + controller routing.
- `connect` CLI parses ref; unknown ref errors cleanly (`_connect_command`).
- `service install` accepts SUB_ID, unit uses `connect <id>` command.
- TUI picker includes `[SUB]` entries; mocks updated to 3-arg picker.

## Exit criteria

- `pytest` green (533 passed);
  commit: `Connect by any reference (CLI/TUI/service)` ✅