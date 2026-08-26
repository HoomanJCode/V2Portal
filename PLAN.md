# V2Ray Interactive CLI Client — Architecture & Plan

> **Status:** Implemented. The `todos/` phases (01–06) are complete and the
> behavior described here is live; this document is the architecture record.
> The user-facing command tree and examples live in `README.md`.

## 1. What this is

A fully-interactive command-line client that wraps two proxy engines
(**sing-box**, default, and **xray-core**, fallback) plus the system
`openvpn`/`openconnect` clients to do five jobs:

1. **Manage proxies** — subscribe to subscriptions, paste individual v2ray
   share links or raw configs, add plain SOCKS5 / HTTP / WireGuard / hysteria2 /
   tuic outbounds, and add OpenVPN / Cisco AnyConnect VPN profiles. Everything
   persists to a local config file.
2. **Serve** — persistent **servers**, each a separate engine process with its
   own local **mixed inbound** (SOCKS5 + HTTP on one port) bound to the LAN so
   any device on the network can use it. There is no ad-hoc `connect`: a
   server's outbound is a universal ref (profile | subscription | group |
   server | direct) resolved at start time.
3. **Route** — route all traffic through the selection, or use user-defined
   split-routing rules (direct / bypass / block by domain, IP, or geo).
4. **Test** — measure latency / reachability of all outbounds, or only the
   outbounds of one subscription.
5. **Back up & transfer** — automatic rolling backups of the config plus
   full-config and share-link export/import for migration and sharing.

## 2. Decisions (locked in with the user)

| Decision | Choice |
|---|---|
| **Universal ID space** | Profiles, subscriptions, groups, servers share **one counter** — an ID alone is unambiguous. Every target reference is auto-detected (no `--profile` / `--group` / `--subscription` selector flags). |
| **Dynamic graph, resolved at use time** | Any entity that contains outbounds (server, group, routing rule) accepts **profile | subscription | group | server**. Resolved recursively to concrete profiles at start/test; subscriptions refresh → new profiles flow automatically; deduped. |
| **Subscription as outbound target** | Resolves as a strategy-based balancer over its current profiles (strategy configurable, default `latency`). |
| **Nested groups** | Groups can hold profiles + subscriptions + other groups + servers; cycles rejected, members deduped. A server member resolves to a socks/http profile through its local inbound. |
| Uniform CLI | Every resource uses `list` / `add` / `edit` / `remove` + resource-specific actions (`group add` unifies `group create`; `subscription edit`/`rename`; `server edit --outbound REF`; `group tree`). Ad-hoc `connect` was dropped — connections are persistent servers. |
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
│    ├─ connect/status screen (pick any ref, live inbound + auth)            │
│    ├─ servers dashboard (status table, start/stop, start-all/stop-all)     │
│    ├─ groups tree (nested hierarchy) + subscription health table           │
│    └─ test / routing / settings screens                                    │
│                                                                             │
│  Core                                                                        │
│    ├─ storage      : load/save config.json                                  │
│    ├─ subs         : fetch + parse subscriptions, decode share links        │
│    ├─ outbounds    : manual/vpn profiles, groups (balancer/chain)           │
│    ├─ servers      : server lifecycle (start/stop/restart, ref resolution) │
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

### Directory layout

```
v2ray-cli/
├── pyproject.toml
├── README.md
├── PLAN.md
├── AGENTS.md
├── todos/                       # phase docs + index (all phases complete)
├── scripts/                     # verify_acceptance / verify_engines / verify_platform
├── src/v2raycli/
│   ├── __init__.py
│   ├── __main__.py
│   ├── app.py                   # CLI parser + command handlers
│   ├── config.py                # settings + platform paths
│   ├── models.py                # dataclasses + enums (single source of config shape)
│   ├── storage.py               # load/save/migrate config.json
│   ├── connection.py            # ConnectionController: engine process lifecycle
│   ├── servers.py               # server model + resolution helpers
│   ├── service.py               # boot service (systemd/termux) → server start --all
│   ├── traffic.py               # sing-box Clash API traffic polling
│   ├── backup.py                # rolling backups + restore
│   ├── exchange.py              # full-config and share-link export/import
│   ├── diagnostics.py           # read-only platform diagnostics
│   ├── geo.py                   # geo asset management
│   ├── errors.py
│   ├── subs/
│   │   ├── __init__.py
│   │   ├── fetcher.py           # fetch + retries + proxy resolution
│   │   ├── parser.py            # subscription import/update + userinfo
│   │   ├── health.py            # expiry/traffic status table
│   │   └── share.py             # link <-> outbound for all protocols
│   ├── outbounds/
│   │   ├── __init__.py
│   │   ├── manual.py
│   │   ├── groups.py            # group model, resolution, tree renderer
│   │   └── vpn.py               # openvpn(.ovpn) + openconnect profiles
│   ├── routing/
│   │   └── rules.py
│   ├── engines/
│   │   ├── __init__.py
│   │   ├── base.py              # EngineAdapter ABC
│   │   ├── singbox.py
│   │   ├── xray.py
│   │   └── binary.py            # locate/download both cores
│   ├── runner.py                # subprocess lifecycle (cores + vpn)
│   ├── test/
│   │   └── latency.py
│   └── tui/
│       ├── __init__.py
│       ├── app_screen.py        # main menu + config summary header
│       ├── connection_screen.py # connect/status panel
│       ├── servers_screen.py    # servers dashboard
│       ├── groups_screen.py     # group tree + creation
│       ├── manage.py            # subscriptions/profiles management
│       ├── routing_screen.py
│       ├── settings_screen.py
│       ├── test_screen.py
│       └── widgets.py           # unified rich-styled widgets
└── tests/                       # pytest suite (one file per module / feature)
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
    "socks_port": 0,                       // 0 = disabled; dedicated SOCKS-only inbound
    "http_port": 0,                        // 0 = disabled; dedicated HTTP-only inbound
    "allow_lan": true,
    "inbound_auth": { "enabled": false, "username": "", "password": "" },
    "dns": ["1.1.1.1", "8.8.8.8"],
    "log_level": "info",
    "test_url": "http://cp.cloudflare.com/generate_204",
    "default_engine": "sing-box",
    "backup_keep": 10,
    "traffic_api": false,                  // sing-box Clash API traffic stats
    "traffic_api_port": 9090,
    "subscription_proxy": ""              // URL or server id used by auto-update
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
  "target_id": null,              // profile/subscription/group/server id; null = currently selected
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

### Group (an outbound target)

```jsonc
{
  "id": "…",
  "name": "Auto lowest-latency",
  "type": "single|balancer|chain",
  "strategy": "latency|random|roundRobin|leastLoad",  // balancer only
  "profile_ids": ["…"],           // static members
  "subscription_ids": ["…"],      // dynamic: resolved to current profiles
  "group_ids": ["…"],             // nested groups (Phase 01)
  "server_ids": ["…"],            // servers as members: resolved to socks/http
                                    // profiles via their local inbound
  "engine": "auto"
}
```

### References & resolution

- **Server** outbound: `profile | subscription | group | server | direct`
  (`outbound_type` persisted; `outbound_id` holds the unique id).
- **Routing rule** `target_id` may reference any of profile | subscription |
  group | server (a server target is a socks/http hop through its local
  inbound). The TUI picker and the boot service resolve the same set.
- `resolve_refs(store, refs)` → deduped, ordered `Profile` list; expands
  subscriptions to current `profile_ids`, nested groups recursively, and a
  server id to a socks/http profile pointing at that server's local inbound
  (server→server chains loop-checked). Rejects cycles (`circular group
  reference`, server chains that reach a group containing them), raises on
  unknown ids.
- `subscription_target(store, sub_id, strategy="latency")` → balancer Target.
- `resolve_target` accepts `Profile | Subscription | Group | Server` models.

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

## 7. Server start / connect flow

There is no ad-hoc `connect` command: proxy connections are persistent
**servers** (each a separate engine process on its own port). Starting a
server (CLI `server start`, the TUI Servers dashboard, or the boot service):

1. Resolve the server's outbound ref (profile | subscription | group | server
   | direct) to a Target; engine `auto` → from kind/strategy; download binary
   if needed.
2. `engines.<engine>.generate(...)` → write `runtime/server-<id>/config.json`.
3. Validate (`<binary> check` / `xray run -test`), then start via `runner`.
4. For `openvpn`/`openconnect` profiles, instead launch the system client with
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
- `test endpoint` measures separate ICMP and TCP reachability with DNS/refusal/
  timeout classification; ICMP-unavailable platforms report "unsupported"
  rather than a failed node.
- `test websocket` starts the resolved engine, verifies the WS/WSS upgrade,
  sends a small ping/payload, and reports handshake/payload failures per profile.
- `test latency` measures real proxy request delay through the engine; test
  scopes accept any ref (profile | subscription | group | server).

### Explicit engine updates

- `engine update` updates sing-box, xray, or both from the CLI. Updates are
  never automatic.
- Updates apply only to binaries managed by the `auto` path; custom binary paths
  require an explicit warning and must not be overwritten silently.
- Downloads are staged, version-checked, atomically replaced, and rolled back if
  verification or replacement fails. Running engine processes block replacement.
- `--proxy` (a URL or a local server id) fetches through a restricted network.

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

See `todos/README.md`. All phases (01–06) are complete; the phase table there
links each phase file to what it delivered.
