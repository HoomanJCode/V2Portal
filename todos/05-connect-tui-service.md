# Phase 05 — Connect, TUI & service on the universal model

**Goal:** one `connector` code path is used by CLI connect, the TUI connect
screen, and the boot service; all accept any reference
(profile | subscription | group).

## Tasks

### 5.1 `connector` module (new, thin)

- Create `src/v2raycli/connector.py`:
  - `resolve_connection(store, ref: str, controller) -> ConnectionStatus`
  - `ref` is a string id; type auto-detected; resolution via Phase-01
    `resolve_refs` / `resolve_target`; returns the connection status.
- `connection.py` keeps `ConnectionController.connect(selection)` but gains
  `connect_ref(store, ref: str)` delegating to `connector`.

### 5.2 CLI — `connect`

- Add `v2raycli connect REF` subcommand (new):
  - REF auto-detected; connects until Ctrl+C / `--stop`.
  - `v2raycli connect --help` documents REF = profile | subscription | group.
- `service install REF` — now accepts subscription too (validation via
  `classify_id`).

### 5.3 TUI connect screen

- `tui/app_screen.py` / `widgets.pick_profile`:
  - Include subscriptions and groups in the picker (grouped, ids shown).
  - Selection returns (kind, id); connect via `connector.resolve_connection`.
- `connection_screen` shows the resolved target name/engine as today
  (balancer name for subscriptions = sub name + strategy).

### 5.4 Tests

- `connect` ref resolution (unit-level; no real engine — mock
  `ConnectionController` / binary).
- TUI picker includes sub/group entries (`tests/test_tui_widgets.py`).
- `service install SUB_ID` accepts, `service install UNKNOWN` rejects.
- `connector` resolves sub→balancer, group→nested, profile→single.

## Exit criteria

- `pytest` green; commit `Connect by any reference (CLI/TUI/service)`.