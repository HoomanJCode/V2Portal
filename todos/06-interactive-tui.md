# Phase 06 — Interactive TUI

Goal: the full interactive experience. On start, show a selection of configs
(subscription nodes + manual proxies + groups); once connected, show a live
status screen; provide management menus for everything built so far.

Use **prompt_toolkit** (menus, fuzzy completions, dialogs) + **rich**
(tables/status). Keep it working in a plain Windows console and Termux (avoid
full-screen curses assumptions where possible).

## Tasks

- [ ] `tui/widgets.py` — small reusable pieces:
  - `menu(options) -> index` (arrow/`j`/`k` + fuzzy typeahead, Enter select)
  - `confirm(prompt)`, `input_text(prompt, default)`, `input_int`
  - `pick_profile(profiles, groups)` — combined, searchable list (groups first
    or a toggle), returning the chosen profile or group
- [ ] `tui/app_screen.py` — main screen loop:
  - on start: if profiles exist, immediately show the **select config** menu
    (mix of subscription nodes, manual proxies, groups); else guide through
    "add a subscription / paste a link / add socks/http / paste v2ray config"
  - actions: `Connect`, `Manage`, `Test`, `Settings`, `Quit`
- [ ] `tui/manage.py` — management menu:
  - **Add**: subscription URL, paste share link, paste raw v2ray outbound,
    add SOCKS proxy, add HTTP proxy
  - **Subscriptions**: list / update one / update all / remove
  - **Profiles**: list / edit name / remove / export share link
  - **Groups**: create balancer (pick strategy + members), create chain
    (pick ordered hops), edit, remove
- [ ] `tui/connection_screen.py` — live status while connected:
  - show target name, inbound URLs (`socks5://`, `http://`, LAN IP),
    up/down traffic (if Phase 05 stats exist), uptime
  - keys: `s` switch (back to select menu), `d` disconnect, `q` back,
    `t` jump to test
  - refresh without blocking; render updates on a short ticker or on log events
- [ ] `tui/test_screen.py` — pick scope (all / one subscription / specific
      profiles) and render a live-updating latency table (see Phase 07).
- [ ] `tui/settings_screen.py` — edit listen address, mixed port, DNS, log
      level, test URL.
- [ ] Wire `app.py` to launch the TUI and route between screens.

## Acceptance / manual checks

- [ ] Fresh install (no config) walks a new user into adding their first config.
- [ ] Adding a subscription, selecting one of its nodes, and connecting works
      end-to-end from the TUI.
- [ ] Creating a balancer over several nodes and connecting to it works.
- [ ] All flows are keyboard-drivable; nothing requires a mouse.

## Definition of Done

- [ ] Every Phase 03–05 feature is reachable from the TUI.
- [ ] Manual walkthrough passes on Linux; Windows and Termux verified in Phase 08.
- [ ] `pytest` (existing suite) still passes.
