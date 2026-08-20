# Build Backlog — V2Ray Interactive CLI Client

These files are the implementation backlog. Read `../PLAN.md` first for the
architecture, decisions, and data model. Execute the phases **in numeric
order**; each phase ends with "Definition of Done" and lists dependencies.

| # | File | Scope | Depends on |
|---|---|---|---|
| 01 | *(passed)* | Package skeleton, settings (auth, engines, routing), models & storage | — |
| 02 | *(passed)* | Share-link decode (incl. hysteria2/tuic/wireguard) + subscription fetch/parse/update | 01 |
| 03 | *(passed)* | Manual outbounds, VPN profiles (openvpn/openconnect), groups, split-routing rules | 01, 02 |
| 04 | *(passed)* | Engine adapter (sing-box + xray), binary download, mixed inbound, split routing, chain/balancer | 01, 03 |
| 05 | *(passed)* | Launch/stop cores + VPN clients, live status, LAN exposure, auth | 04 |
| 06 | *(passed)* | Interactive menus, connect/switch screen, management + routing UI | 05 |
| 07 | `07-outbound-testing.md` | Engine-aware latency/reachability test, all or per-subscription | 04 |
| 08 | `08-cross-platform-packaging.md` | Windows/Termux polish, VPN client detection, README, release | 06, 07 |
| 09 | *(passed)* | Rolling backups, restore, full-config & share-link export/import | 01, 02 |
| 10 | *(passed)* | ICMP/TCP/WebSocket/full-delay tests and explicit sing-box/xray updates | 04, 05, 06, 07 |

## Conventions for the implementing agent

- `models.py` dataclasses are the single source of truth (Profile `kind` and
  `engine` fields drive everything downstream).
- Outbound/group tags = stable UUIDs; never user names.
- Engine selection is resolved once (in `engines/base.py::resolve_engine`) and
  reused by config-gen, runner, and tester.
- Validate engine config with the engine's own check command before launching.
- Add a `pytest` test next to any parser/generator change.
- Do not commit downloaded engine binaries, geo assets, or the runtime config.
- Run a backup before any destructive operation (update/remove/import/restore).
