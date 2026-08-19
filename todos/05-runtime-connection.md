# Phase 05 — Runtime & Connection Lifecycle

Goal: actually run xray as a managed subprocess, expose the LAN-facing mixed
inbound, and give the upper layers a clean status/log/traffic interface.

## Tasks

- [ ] `xray/runner.py` — `Runner` class:
  - `start(config_path)` → spawn `xray run -config <path>` with stdout/stderr
    piped (no shell), `CREATE_NO_WINDOW` on Windows
  - `stop()` → terminate on POSIX / `taskkill`-free terminate on Windows,
    with a graceful-then-kill escalation and no orphaned processes
  - `is_running()`, `pid`, `wait(timeout)`
  - `stream_logs()` → parse xray log lines into structured events
    (level, message); handle the log format changes across xray versions
- [ ] `ConnectionController` (new module, e.g. `app/connection.py` or
      `xray/controller.py`):
  - `connect(target)` → `config_gen.generate` + `write_runtime_config` +
    `validate_config` + `runner.start`; return a `ConnectionStatus`
  - `switch(target)` → regenerate + restart (stop, then start)
  - `disconnect()` → stop and mark idle
  - status object: `{ state: idle|connecting|connected|error, target_name,
    inbound: {listen, mixed_port, urls:["socks5://0.0.0.0:1080","http://0.0.0.0:1080"]},
    pid, started_at, error }`
- [ ] LAN helpers: detect local LAN IPs (e.g. via `socket`/`netifaces`-free
      approach) and include a `lan://<ip>:<port>` hint in the status so users
      can copy the address for other devices.
- [ ] Traffic stats (stretch, but wire the seam now): an `api`-inbound +
      `stats`/`policy` config knob and a `get_stats()` that reports up/down
      bytes per outbound; if skipped, return `null` so the TUI degrades cleanly.
- [ ] Handle the common failure modes into typed errors: binary missing,
      port already in use, invalid config, xray exits immediately.

## Tests

- [ ] `test_runner.py`: with a fake `xray` script on `PATH` (prints then sleeps),
      assert start/stop/status transitions and no leftover processes.
- [ ] `test_controller.py`: connect→switch→disconnect sequence calls the
      expected generator/runner methods (mocked); port-in-use error mapped.

## Definition of Done

- [ ] A manually created `Profile(kind="socks")` can be connected to end-to-end
      from the Python API (not the TUI yet), and `curl -x http://<lan-ip>:1080`
      from another machine routes through it.
- [ ] Clean shutdown on Ctrl+C and no zombie xray processes.
- [ ] `pytest` passes.
