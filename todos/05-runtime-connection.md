# Phase 05 — Runtime & Connection Lifecycle

> **Status:** ✅ Implemented (commits 27983e5 → b379621).
> ✅ LAN inbound verified live: sing-box mixed inbound served HTTP + SOCKS5 on one port (curl through both).

Goal: run the chosen engine (or VPN client) as a managed subprocess, expose the
LAN-facing mixed inbound, and give upper layers a clean status/log interface.

## Tasks

- [x] `runner.py` — generic `Proc` helper:
  - `start(argv)` (no shell; `CREATE_NO_WINDOW` on Windows), `stop()`
    (graceful then kill, race-safe and no orphans), `is_running()`, `pid`, `wait()`.
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
- [x] Traffic stats (stretch): sing-box Clash API counters are polled by the
      controller, displayed in the live TUI status, and accumulated on
      disconnect; xray/VPN connections and malformed API or persisted counters
      degrade cleanly when unavailable.
- [x] Typed errors: binary missing, VPN client/target missing, stale targets,
      subprocess launch failures, port in use (engine immediate exit), invalid config.

## Tests

- [x] `test_runner.py`: fake script — start/stop/status, log capture, no
      leftover processes.
- [x] `test_controller.py`: connect→switch→disconnect calls expected
      adapter/runner methods (mocked binary); missing-binary and immediate-exit
      mapped to error status.
- [x] `test_vpn_connect.py`: argv building for openvpn/openconnect (mocked
      client, no real connection).

## Definition of Done

- [x] A generated config routes end-to-end: sing-box mixed inbound served
      HTTP (plain + CONNECT) and SOCKS5 on one port, verified live against a
      `direct` egress (proxy → engine → internet).
- [x] `kind=openvpn` profile launches the (mock) client with correct argv.
- [x] Clean shutdown on Ctrl+C; no zombie processes (verified with mock).
- [x] `pytest` passes — 112 tests.
