# Phase 06 — Interactive TUI

> **Status:** ✅ Written (commits 98759fb → 3b334ea).
> ✅ Verified with deps installed: all modules import, `tui_available()` is True,
> and `app_screen.run` dispatches and exits cleanly (smoke). The full interactive
> walkthrough still needs a human at a real TTY.

Goal: the full interactive experience. On start, show a selection of configs
(subscription nodes + manual proxies + groups + VPNs); once connected, show a
live status screen; provide management menus for everything built so far.

Use **prompt_toolkit** + **rich**, keyboard-driven, working in plain Windows
console and Termux.

## Tasks

- [x] `tui/widgets.py`: `menu`, `confirm`, `input_text`, `input_int`,
      `input_secret`, `multi_select`, `show_message`,
      `pick_profile(profiles, groups, include_vpn=True)` (dialog-based).
- [x] `tui/app_screen.py` — main loop: Connect / Manage / Test / Routing /
      Settings / Quit; guides to "add a config" when none exist.
- [x] `tui/manage.py`:
  - **Add**: subscription URL, paste share link, paste raw outbound, SOCKS/HTTP
    proxy, WireGuard, hysteria2, tuic, OpenVPN (.ovpn), OpenConnect (server)
  - **Subscriptions**: update one / update all / remove
  - **Profiles**: rename / remove / export share link
  - **Groups**: create balancer (strategy + members), create chain (ordered
    hops), remove
  - **Transfer**: backup/export/import actions (implemented in Phase 09)
- [x] `tui/routing_screen.py`: toggle mode all/split; add/remove/move rules
      (action, domain/IP/geo matchers).
- [x] `tui/connection_screen.py` — live status: target, engine, inbound URLs +
      auth, LAN IP, pid; keys `s` switch, `d` disconnect, `t` test, `q` back;
      Ctrl+C/EOF cleanly disconnects while `q` returns to the main menu with
      the connection preserved.
- [x] `tui/test_screen.py`: full proxy-delay, ICMP/TCP endpoint, and WS/WSS
      testing actions with shared scope selection.
- [x] `tui/settings_screen.py`: listen, mixed port, LAN sharing, inbound auth,
      DNS, log level, test URL, default engine.
- [x] Wire `app.py` — `main()` launches the TUI on a TTY when
      `prompt_toolkit`/`rich` are importable; otherwise prints a summary (keeps
      non-interactive use and tests working).

## Acceptance / manual checks (deferred — deps not installed)

- [x] Fresh install walks a new user into adding their first config (the TUI
      opens Manage automatically when no profiles or groups exist; automated
      regression coverage is in `test_tui_connection.py`).
- [x] Add subscription → select a node → connect dispatch (mocked UI coverage;
      live engine connection remains deferred).
- [x] Create balancer over several nodes and connect; create chain and connect
      (mocked UI coverage; live engine connection remains deferred).
- [x] Add an OpenVPN profile and connect (mocked UI/profile coverage; live TTY
      walkthrough remains deferred).
- [x] All flows keyboard-drivable through prompt-toolkit dialogs or the
      numbered small-terminal fallback (covered by `test_tui_widgets.py`).

## Definition of Done

- [x] Every Phase 03–05 feature is reachable from the TUI (code path).
- [~] Manual walkthrough — imports + main-loop smoke verified; a full
      interactive run still needs a human at a TTY (Linux/Windows/Termux).
- [x] `pytest` (existing suite) still passes — 112 tests.
