# Phase 08 — Cross-Platform Polish & Packaging

Goal: verify and harden on Linux, Windows, and Termux; ship an easy install.

## Tasks

- [ ] Verify on **Linux**: full walkthrough (add sub → split-route config →
      connect → LAN curl → switch → test → disconnect; add OpenVPN profile).
- [ ] Verify on **Windows**:
  - console behavior in `cmd`/PowerShell (colors, keys, Ctrl+C)
  - `CREATE_NO_WINDOW` on engine/VPN subprocesses; no flashing windows
  - `%APPDATA%` config; firewall note when LAN binding is enabled
  - binary download + extraction for both engines on Windows
  - `openvpn`/`openconnect` detection on PATH
- [ ] Verify on **Termux (Android)**:
  - `pkg install python` + `pip install .` documented
  - arm64 binaries for sing-box + xray auto-download
  - `0.0.0.0` LAN binding works; show the phone's Wi-Fi IP
  - terminal size quirks (fall back to non-fullscreen rendering if needed)
  - note: `openvpn`/`openconnect` may need root — document limitations
- [ ] README:
  - features, install (pip / PyInstaller / Termux), quickstart
  - how to add each profile type (subscription, link, socks/http, wireguard,
    hysteria2, tuic, manual, OpenVPN, OpenConnect)
  - split-routing setup, LAN sharing + auth, subscription update, testing
  - engine selection (sing-box default, xray for ssr/leastLoad)
  - troubleshooting (port in use, firewall, missing binaries/clients, geo assets)
- [ ] Optional PyInstaller spec for single-folder bundles; document that engine
      binaries + geo assets still download on first run.
- [ ] Add `--version`, `--config-dir`, `--headless`/`--connect <id>` flags for
      scripting/testing.
- [ ] Final pass: `pytest`, `pip install -e .[dev]`, clean-config run on each
      platform.

## Definition of Done

- [ ] All three platforms run the full flow successfully (VPN flow at least with
      mock client on non-root Termux).
- [ ] README and install instructions complete and accurate.
- [ ] No platform-specific hacks left uncommented; `pytest` green.
