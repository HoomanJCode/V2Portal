# Phase 07 — Outbound Testing

Goal: measure latency / reachability of outbounds — all of them, one
subscription's nodes, or an arbitrary selection — and show a clear table.

## Tasks

- [ ] `test/latency.py` — `test_profile(profile, settings) -> TestResult`:
  - generate a minimal xray config: ephemeral local SOCKS inbound on a free
    port, a `freedom` outbound with `proxySettings.tag = <profile id>`, and a
    rule routing the test inbound through freedom
  - start a short-lived xray, then time an `httpx` GET to `settings.test_url`
    through `socks5://127.0.0.1:<ephemeral>`
  - record `{ ok, latency_ms, error }`; always kill the process (even on failure)
- [ ] `test_many(profiles, settings, concurrency=8) -> list[TestResult]` — run a
      bounded worker pool; enforce a per-node timeout.
- [ ] Scope selectors: `all`, `subscription_id=<id>`, `profile_ids=[...]`.
- [ ] Result rendering via `rich.table` (sorted by latency, failures last) with
      color coding (green/amber/red thresholds).
- [ ] Persist the last test result (`runtime/test_results.json`) so the TUI can
      show cached results while a re-test runs.
- [ ] Stretch: also report per-node round-trip of the DNS + TCP + TLS phases
      (connect vs full-request timing) for debugging.

## Tests

- [ ] `test_latency.py`: with a fake xray script, assert the runner is invoked
      with a freedom→profile config, the process is always cleaned up, and
      results are structured correctly.
- [ ] Scope-selector unit tests.

## Definition of Done

- [ ] `test all` and `test one subscription` both complete and render a sorted
      table; failing nodes are clearly marked with their error.
- [ ] No leaked xray processes after a test run (verify on Linux + Windows).
- [ ] `pytest` passes.
