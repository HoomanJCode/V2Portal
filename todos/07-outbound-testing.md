# Phase 07 — Outbound Testing

Goal: measure latency / reachability of outbounds — all of them, one
subscription's nodes, or an arbitrary selection — engine-aware, with a clear
table.

## Tasks

- [x] `test/latency.py`:
  - `test_profile(profile, settings) -> TestResult`:
    - resolve engine, generate a minimal config: ephemeral local inbound, a
      `direct`/`freedom` exit routed **through** the profile (xray:
      freedom `proxySettings.tag`; sing-box: `detour`), rule routing test
      inbound → exit
    - start short-lived engine, time `httpx` GET to `settings.test_url` through
      `socks5://127.0.0.1:<ephemeral>`
    - record `{ ok, latency_ms, error, engine }`; always kill the process
  - `test_many(profiles, settings, concurrency=8)` — bounded worker pool,
    per-node timeout.
- [x] Scope selectors: `all`, `subscription_id=<id>`, `profile_ids=[...]`.
- [x] Skip `kind ∈ {openvpn, openconnect}` (VPNs aren't latency-tested; mark them
      "not testable" in the table).
- [x] Render via `rich.table` sorted by latency, failures last, color-coded.
- [x] Persist last results to `runtime/test_results.json` for cached display.
- [ ] Stretch: report TCP-connect vs full-request timing split.

## Tests

- [x] `test_latency.py`: with fake engine scripts, assert the runner is invoked
      with a config that routes through the profile, process always cleaned up,
      results structured; VPN profiles skipped.
- [x] Scope-selector unit tests.

## Definition of Done

- [x] "test all" and "test one subscription" complete and render a sorted table;
      failures show errors; VPNs marked not-testable. *(wired in `tui/test_screen.py`;
      E2E run needs real engine binaries — deferred.)*
- [x] No leaked engine processes after a run. *(enforced by `finally` cleanup +
      unit-tested; real Windows verification deferred.)*
- [x] `pytest` passes.

## Deferred (needs networked env / real engine binaries)

- Live "test all / test one subscription" run against actual sing-box/xray.
- Windows end-to-end run to confirm no leaked processes.
- TCP-connect vs full-request timing split (stretch).
