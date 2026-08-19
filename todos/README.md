# Build Backlog — V2Ray Interactive CLI Client

These files are the implementation backlog. Read `../PLAN.md` first for the
architecture, decisions, and data model. Execute the phases **in numeric
order**; each phase ends with "Definition of Done" checkboxes and lists which
earlier phases it depends on.

| # | File | Scope | Depends on |
|---|---|---|---|
| 01 | `01-scaffold-and-config.md` | Project skeleton, packaging, config dir, settings & storage layer | — |
| 02 | `02-share-link-and-subscription.md` | Share-link decode/encode + subscription fetch/parse/update | 01 |
| 03 | `03-outbound-management.md` | Manual v2ray/socks/http outbounds + groups (balancer, chain) | 01, 02 |
| 04 | `04-xray-config-generation.md` | Profile/Group → xray JSON, mixed inbound, binary download | 01, 03 |
| 05 | `05-runtime-connection.md` | Launch/stop xray, live status, LAN exposure | 04 |
| 06 | `06-interactive-tui.md` | Interactive menus, connect/switch screen, management UI | 05 |
| 07 | `07-outbound-testing.md` | Latency/reachability test for all or per-subscription | 04 |
| 08 | `08-cross-platform-packaging.md` | Windows/Termux polish, PyInstaller, README, release | 06, 07 |

## Conventions for the implementing agent

- Keep `models.py` dataclasses the single source of truth; storage, config-gen,
  and TUI all consume them.
- Every outbound/group gets a stable UUID tag; never use user names as tags.
- Validate xray config by running `xray run -test -config <file>` before launching.
- Add a `pytest` test next to any parser/generator change.
- Do not commit downloaded xray binaries or the runtime config.
