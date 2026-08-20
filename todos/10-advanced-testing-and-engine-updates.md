# Phase 10 — Advanced Outbound Testing & Engine Updates

> **Status:** In progress; all automatable implementation slices are covered.

Goal: provide deeper per-config verification and let users update sing-box or
xray only when they explicitly request it.

## Advanced outbound tests

- [x] Add an ICMP ping probe for each endpoint when the platform permits it;
      record unsupported/blocked ICMP separately instead of treating it as a
      proxy failure. Exposed by `--probe`.
- [x] Add a TCP-connect probe for each endpoint and report connect time,
      timeout, DNS failure, and refused connection distinctly. Exposed by
      `--probe`.
- [x] Add WebSocket transport testing:
  - [x] Start the resolved engine config for the selected profile.
  - [x] Connect through the local inbound and verify a WebSocket upgrade
        handshake (`101 Switching Protocols`) when the profile uses WS/WSS.
  - [x] Send a small ping/payload and verify a valid response before cleanup.
  - [x] Report handshake and payload failures per config without aborting the
        remaining test run. Exposed by `--ws-test`.
- [x] Add real delay testing through each profile: perform a full HTTP request
      through the proxy, report TCP connect time separately from request time,
      and preserve per-config errors/timeouts. The existing `--test` path
      provides this behavior.
- [x] Run ICMP/TCP/WS/full-request tests with bounded concurrency and retain
      the existing sorted result table and cached result format.

## User-requested engine updates

- [x] Add explicit CLI update actions for `sing-box`, `xray`, or both; do not
      update binaries automatically during startup or connection.
- [x] Add matching TUI actions under Settings/Manage with confirmation,
      current-version/latest-version output, and cancellation.
- [x] Update only binaries managed by the `auto` path; custom and system
      `binary_path` values are protected and never overwritten silently.
- [x] Refuse updates while the corresponding engine process is connected;
      download to a temporary file, validate the version, then replace the
      cached binary atomically.
- [x] Keep the previous cached binary until the replacement is verified, and
      restore it if version detection or replacement fails.

## Tests

- [x] Unit-test ICMP-unavailable and TCP timeout/refused classification.
- [x] Unit-test WebSocket handshake and payload failure.
- [x] Unit-test full-request delay and mixed success/failure reporting.
- [x] Test CLI/TUI update confirmation, engine selection, custom binary
      protection, running-engine protection, atomic replacement, and rollback.
- [x] Test a credential-free mixed-protocol v2rayN subscription shape with
      configs that fail individually; one bad node does not stop the remaining
      tests. Live supplied credentials remain external to the repository.
- [x] Allow the live engine verification script to use an explicit, ephemeral
      HTTP/SOCKS proxy for GitHub metadata and binary downloads without storing
      the proxy value.

## Definition of Done

- [x] ICMP and TCP endpoint measurements are visible and distinguishable.
- [x] WS/WSS profiles complete handshake plus payload checks when applicable.
- [x] Real proxy delay is measured separately from endpoint/connect timing.
- [x] Users can explicitly update sing-box, xray, or both from CLI and TUI.
- [x] Failed updates leave the prior working binary intact.
- [ ] `pytest` passes and live verification is recorded without marking blocked
      platform/credential checks as complete.
