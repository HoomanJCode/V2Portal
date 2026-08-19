# Phase 01 — Scaffold & Config Layer

Goal: a runnable Python package skeleton plus the settings/storage layer that
everything else builds on. No proxy logic yet.

## Tasks

- [ ] Create `pyproject.toml`:
  - project name `v2raycli`, version `0.1.0`, `requires-python = ">=3.10"`
  - deps: `prompt_toolkit`, `rich`, `httpx[socks]`, `platformdirs`
  - dev deps: `pytest`
  - console script `v2raycli = v2raycli.app:main`, `src/` layout
- [ ] Create `src/v2raycli/` with `__init__.py` (`__version__`) and `__main__.py`.
- [ ] `config.py`:
  - config dir via `platformdirs.user_config_dir("v2raycli")`
    (Linux/Termux `~/.config/v2raycli`, Windows `%APPDATA%\v2raycli`)
  - ensure dirs exist; expose `CONFIG_PATH`, `RUNTIME_DIR`, `BIN_DIR`, `GEO_DIR`,
    `BACKUP_DIR`
  - `DEFAULT_SETTINGS` per `PLAN.md §5`:
    listen `0.0.0.0`, mixed_port `1080`, allow_lan `true`,
    `inbound_auth {enabled:false, username:"", password:""}`,
    dns `["1.1.1.1","8.8.8.8"]`, log_level `info`,
    test_url `http://cp.cloudflare.com/generate_204`, default_engine `sing-box`,
    backup_keep `10`
- [ ] `models.py` — dataclasses matching `PLAN.md §5`:
  - `Settings`, `EngineOptions` (per-engine binary/version), `Profile`,
    `Subscription`, `Group`, `RoutingConfig`, `RoutingRule`, `VpnConfig`
  - enums: `ProfileKind` (vmess, vless, trojan, ss, ssr, socks, http, wireguard,
    hysteria2, tuic, manual, openvpn, openconnect), `GroupType`, `Strategy`
    (latency, random, roundRobin, leastLoad), `EngineName` (sing-box, xray, auto)
  - uuid4 ids; ISO-8601 timestamps; explicit `to_dict()` / `from_dict()`
- [ ] `storage.py`:
  - `load()` (creates default on first run), `save()` (atomic temp + replace),
    `schema_version` check/warning; `save()` exposes a pre-write hook used by
    the backup layer in Phase 09
  - `ConfigStore` CRUD: profiles, subscriptions (unlink `profile_ids` on remove),
    groups, routing rules, settings/engines update
- [ ] `app.py` — `main()` loads storage, prints banner + counts, exits cleanly
  (TUI lands in Phase 06).
- [ ] `.gitignore`: `.venv/`, `__pycache__/`, `*.egg-info/`, `runtime/`,
  downloaded binaries and geo assets.

## Tests

- [ ] `test_storage.py`: first-run default config; round-trip; atomic write;
  CRUD helpers persist.
- [ ] `test_models.py`: dict round-trip for every kind/type, defaults, ids.

## Definition of Done

- [ ] `pip install -e .[dev]` works; `v2raycli` runs and exits 0.
- [ ] `pytest` passes.
- [ ] `config.json` created on first run with all default settings, empty
      profiles/subscriptions/groups, and `routing.mode = "all"`.
