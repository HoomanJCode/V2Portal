# Phase 08 — Cross-Platform Polish & Packaging

Goal: verify and harden on Linux, Windows, and Termux; ship an easy install.

## Tasks

- [ ] Verify on **Linux**: full walkthrough (add sub → connect → LAN curl →
      switch → test → disconnect).
- [ ] Verify on **Windows**:
  - console behavior in `cmd` and PowerShell (colors, keys, Ctrl+C)
  - `CREATE_NO_WINDOW` on the xray subprocess; no flashing windows
  - `%APPDATA%` config path; firewall note when LAN binding is enabled
  - binary download + zip extraction on Windows
- [ ] Verify on **Termux (Android)**:
  - `pkg install python` + `pip install .` path documented
  - arm64 binary auto-download works
  - LAN binding `0.0.0.0` works and the LAN IP hint shows the phone's Wi-Fi IP
  - terminal size quirks (fall back to non-fullscreen rendering if needed)
- [ ] README:
  - features, install (pip / PyInstaller / Termux), quickstart
  - how to add a subscription / link / socks / http / manual config
  - how LAN sharing works + how other devices connect
  - how updating subscriptions and testing outbounds work
  - troubleshooting (port in use, firewall, binary download blocked)
- [ ] Optional PyInstaller spec for a single-folder bundle (Windows `.exe` /
      Linux binary); document that xray-core is still downloaded on first run.
- [ ] Add `--version`, `--config-dir`, and a `--headless`/`--connect <id>` flag
      so the TUI can be bypassed for scripting (nice-to-have; matches
      "interactive" but helps testing).
- [ ] Final pass: `pytest`, `pip install -e .[dev]`, and a clean-config run on
      each platform.

## Definition of Done

- [ ] All three platforms run the full flow successfully.
- [ ] README and install instructions are complete and accurate.
- [ ] No platform-specific hacks left uncommented; `pytest` green.
