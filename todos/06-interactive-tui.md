# Phase 06 — Interactive TUI

Goal: the full interactive experience. On start, show a selection of configs
(subscription nodes + manual proxies + groups + VPNs); once connected, show a
live status screen; provide management menus for everything built so far.

Use **prompt_toolkit** + **rich**, keyboard-driven, working in plain Windows
console and Termux (avoid full-screen curses assumptions where possible).

## Tasks

- [ ] `tui/widgets.py`: `menu(options)` (arrow/`j`/`k` + fuzzy typeahead),
      `confirm`, `input_text`, `input_int`, `input_secret`,
      `pick_profile(profiles, groups, include_vpn=True)` (searchable, grouped).
- [ ] `tui/app_screen.py` — main loop:
  - on start: if profiles exist, show **select config** menu (subscription
    nodes, manual proxies, groups, VPNs); else guide through adding a first
    config
  - actions: Connect, Manage, Test, Routing, Settings, Quit.
- [ ] `tui/manage.py`:
  - **Add**: subscription URL, paste share link, paste raw outbound, SOCKS/HTTP
    proxy, WireGuard, hysteria2, tuic, OpenVPN (.ovpn), OpenConnect (server)
  - **Subscriptions**: list / update one / update all / remove
  - **Profiles**: list / edit name / remove / export share link
  - **Groups**: create balancer (strategy + members), create chain (ordered
    hops), edit, remove
  - **Transfer**: backup now, restore from backup, export full (with/without
    secrets), import (full or share-link file), export share links
- [ ] `tui/routing_screen.py`: toggle `mode` all/split; add/reorder/remove rules
      (action, domain/IP/geo matchers, optional target).
- [ ] `tui/connection_screen.py` — live status:
  - target name, engine, inbound URLs + auth (socks5/http, LAN IP), up/down
    traffic (if stats exist), uptime
  - keys: `s` switch, `d` disconnect, `t` test, `q` back
- [ ] `tui/test_screen.py`: scope picker + live latency table (Phase 07).
- [ ] `tui/settings_screen.py`: listen, mixed port, inbound auth, DNS, log level,
      test URL, default engine, per-engine binary path.
- [ ] Wire `app.py` to launch the TUI and route between screens.

## Acceptance / manual checks

- [ ] Fresh install walks a new user into adding their first config.
- [ ] Add subscription → select a node → connect end-to-end from the TUI.
- [ ] Create balancer over several nodes and connect; create chain and connect.
- [ ] Add an OpenVPN profile and connect (mock client).
- [ ] All flows keyboard-drivable.

## Definition of Done

- [ ] Every Phase 03–05 feature is reachable from the TUI.
- [ ] Manual walkthrough passes on Linux; Windows/Termux in Phase 08.
- [ ] `pytest` (existing suite) still passes.
