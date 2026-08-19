# Phase 01 — Scaffold & Config Layer

Goal: a runnable Python package skeleton plus the settings/storage layer that
everything else builds on. No proxy logic yet.

## Tasks

- [ ] Create `pyproject.toml` with:
  - project name `v2raycli`, version `0.1.0`, `requires-python = ">=3.10"`
  - dependencies: `prompt_toolkit`, `rich`, `httpx[socks]`, `platformdirs`
  - dev dependencies: `pytest`
  - console script entry point `v2raycli = v2raycli.app:main`
  - package config pointing at `src/` layout
- [ ] Create `src/v2raycli/` package with `__init__.py` (expose `__version__`)
  and `__main__.py` (`python -m v2raycli` → `app.main`).
- [ ] `config.py`:
  - resolve the config directory via `platformdirs.user_config_dir("v2raycli")`
    (Linux/Termux → `~/.config/v2raycli`, Windows → `%APPDATA%\v2raycli`)
  - ensure the dir exists; expose `CONFIG_PATH`, `RUNTIME_DIR`, `BIN_DIR`
  - define `DEFAULT_SETTINGS` (listen `0.0.0.0`, mixed_port `1080`,
    allow_lan `true`, dns `["1.1.1.1","8.8.8.8"]`, log_level `info`,
    test_url `http://cp.cloudflare.com/generate_204`)
- [ ] `models.py` — dataclasses matching `PLAN.md §4`:
  - `Settings`, `XrayOptions`, `Profile`, `Subscription`, `Group`
  - use `uuid4` default ids; `created_at`/`updated_at` ISO-8601 helpers
  - `ProfileKind` and `GroupType`/`Strategy` enums
  - `to_dict()` / `from_dict()` on each (explicit, no magic serialization)
- [ ] `storage.py`:
  - `load()` → creates a default config on first run; tolerates a missing file
  - `save(config)` → atomic write (temp file + `os.replace`)
  - `schema_version` field with a check/warning if newer than supported
  - in-memory `ConfigStore` wrapper with CRUD helpers:
    `add_profile`, `get_profile`, `list_profiles`,
    `add_subscription`, `remove_subscription` (also unlinks its `profile_ids`),
    `add_group`, `list_groups`, `update_settings`
- [ ] `app.py` — `main()` that loads storage, prints a banner + counts
  (profiles/subscriptions/groups), and exits cleanly (placeholder for the TUI
  that lands in Phase 06).
- [ ] Add `.gitignore` (`.venv/`, `__pycache__/`, `*.egg-info/`, `runtime/`,
  downloaded binaries).

## Tests (`tests/`)

- [ ] `test_storage.py`: first-run default config; round-trip save/load;
  atomic write leaves no temp file; CRUD helpers mutate and persist.
- [ ] `test_models.py`: dict round-trip preserves all fields; default ids.

## Definition of Done

- [ ] `pip install -e .[dev]` succeeds; `v2raycli` runs and exits 0.
- [ ] `pytest` passes.
- [ ] `config.json` is created on first run at the platform config dir with the
      default settings.
