# Phase 06 — Interactive TUI

> **Status:** ✅ Written (commits 98759fb → 3b334ea).
> Not executed here — `prompt_toolkit`/`rich` are not installed in the dev env;
> all modules pass `py_compile`. Manual walkthrough deferred to Phase 08.

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
  - **Transfer**: placeholder (backup/export/import lands in Phase 09)
- [x] `tui/routing_screen.py`: toggle mode all/split; add/remove/move rules
      (action, domain/IP/geo matchers).
- [x] `tui/connection_screen.py` — live status: target, engine, inbound URLs +
      auth, LAN IP, pid; keys `s` switch, `d` disconnect, `t` test, `q` back.
- [x] `tui/test_screen.py`: placeholder (latency tester lands in Phase 07).
- [x] `tui/settings_screen.py`: listen, mixed port, inbound auth, DNS, log level,
      test URL, default engine.
- [x] Wire `app.py` — `main()` launches the TUI on a TTY when
      `prompt_toolkit`/`rich` are importable; otherwise prints a summary (keeps
      non-interactive use and tests working).

## Acceptance / manual checks (deferred — deps not installed)

- [ ] Fresh install walks a new user into adding their first config.
- [ ] Add subscription → select a node → connect end-to-end from the TUI.
- [ ] Create balancer over several nodes and connect; create chain and connect.
- [ ] Add an OpenVPN profile and connect (mock client).
- [ ] All flows keyboard-drivable.

## Definition of Done

- [x] Every Phase 03–05 feature is reachable from the TUI (code path).
- [ ] Manual walkthrough passes on Linux; Windows/Termux in Phase 08 — deferred.
- [x] `pytest` (existing suite) still passes — 79 tests.
