# Phase 05 — Runtime & Connection Lifecycle

> **Status:** ✅ Implemented (commits 27983e5 → b379621).
> End-to-end LAN curl check is deferred — needs a real engine binary.

Goal: run the chosen engine (or VPN client) as a managed subprocess, expose the
LAN-facing mixed inbound, and give upper layers a clean status/log interface.

## Tasks

- [x] `runner.py` — generic `Proc` helper:
  - `start(argv)` (no shell; `CREATE_NO_WINDOW` on Windows), `stop()`
    (graceful then kill, no orphans), `is_running()`, `pid`, `wait()`.
  - plus background log capture (`logs()`, `wait_for_log()`).
- [x] `ConnectionController` (`connection.py`):
  - `connect(target)` → `resolve_engine` → `generate` → `write_runtime_config` →
    `validate_config` → start; return `ConnectionStatus`
  - `switch(target)` (regenerate + restart), `disconnect()`.
  - status: `{ state, target_name, engine, inbound {listen, mixed_port, urls, auth},
    pid, started_at, error }`.
- [x] `connect_vpn(profile)` for `kind ∈ {openvpn, openconnect}`:
  - locate client (`shutil.which`), build argv from `vpn.config_path/server/args`
  - start in foreground-but-managed mode; no inbound server; status reflects the
    VPN being up (OS routing is owned by the client, not the CLI).
- [x] LAN helpers: detect local IPs; include `lan://<ip>:<port>` hint + auth in
      status.
- [x] Log parsing: `Proc` captures lines for both engines (structured parsing
      into engine events is left to the TUI/status layer).
- [x] Traffic stats (stretch, seam now): **not implemented** — status exposes
      `pid`/`started_at`; the stats API is deferred (TUI will degrade cleanly).
- [x] Typed errors: binary missing, VPN client missing, port in use (engine
      immediate exit), invalid config.

## Tests

- [x] `test_runner.py`: fake script — start/stop/status, log capture, no
      leftover processes.
- [x] `test_controller.py`: connect→switch→disconnect calls expected
      adapter/runner methods (mocked binary); missing-binary and immediate-exit
      mapped to error status.
- [x] `test_vpn_connect.py`: argv building for openvpn/openconnect (mocked
      client, no real connection).

## Definition of Done

- [ ] A `kind=socks` profile connects end-to-end from the Python API, and
      `curl -x http://<lan-ip>:1080` from another machine routes through it —
      **deferred** (no engine binary offline).
- [x] `kind=openvpn` profile launches the (mock) client with correct argv.
- [x] Clean shutdown on Ctrl+C; no zombie processes (verified with mock).
- [x] `pytest` passes — 79 tests.
