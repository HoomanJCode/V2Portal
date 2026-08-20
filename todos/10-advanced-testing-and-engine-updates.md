# Phase 10 — Advanced Outbound Testing & Engine Updates

> **Status:** In progress; endpoint ICMP/TCP probes are implemented.

Goal: provide deeper per-config verification and let users update sing-box or
xray only when they explicitly request it.

## Advanced outbound tests

- [x] Add an ICMP ping probe for each endpoint when the platform permits it;
      record unsupported/blocked ICMP separately instead of treating it as a
      proxy failure. Exposed by `--probe`.
- [x] Add a TCP-connect probe for each endpoint and report connect time,
      timeout, DNS failure, and refused connection distinctly. Exposed by
      `--probe`.
- [ ] Add WebSocket transport testing:
  - [ ] Start the resolved engine config for the selected profile.
  - [ ] Connect through the local inbound and verify a WebSocket upgrade
        handshake (`101 Switching Protocols`) when the profile uses WS/WSS.
  - [ ] Send a small ping/payload and verify a valid response before cleanup.
  - [ ] Report handshake and payload failures per config without aborting the
        remaining test run.
- [ ] Add real delay testing through each profile: perform a full HTTP request
      through the proxy, report TCP connect time separately from request time,
      and preserve per-config errors/timeouts.
- [ ] Run ICMP/TCP/WS/full-request tests with bounded concurrency and retain
      the existing sorted result table and cached result format.

## User-requested engine updates

- [ ] Add explicit CLI update actions for `sing-box`, `xray`, or both; do not
      update binaries automatically during startup or connection.
- [ ] Add matching TUI actions under Settings/Manage with confirmation,
      current-version/latest-version output, and cancellation.
- [ ] Update only binaries managed by the `auto` path; warn before replacing a
      user-specified `binary_path` and never overwrite custom binaries silently.
- [ ] Refuse or defer updates while the corresponding engine process is
      connected; download to a temporary file, validate the version, then
      replace the cached binary atomically.
- [ ] Keep the previous cached binary until the replacement is verified, and
      restore it if version detection or replacement fails.

## Tests

- [x] Unit-test ICMP-unavailable and TCP timeout/refused classification.
- [ ] Unit-test WebSocket handshake and payload failure, full-request delay,
      and mixed success/failure reporting.
- [ ] Test CLI/TUI update confirmation, engine selection, custom binary
      protection, running-engine protection, atomic replacement, and rollback.
- [ ] Test the supplied mixed-protocol subscription shape with configs that
      fail individually; one bad node must not stop the remaining tests.

## Definition of Done

- [x] ICMP and TCP endpoint measurements are visible and distinguishable.
- [ ] WS/WSS profiles complete handshake plus payload checks when applicable.
- [ ] Real proxy delay is measured separately from endpoint/connect timing.
- [ ] Users can explicitly update sing-box, xray, or both from CLI and TUI.
- [ ] Failed updates leave the prior working binary intact.
- [ ] `pytest` passes and live verification is recorded without marking blocked
      platform/credential checks as complete.
