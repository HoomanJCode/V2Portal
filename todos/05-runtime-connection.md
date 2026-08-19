# Phase 05 — Runtime & Connection Lifecycle

Goal: run the chosen engine (or VPN client) as a managed subprocess, expose the
LAN-facing mixed inbound, and give upper layers a clean status/log interface.

## Tasks

- [ ] `runner.py` — generic `Proc` helper:
  - `start(argv)` (no shell; `CREATE_NO_WINDOW` on Windows), `stop()`
    (graceful then kill, no orphans), `is_running()`, `pid`, `wait()`.
- [ ] `ConnectionController`:
  - `connect(target)` → `resolve_engine` → `generate` → `write_runtime_config` →
    `validate_config` → start; return `ConnectionStatus`
  - `switch(target)` (regenerate + restart), `disconnect()`.
  - status: `{ state, target_name, engine, inbound {listen, mixed_port,
    urls, auth}, pid, started_at, error }`.
- [ ] `connect_vpn(profile)` for `kind ∈ {openvpn, openconnect}`:
  - locate client (`shutil.which`), build argv from `vpn.config_path/server/args`
  - start in foreground-but-managed mode; no inbound server; status reflects the
    VPN being up and that OS routing is owned by the client (not the CLI).
- [ ] LAN helpers: detect local IPs; include `lan://<ip>:<port>` hint + auth in
      status for other devices.
- [ ] Log parsing: structured events per engine (sing-box/xray log formats).
- [ ] Traffic stats (stretch, seam now): sing-box `experimental.clash_api` or
      xray api/stats; return `null` if disabled so TUI degrades cleanly.
- [ ] Typed errors: binary missing, VPN client missing, port in use, invalid
      config, immediate exit.

## Tests

- [ ] `test_runner.py`: fake `sing-box`/`xray` scripts (print then sleep) —
      start/stop/status, no leftover processes.
- [ ] `test_controller.py`: connect→switch→disconnect calls expected
      adapter/runner methods (mocked); port-in-use and missing-binary mapped.
- [ ] `test_vpn_connect.py`: argv building for openvpn/openconnect (mocked
      client, no real connection).

## Definition of Done

- [ ] A `kind=socks` profile connects end-to-end from the Python API, and
      `curl -x http://<lan-ip>:1080` from another machine routes through it.
- [ ] `kind=openvpn` profile launches the (mock) client with correct argv.
- [ ] Clean shutdown on Ctrl+C; no zombie processes.
- [ ] `pytest` passes.
