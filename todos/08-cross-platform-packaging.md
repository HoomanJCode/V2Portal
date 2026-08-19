# Phase 08 — Cross-Platform Polish & Packaging

Goal: verify and harden on Linux, Windows, and Termux; ship an easy install.

## Tasks

- [ ] Verify on **Linux**: full walkthrough (add sub → split-route config →
      connect → LAN curl → switch → test → disconnect; add OpenVPN profile).
      *(deferred — needs real engine binaries)*
- [ ] Verify on **Windows**:
  - console behavior in `cmd`/PowerShell (colors, keys, Ctrl+C)
  - `CREATE_NO_WINDOW` on engine/VPN subprocesses; no flashing windows
  - `%APPDATA%` config; firewall note when LAN binding is enabled
  - binary download + extraction for both engines on Windows
  - `openvpn`/`openconnect` detection on PATH
      *(deferred — no Windows host here)*
- [~] Verify on **Termux (Android)**:
  - [x] `pkg install python` + `pip install .` documented
  - [x] arm64 binaries for sing-box + xray auto-download (verified live:
        sing-box android-arm64 + xray linux-arm64 both run on bionic)
  - [x] `0.0.0.0` LAN binding works (verified live: reachable via Wi-Fi IP
        10.8.2.75 → HTTP 200 through the mixed inbound)
  - [ ] terminal size quirks (fall back to non-fullscreen rendering if needed)
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

- [ ] All three platforms run the full flow successfully. *(deferred — needs
      real engine binaries + a Windows host)*
- [x] README and install instructions complete and accurate.
- [x] No platform-specific hacks left uncommented; `pytest` green (91 tests).

## Deferred (needs a Windows host / full walkthrough)

- Linux + Windows end-to-end walkthroughs (Termux binaries + config gen + mixed
  inbound verified; full TUI walkthrough still needs installed TUI deps).
- Windows console + `CREATE_NO_WINDOW` + firewall verification.
- Termux `0.0.0.0` LAN binding + terminal-size fallback.
