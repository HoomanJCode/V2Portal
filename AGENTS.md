# AGENTS.md — Rules for AI agents

Project: `v2raycli` — an interactive v2ray CLI client (sing-box + xray-core).

## Read first

- `PLAN.md` — architecture, decisions, data model, config mapping.
- `todos/README.md` — phase index and ordering. Execute phases in numeric order.
- **Status:** the universal ID model & dynamic resolution refactor
  (`todos/01-*.md` … `todos/06-*.md`) is **complete**. Current model: one ID
  space for profiles / subscriptions / groups / servers; every target ref is
  auto-detected and resolved at use time. Index: `todos/README.md`.

## Workflow

1. Work in small, self-contained steps and **commit after each step**
   (micro commits). Never batch unrelated changes into one commit.
2. Update the matching `todos/0X-*.md` checkboxes (`[ ]` → `[x]`) as tasks are
   completed, and commit those updates with (or right after) the related code.
3. Keep `models.py` dataclasses the single source of truth for config shape.
4. Verify by running `pytest` (from the repo root) before committing, when
   feasible.

## Commit conventions

- Concise, imperative subject describing intent; one topic per commit.
- Git identity may be unset locally. If `git commit` rejects for a missing
  identity, use:
  `git -c user.name="HoomanJ" -c user.email="Hooman.Jalalpoor@gmail.com" commit ...`
- Do not push unless the user asks.

## Code conventions

- Python 3.10+, `src/` layout, `pyproject.toml`.
- Type hints and dataclasses with explicit `to_dict()` / `from_dict()`.
- Add a pytest test next to any parser / generator / storage change.

## Never commit

- Engine binaries, geo assets, `runtime/`, `.venv/`, `__pycache__/`,
  `*.egg-info/`, `.pytest_cache/`.
