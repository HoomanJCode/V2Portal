# V2Ray Interactive CLI Client — Architecture & Plan

> **Status:** Planning only. No code has been written yet. The files under `todos/`
> are the build backlog. An implementing agent should read this document first,
> then execute the phases in `todos/` in order.

## 1. What this is

A fully-interactive command-line client that wraps two proxy engines
(**sing-box**, default, and **xray-core**, fallback) plus the system
`openvpn`/`openconnect` clients to do five jobs:

1. **Manage proxies** — subscribe to subscriptions, paste individual v2ray
   share links or raw configs, add plain SOCKS5 / HTTP / WireGuard / hysteria2 /
   tuic outbounds, and add OpenVPN / Cisco AnyConnect VPN profiles. Everything
   persists to a local config file.
2. **Connect** — pick a proxy (single node, subscription node, balancer, or
   chain), then run a local **mixed inbound** (SOCKS5 + HTTP on one port) bound
   to the LAN so any device on the network can use it.
3. **Route** — route all traffic through the selection, or use user-defined
   split-routing rules (direct / bypass / block by domain, IP, or geo).
4. **Test** — measure latency / reachability of all outbounds, or only the
   outbounds of one subscription.
5. **Back up & transfer** — automatic rolling backups of the config plus
   full-config and share-link export/import for migration and sharing.

## 2. Decisions (locked in with the user)

| Decision | Choice |
|---|---|
| Language | **Python 3.10+** (Linux, Windows, Termux; fastest to iterate) |
| Engines | **Dual engine**: sing-box (default) + xray-core (fallback), behind an adapter layer |
| Protocol coverage | vmess, vless, trojan, ss, ssr, wireguard, hysteria2, tuic, socks, http |
| OpenVPN / Cisco AnyConnect | Integrate via system `openvpn` / `openconnect` clients as a separate "VPN profile" type (not chainable/balanceable with proxy outbounds) |
| Interactive UI | **prompt_toolkit** + **rich** |
| Config storage | **JSON** via `platformdirs` |
| HTTP client | **httpx** |
| Routing | **Split routing** (rules by domain / IP / geo), defaulting to "route everything" |
| Inbound auth | **Optional** — per-connection username/password for socks+http |
| Subscription update | **Delete** nodes that disappeared upstream |
| System behavior | **LAN server only** — run the mixed inbound; never touch OS routing/proxy |

## 3. Engine & protocol matrix

| Protocol | sing-box | xray-core |
|---|---|---|
| vmess / vless / trojan / ss | ✅ | ✅ |
| ssr (ShadowsocksR) | ❌ | ✅ |
| socks / http | ✅ | ✅ |
| wireguard | ✅ | ✅ |
| hysteria2 | ✅ | ❌ |
| tuic | ✅ | ❌ |
| OpenVPN / AnyConnect | ❌ (external client) | ❌ (external client) |

- **Default engine = sing-box** (native `mixed` inbound = socks+http one port;
  `url_test` / round-robin selector for auto-select).
- **xray-core** is used when a selected profile/group requires it (ssr, or the
  `leastPing`/`leastLoad` balancer strategies).
- A profile/group carries an `engine` field: `"auto"` (resolved from `kind` and
  strategy), `"sing-box"`, or `"xray"`.

### Auto-select strategy → engine mapping

| User-facing strategy | sing-box | xray-core |
|---|---|---|
| latency | `urltest` outbound | balancer `leastPing` |
| random | `selector` (strategy `random`) | balancer `random` |
| round robin | `selector` (strategy `round_robin`) | balancer `roundRobin` |
| least load | — (fallback to round robin) | balancer `leastLoad` |

> **VERIFY during Phase 04** the exact sing-box selector `strategy` values and
> the xray balancer `strategy.type` values for the pinned versions.

### Chaining → engine mapping

- **sing-box**: outbound `detour` field (chain each hop to the next).
- **xray-core**: outbound base `proxySettings.tag` (chain each hop to the next).

> **VERIFY** exact field placement for the pinned versions in Phase 04.

## 4. High-level architecture

```
┌───────────────────────────── v2ray-cli (Python) ────────────────────────────┐
│  TUI (prompt_toolkit + rich)                                                │
│    ├─ select config (subscription nodes + manual proxies + groups + VPNs)  │
│    ├─ manage (add/update subscriptions, outbounds, groups, VPNs, rules)    │
│    ├─ live connection screen (status, inbound addr, auth, up/down)         │
│    └─ test screen (latency table)                                          │
│                                                                             │
│  Core                                                                        │
│    ├─ storage      : load/save config.json                                  │
│    ├─ subs         : fetch + parse subscriptions, decode share links        │
│    ├─ outbounds    : manual/vpn profiles, groups (balancer/chain)           │
│    ├─ routing      : split-routing rule model + normalization               │
│    ├─ engines      : base adapter + singbox.py + xray.py + binary.py        │
│    ├─ runner       : spawn/kill engine cores + vpn clients, logs, stats     │
│    └─ test.latency : engine-aware per-outbound latency probe                │
└───────────────────────────────┬──────────────────────────────────────────────┘
                                │ spawns (one at a time)
        ┌───────────────────────┼───────────────────────────┐
        ▼                       ▼                           ▼
   sing-box core            xray-core                 openvpn/openconnect
   mixed inbound :1080      socks :1080 + HTTP :1081  (VPN profile, no inbound)
```

### Directory layout (to be created in Phase 01)

```
v2ray-cli/
├── pyproject.toml
├── README.md
├── PLAN.md
├── todos/
├── src/v2raycli/
│   ├── __init__.py
│   ├── __main__.py
│   ├── app.py
│   ├── config.py                  # settings + platform paths
│   ├── models.py                  # dataclasses + enums
│   ├── storage.py
│   ├── subs/
│   │   ├── __init__.py
│   │   ├── fetcher.py
│   │   ├── parser.py
│   │   └── share.py               # link <-> outbound for all protocols
│   ├── outbounds/
│   │   ├── __init__.py
│   │   ├── manual.py
│   │   ├── groups.py
│   │   └── vpn.py                 # openvpn(.ovpn) + openconnect profiles
│   ├── routing/
│   │   └── rules.py
│   ├── engines/
│   │   ├── __init__.py
│   │   ├── base.py                # EngineAdapter ABC
│   │   ├── singbox.py
│   │   ├── xray.py
│   │   └── binary.py              # locate/download both cores
│   ├── runner.py                  # subprocess lifecycle (cores + vpn)
│   ├── backup.py                  # rolling backups + restore
│   ├── exchange.py                # full-config and share-link export/import
│   ├── test/
│   │   └── latency.py
│   └── tui/
│       ├── __init__.py
│       ├── app_screen.py
│       ├── select_profile.py
│       ├── manage.py
│       ├── connection_screen.py
│       ├── test_screen.py
│       └── widgets.py
└── tests/                         # pytest
    ├── test_share.py
    ├── test_parser.py
    ├── test_config_gen.py
    ├── test_storage.py
    ├── test_groups.py
    └── test_routing.py
```

## 5. Data model (`config.json`)

Stored at `<platform config dir>/v2ray-cli/config.json`
(Linux/Termux `~/.config/v2ray-cli/`, Windows `%APPDATA%\v2ray-cli\`).

```jsonc
{
  "schema_version": 2,
  "settings": {
    "listen": "0.0.0.0",
    "mixed_port": 1080,
    "allow_lan": true,
    "inbound_auth": { "enabled": false, "username": "", "password": "" },
    "dns": ["1.1.1.1", "8.8.8.8"],
    "log_level": "info",
    "test_url": "http://cp.cloudflare.com/generate_204",
    "default_engine": "sing-box",
    "backup_keep": 10
  },
  "routing": {
    "mode": "all",                       // "all" | "split"
    "rules": [ /* ordered, see below */ ]
  },
  "engines": {
    "sing-box": { "binary_path": "auto", "version": "latest" },
    "xray":     { "binary_path": "auto", "version": "latest" }
  },
  "profiles": [],
  "subscriptions": [],
  "groups": []
}
```

### Routing rule

```jsonc
{
  "id": "…",
  "action": "proxy|direct|block",
  "target_id": null,              // profile/group id; null = currently selected
  "match": {
    "domains": ["example.com", "keyword:ads", "regex:^x\\."],
    "ips": ["10.0.0.0/8", "192.168.0.0/16"],
    "geoip": ["cn", "private"],
    "geosite": ["gfw", "category-ads-all"]
  }
}
```

### Profile (one concrete outbound / VPN)

```jsonc
{
  "id": "3f2b…",
  "name": "US-01",
  "kind": "vmess|vless|trojan|ss|ssr|socks|http|wireguard|hysteria2|tuic|manual|openvpn|openconnect",
  "engine": "auto",                // auto | sing-box | xray  (ignored for openvpn/openconnect)
  "share_link": "vmess://…",
  "outbound": { /* engine outbound object, minus tag/protocol */ },
  "vpn": null,                     // { "type": "openvpn|openconnect", "config_path": "…", "server": "…", "args": [] }
  "source": "subscription|manual",
  "subscription_id": null,
  "enabled": true,
  "created_at": "…",
  "updated_at": "…"
}
```

### Subscription — unchanged from v1 (see `todos/02`)

```jsonc
{
  "id": "…", "name": "…", "url": "https://…|file://…|paste://…",
  "user_agent": null, "last_updated": null, "expires": null, "traffic_used": 0,
  "profile_ids": ["…"], "auto_update_days": 0, "enabled": true
}
```

### Group (what the user connects to)

```jsonc
{
  "id": "…",
  "name": "Auto lowest-latency",
  "type": "single|balancer|chain",
  "strategy": "latency|random|roundRobin|leastLoad",  // balancer only
  "profile_ids": ["…"],           // balancer: candidate set; chain: ordered hops
  "engine": "auto"
}
```

## 6. Config generation (per engine)

The engine adapter exposes:
- `supported_kinds: set[str]`
- `generate(settings, routing, target) -> dict` — full engine config
- `run_args(config_path) -> list[str]` / `validate_args(config_path)`

Common shape produced for **both** engines:

- **Inbound**: sing-box → `mixed` inbound (socks5+http one port); xray →
  `socks` plus an adjacent `http` inbound (HTTP CONNECT support). Apply
  `settings.inbound_auth` when enabled. Bind the effective `listen` address.
- **Outbounds**: one per referenced profile + a `direct`/`block` fallback;
  tags = profile `id`.
- **Target**:
  - single → route to that outbound.
  - balancer → sing-box `selector`/`urltest`; xray `routing.balancers` + rule.
  - chain → sing-box `detour`; xray `proxySettings`; route to last hop.
- **Routing**: when `mode == "split"`, emit engine-native rules from
  `routing.rules`; final fallback = selected target.

## 7. Connect flow

1. User picks a profile / group / VPN from the interactive list.
2. Resolve the engine (`auto` → from kind/strategy); download binary if needed.
3. `engines.<engine>.generate(...)` → write `runtime/config.json`.
4. Validate (`<binary> check` / `xray run -test`), then start via `runner`.
5. For `openvpn`/`openconnect` profiles, instead launch the system client with
   the stored config; no inbound server is created (the VPN owns system routing
   — this is an explicit user choice, kept separate from proxy outbounds).
6. TUI shows target, engine, inbound URL(s) + auth, and (stretch) live traffic.

## 8. Backup, Export & Import

- **Automatic backups**: snapshot `config.json` to `BACKUP_DIR` before any
  destructive operation (subscription update, profile/group removal, import,
  restore); keep the last `settings.backup_keep` (default 10) and prune older.
- **Restore**: list timestamped backups and restore one; the current config is
  itself backed up first.
- **Full export**: portable JSON (`schema_version`, settings, routing,
  profiles, subscriptions, groups); optional `redact` mode masks credentials
  (passwords/uuids/keys) for sharing.
- **Share-link export**: dump selected profiles (or a subscription's nodes) as
  a newline-separated share-link file.
- **Import**: a full export (merge or replace, with dedupe + conflict
  handling) or a share-link file (reuses the subscription parser).
- Backups and exports live in the config dir; config dir permissions are `0700`.

## 9. Testing outbounds

- Engine-aware: same per-profile probe as before, but the temporary config and
  binary are chosen by the profile's resolved engine.
- VPN profiles (openvpn/openconnect) are **not** latency-tested; they show a
  simple "connect test" (client launches and establishes, then disconnects) —
  optional, deferred.

## 10. Cross-platform notes

- Two engine binaries to auto-download per OS/arch (sing-box + xray).
- `openvpn`/`openconnect` are system dependencies — detected on `PATH`; a clear
  error + install hint is shown if missing.
- Linux, Windows (`CREATE_NO_WINDOW`, `%APPDATA%`), Termux (arm64, `0.0.0.0`
  LAN binding) as before.

## 11. Risks / open questions to verify during implementation

1. **Mixed inbound** — sing-box uses `mixed` on one port; xray uses SOCKS on
   `mixed_port` plus HTTP CONNECT on the adjacent port.
2. **Selector/balancer strategies** — exact strategy strings for sing-box
   (`random`, `round_robin`, `url_test`) and xray (`random`, `roundRobin`,
   `leastPing`, `leastLoad`).
3. **Chaining fields** — sing-box `detour` vs xray `proxySettings` placement.
4. **Share-link variants** — ss legacy/SIP002, ssr payload, hysteria2/tuic/
   wireguard link formats; base64 padding variants.
5. **OpenVPN/AnyConnect integration** — confirm client CLI flags for "run with
   this config and daemonize/foreground" across OSes; VPN profiles are isolated
   from proxy chaining/balancing.
6. **Geo routing data** — sing-box and xray need geoip/geosite asset files;
   decide bundled vs downloaded on first use.
7. **Secrets at rest** — backups/exports contain credentials; set config dir
   permissions to `0700` and provide a redacted export for sharing.

## 12. Phase order

See `todos/README.md`.
