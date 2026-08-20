# Phase 01 — Scaffold & Config Layer

> **Status:** ✅ Implemented (commits 2de39c3 → 21447ec).

Goal: a runnable Python package skeleton plus the settings/storage layer that
everything else builds on. No proxy logic yet.

## Tasks

- [x] Create `pyproject.toml`:
  - project name `v2raycli`, version `0.1.0`, `requires-python = ">=3.10"`
  - deps: `prompt_toolkit`, `rich`, `httpx[socks]`, `platformdirs`
  - dev deps: `pytest`
  - console script `v2raycli = v2raycli.app:main`, `src/` layout
  - `[tool.pytest.ini_options]` with `pythonpath = ["src"]`, `testpaths = ["tests"]`
- [x] Create `src/v2raycli/` with `__init__.py` (`__version__`) and `__main__.py`.
- [x] `config.py`:
  - config dir via `platformdirs.user_config_dir("v2raycli")` with a stdlib
    fallback (so the package imports in minimal dev shells)
    (Linux/Termux `~/.config/v2raycli`, Windows `%APPDATA%\v2raycli`)
  - ensure dirs exist; expose `CONFIG_PATH`, `RUNTIME_DIR`, `BIN_DIR`, `GEO_DIR`,
    `BACKUP_DIR`
  - `DEFAULT_SETTINGS` per `PLAN.md §5`:
    listen `0.0.0.0`, mixed_port `1080`, allow_lan `true`,
    `inbound_auth {enabled:false, username:"", password:""}`,
    dns `["1.1.1.1","8.8.8.8"]`, log_level `info`,
    test_url `http://cp.cloudflare.com/generate_204`, default_engine `sing-box`,
    backup_keep `10`
- [x] `models.py` — dataclasses matching `PLAN.md §5`:
  - `Settings`, `Profile`, `Subscription`, `Group`, `RoutingConfig`,
    `RoutingRule`, `Config` (engine options stored as an `engines` dict;
    `vpn` inline dict on `Profile` — matches `PLAN.md §5`)
  - enums: `ProfileKind` (vmess, vless, trojan, ss, ssr, socks, http, wireguard,
    hysteria2, tuic, manual, openvpn, openconnect), `GroupType`, `Strategy`
    (latency, random, roundRobin, leastLoad), `EngineName` (sing-box, xray, auto)
  - uuid4 ids; ISO-8601 timestamps; explicit `to_dict()` / `from_dict()`
- [x] `storage.py`:
  - `load()` (creates default on first run), `save()` (atomic temp + replace),
    `schema_version` stored on read/write; unsupported versions and malformed
    nested config shapes produce a clear load error without being overwritten
  - `ConfigStore` CRUD: profiles, subscriptions (unlink `profile_ids` on remove),
    groups, routing rules, settings/engines update
  - note: the backup pre-write hook is added in Phase 09, not here
- [x] `app.py` — `main()` loads storage, prints banner + counts, exits cleanly
  (TUI lands in Phase 06).
- [x] `.gitignore`: `.venv/`, `__pycache__/`, `*.egg-info/`, `runtime/`,
  downloaded binaries and geo assets.

## Tests

- [x] `test_storage.py`: first-run default config; round-trip; atomic write;
  CRUD helpers persist; malformed schema and nested config shapes are rejected.
- [x] `test_models.py`: dict round-trip for every kind/type, defaults, ids.
- [x] `test_app.py`: `main()` runs and exits 0 in an isolated temp config dir.

## Definition of Done

- [x] `v2raycli` runs and exits 0 (verified via `tests/test_app.py`).
      `pip install -e .[dev]` was **not** run here (offline env; optional deps
      not installed) — the package is exercised via `pythonpath = ["src"]`.
- [x] `pytest` passes — 14 tests.
- [x] `config.json` created on first run with all default settings, empty
      profiles/subscriptions/groups, and `routing.mode = "all"` (verified via
      `tests/test_storage.py`).

passed
