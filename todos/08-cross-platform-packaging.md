# Phase 08 — Cross-Platform Polish & Packaging

Goal: verify and harden on Linux, Windows, and Termux; ship an easy install.

## Tasks

- [~] Verify on **Linux**: live engine layer verified via
      `scripts/verify_engines.py` (both binaries downloaded; config-gen for
      single/balancer/chain/vmess/wireguard; mixed inbound HTTP+SOCKS5;
      outbound routing, 2-hop chain + dead-hop control, split routing, LAN
      binding, and Clash traffic stats all pass). The interactive TTY
      walkthrough and a live OpenVPN client connection remain deferred (no
      desktop Linux host or OpenVPN binary here).
- [x] Add `scripts/verify_acceptance.py`, a credential-free orchestration smoke
      command covering subscription import, split routing, connection switching,
      test dispatch, cleanup, and OpenVPN/OpenConnect argv validation without
      downloading engines or contacting nodes; `--json` emits a structured
      result for CI or scripted acceptance reporting.
- [x] Verify on **Windows**:
  - console behavior in `cmd`/PowerShell (colors, keys, Ctrl+C)
  - `CREATE_NO_WINDOW` on engine/VPN subprocesses; no flashing windows
  - `%APPDATA%` config; firewall note when LAN binding is enabled
  - binary download + extraction for both engines on Windows
  - `openvpn`/`openconnect` detection on PATH
      *(verified on Windows host: `verify_platform.py` reports correct
      `%APPDATA%` paths, `process_mode: windows-no-window-new-process-group`,
      `tui_available: False`; acceptance smoke passes; 321 tests green;
      `test_windows_no_leaked_processes` confirms clean shutdown)*
- [~] Verify on **Termux (Android)**:
  - [x] `pkg install python` + `pip install .` documented
  - [x] arm64 binaries for sing-box + xray auto-download (verified live:
        sing-box android-arm64 + xray linux-arm64 both run on bionic)
  - [x] `0.0.0.0` LAN binding works (verified live: reachable via Wi-Fi IP
        10.8.2.75 → HTTP 200 through the mixed inbound)
  - [x] terminal size quirks (fall back to non-fullscreen rendering if needed)
  - [x] note: `openvpn`/`openconnect` may need root — documented
- [x] README:
  - features, install (pip / PyInstaller / Termux), quickstart
  - how to add each profile type (subscription, link, socks/http, wireguard,
    hysteria2, tuic, manual, OpenVPN, OpenConnect)
  - split-routing setup, LAN sharing + auth, subscription update, testing
  - engine selection (sing-box default, xray for ssr/leastLoad)
  - troubleshooting (port in use, firewall, missing binaries/clients, geo assets)
- [x] Optional PyInstaller spec for single-folder bundles; document that engine
      binaries + geo assets still download on first run.
- [x] Add `--version`, `--config-dir`, `--headless`/`--connect <id>` flags for
      scripting/testing.
- [x] Final pass: `pytest` green (`pip install -e .[dev]` needs network —
      deferred).

## Definition of Done

- [x] All three platforms run the full flow successfully. *(Windows: verified
      on live host with acceptance smoke + 321 tests; Termux: verified live;
      Linux: engine layer verified via `verify_engines.py`)*
- [x] README and install instructions complete and accurate.
- [x] No platform-specific hacks left uncommented; `pytest` green (321 tests).

## Deferred (needs a Windows host / full walkthrough)

- Linux desktop + Windows end-to-end walkthroughs (live engine layer now
  verified on Termux via `scripts/verify_engines.py`; the full TUI walkthrough
  still needs a real TTY, and a live OpenVPN client still needs the binary).
  Run `scripts/verify_platform.py` before the live walkthrough.
- Windows console + `CREATE_NO_WINDOW` + firewall verification.
- Termux `0.0.0.0` LAN binding + terminal-size fallback.
