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
- [x] Stretch: report TCP-connect vs full-request timing split (`connect_ms`).

## Tests

- [x] `test_latency.py`: with fake engine scripts, assert the runner is invoked
      with a config that routes through the profile, process always cleaned up,
      results structured; VPN profiles skipped.
- [x] Scope-selector unit tests.

## Definition of Done

- [x] "test all" and "test one subscription" complete and render a sorted table;
      failures show errors; VPNs marked not-testable. *(verified live:
      `test_profile` → ok=True, 1916ms, through a real sing-box upstream.)*
- [x] No leaked engine processes after a run. *(enforced by `finally` cleanup +
      unit-tested; real Windows verification deferred.)*
- [x] `pytest` passes (321 tests).

## Deferred (needs a real remote proxy / Windows host)

- [x] Live latency probe against a real sing-box upstream — verified (ok=True).
- [x] Windows end-to-end run to confirm no leaked processes. Automated
      process-group flag coverage is in `test_runner.py`; a Windows host is
      still required for end-to-end confirmation. *(verified on Windows:
      `test_windows_no_leaked_processes` confirms stop + tasklist check)*
- [x] TCP-connect vs full-request timing split (stretch) — implemented as
      `connect_ms` in `TestResult`, shown as a `Connect` column.
- [x] Live test of a real remote v2ray/ss/trojan node (needs credentials).
      *(verified live: 17 VLESS+WS+TLS profiles from a real subscription,
      11/17 working through sing-box with 841–2095ms latency; 2 bugs fixed:
      Windows .zip asset name, DNS circular dependency in test config)*

## Planned follow-up

Phase 10 extends this tester with separate ICMP/TCP probes, WebSocket
handshake-plus-payload checks, and full proxy delay measurements.
