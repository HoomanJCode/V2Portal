# V2Ray Interactive CLI Client — Architecture & Plan

> **Status:** Planning only. No code has been written yet. The files under `todos/`
> are the build backlog. An implementing agent should read this document first,
> then execute the phases in `todos/` in order.

## 1. What this is

A fully-interactive command-line client that wraps a v2ray-family core
(**xray-core**) to do three jobs:

1. **Manage proxies** — subscribe to subscriptions, paste individual v2ray
   share links or raw v2ray configs, and add plain SOCKS5 / HTTP proxies as
   outbounds. Everything persists to a local config file.
2. **Connect** — pick a proxy (a single node, a node from a subscription, a
   balancer, or a chain), then run a local **mixed inbound** server (SOCKS5 +
   HTTP on one port) bound to the LAN so any device on the network can use it.
3. **Test** — measure latency / reachability of all outbounds, or only the
   outbounds of one subscription.

## 2. Decisions (made, with rationale)

| Decision | Choice | Why |
|---|---|---|
| Language | **Python 3.10+** | Available on Linux, Windows (installer) and Termux (`pkg install python`); fastest to iterate; very readable for a later AI/contributor. |
| Engine | **xray-core** (subprocess) | Actively maintained fork of v2ray-core; supports all v2ray share-link protocols (vmess/vless/trojan/ss/ssr) plus socks/http outbounds; has `balancer` (random, roundRobin, leastPing, leastLoad) matching the requested auto-select strategies; supports outbound chaining via `proxySettings`. |
| Interactive UI | **prompt_toolkit** + **rich** | Pure-Python, works on Windows and Termux, robust menus/fuzzy pickers/tables, no curses dependency hell. |
| Config storage | **JSON** at a platform config dir (via `platformdirs`) | Human-readable, trivial to diff/backup, no schema migration tooling needed. |
| HTTP client | **httpx** | Modern, supports timeouts/proxies (SOCKS via `socksio`), used for fetching subscriptions and for latency probing. |
| Packaging | `pyproject.toml` + console script; documented manual install for Termux; optional PyInstaller single-folder bundle later | Keep it runnable on all three platforms without a heavy build step. |
| Engine binary | **Auto-download** a pinned xray-core release (per OS/arch) into the config dir, with fallback to a system `xray`/`v2ray` on `PATH` | No manual dependency; user can override the path. |

> **Can be changed cheaply.** The parsing, config-storage, and config-generation
> logic is language-independent in spirit. If you prefer a single Go binary or a
> Node CLI, only the code (not the model) changes. Flag this early.

## 3. High-level architecture

```
┌─────────────────────────── v2ray-cli (Python) ───────────────────────────┐
│                                                                          │
│  TUI (prompt_toolkit + rich)                                             │
│    ├─ profile / subscription / group menus (add, edit, remove, select)  │
│    ├─ live connection screen (status, inbound addr, up/down traffic)     │
│    └─ test screen (latency table)                                        │
│                                                                          │
│  Core                                                                     │
│    ├─ storage        : load/save config.json (platform config dir)       │
│    ├─ subs.fetcher   : download subscription payloads                    │
│    ├─ subs.parser    : base64 / plain / share-link → Profile objects     │
│    ├─ outbounds      : manual v2ray/socks/http, groups (balancer/chain)  │
│    ├─ xray.config_gen: Profile/Group → xray JSON config                  │
│    ├─ xray.runner    : spawn/kill `xray run`, parse logs, expose stats   │
│    └─ test.latency   : per-outbound latency probe                        │
│                                                                          │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ spawns
                         ┌──────▼────────┐
                         │   xray-core   │  mixed inbound (SOCKS5+HTTP) :1080
                         │  (subprocess) │  ──► selected outbound/group
                         └───────────────┘
```

### Directory layout (to be created in Phase 01)

```
v2ray-cli/
├── pyproject.toml
├── README.md
├── PLAN.md
├── todos/                       # this planning backlog
├── src/v2raycli/
│   ├── __init__.py
│   ├── __main__.py              # python -m v2raycli
│   ├── app.py                   # top-level loop / command dispatch
│   ├── config.py                # settings + platform paths
│   ├── models.py                # dataclasses (Profile, Subscription, Group, Settings)
│   ├── storage.py               # load/save/validate config.json
│   ├── subs/
│   │   ├── __init__.py
│   │   ├── fetcher.py
│   │   ├── parser.py            # subscription payload → links
│   │   └── share.py             # vmess/vless/trojan/ss/ssr link <-> outbound
│   ├── outbounds/
│   │   ├── __init__.py
│   │   ├── manual.py
│   │   └── groups.py            # balancer + chain builders
│   ├── xray/
│   │   ├── __init__.py
│   │   ├── binary.py            # locate/download xray-core
│   │   ├── config_gen.py        # Profile/Group → xray JSON
│   │   └── runner.py            # subprocess lifecycle + log parsing
│   ├── test/
│   │   └── latency.py
│   └── tui/
│       ├── __init__.py
│       ├── app_screen.py
│       ├── select_profile.py
│       ├── manage.py
│       ├── test_screen.py
│       └── widgets.py
└── tests/                       # pytest unit tests
    ├── test_share.py
    ├── test_parser.py
    ├── test_config_gen.py
    └── test_storage.py
```

## 4. Data model (`config.json`)

Stored at `<platform config dir>/v2ray-cli/config.json`
(Linux/Termux `~/.config/v2ray-cli/`, Windows `%APPDATA%\v2ray-cli\`).

```jsonc
{
  "schema_version": 1,
  "settings": {
    "listen": "0.0.0.0",           // LAN-accessible inbound
    "mixed_port": 1080,            // SOCKS5 + HTTP on the same port
    "allow_lan": true,
    "dns": ["1.1.1.1", "8.8.8.8"],
    "log_level": "info",
    "test_url": "http://cp.cloudflare.com/generate_204"
  },
  "xray": {
    "binary_path": "auto",         // "auto" | "system" | "/absolute/path"
    "version": "latest"            // pinned release tag once downloaded
  },
  "profiles": [ /* leaf outbounds, see below */ ],
  "subscriptions": [ /* subscription definitions */ ],
  "groups": [ /* balancers + chains */ ]
}
```

### Profile (one concrete outbound)

```jsonc
{
  "id": "3f2b…",                     // uuid4
  "name": "US-01",
  "kind": "vmess|vless|trojan|ss|ssr|socks|http|manual",
  "share_link": "vmess://…",         // original link if imported from one
  "outbound": { "settings": {...}, "streamSettings": {...} }, // xray outbound (minus tag/protocol)
  "source": "subscription|manual",
  "subscription_id": null,           // set when it came from a subscription
  "enabled": true,
  "created_at": "2026-08-19T…",
  "updated_at": "2026-08-19T…"
}
```

- `kind` **socks**/**http** → a plain proxy outbound; the "password"/address/port
  are prompted and stored inside `outbound.settings`.
- `kind` **manual** → the user pasted a raw xray outbound object; we wrap it.

### Subscription

```jsonc
{
  "id": "…",
  "name": "My provider",
  "url": "https://…",                // or a file:// path, or "paste://<payload>"
  "user_agent": null,
  "last_updated": null,
  "expires": null,                   // from Subscription-Userinfo header
  "traffic_used": 0,
  "profile_ids": ["…", "…"],         // profiles parsed from this sub
  "auto_update_days": 0,             // 0 = manual
  "enabled": true
}
```

### Group (what the user actually "connects" to)

```jsonc
{
  "id": "…",
  "name": "Auto lowest-latency",
  "type": "single|balancer|chain",
  "strategy": "random|roundRobin|leastPing|leastLoad", // balancer only
  "profile_ids": ["…", "…"]          // balancer: candidate set; chain: ordered hops
}
```

- `single` groups are implicit (a profile can be selected directly) — a `single`
  group is only stored when the user saves a "favorite" with a custom name.
- **Balancer** = auto-select over a set of profiles using the chosen strategy.
- **Chain** = ordered hop list; entry = `profile_ids[0]`, exit = last element.

## 5. Mapping to xray-core config

The generator (`xray/config_gen.py`) emits a fresh JSON config each time the
user connects. Core shape:

```jsonc
{
  "log": { "loglevel": "info" },
  "inbounds": [
    {
      "tag": "mixed-in",
      "listen": "0.0.0.0",
      "port": 1080,
      "protocol": "socks",
      "settings": { "auth": "noauth", "udp": true }
      // NOTE: xray's SOCKS inbound also answers HTTP CONNECT on the same port,
      // giving "SOCKS + HTTP on one port". VERIFY this during Phase 04; if the
      // pinned xray build does not, fall back to two inbounds on separate ports
      // (socks 1080 + http 1081) and surface both addresses in the TUI.
    }
  ],
  "outbounds": [ /* one entry per profile in the selected set, plus a `direct` */ ],
  "routing": {
    "balancers": [ /* only for balancer groups */ ],
    "rules": [
      { "type": "field", "inboundTag": ["mixed-in"], "outboundTag": "<selected>" }
    ]
  }
}
```

Rules per group type:

- **single** → `outboundTag` = the profile's tag.
- **balancer** → add an entry to `routing.balancers`
  `{ "tag": "<group id>", "selector": ["<tag…>"], "strategy": { "type": "leastPing" } }`
  and route to the balancer tag. Strategies map 1:1:
  `random`, `roundRobin`, `leastPing`, `leastLoad`.
- **chain** → emit one outbound per hop and chain them with `proxySettings`:
  hop `i` gets `"proxySettings": { "tag": "<tag of hop i-1>", "transportLayer": false }`
  (first hop has none); route to the **last** hop's tag.
  **VERIFY exact field name/location** (`proxySettings` on the outbound base object)
  against the pinned xray version in Phase 04; adjust the generator accordingly.

Outbound tags: use the profile `id` (stable, collision-free); keep a human label
in a comment/log only (xray tags are internal).

## 6. The connect flow

1. User picks a profile or group from the interactive list (which shows both
   subscription nodes and manually-added profiles/groups).
2. `config_gen` builds the xray config and writes `runtime/config.json`.
3. `runner` starts `xray run -config <path>` and reports the process status.
4. TUI shows: connected target, inbound `mixed://0.0.0.0:1080`, and (stretch)
   live up/down traffic parsed from xray logs or the stats API.
5. "Switch" regenerates config and restarts the process. "Stop" terminates it.

## 7. Testing outbounds

Per-outbound latency test (Phase 07):

- For each profile under test, start a short-lived xray with a minimal config:
  an ephemeral local SOCKS inbound, a `freedom` outbound whose
  `proxySettings.tag` = the profile, and a rule routing the test inbound through
  freedom. Time an HTTP request to `settings.test_url` through it, then kill it.
- Run a small batch concurrently; report `{ name, ok, latency_ms, error }`.
- Reuse the same machinery for "test all" vs "test one subscription".

Stretch: use xray's `observatory`/leastPing to get latencies without per-node
processes, but keep the explicit approach as the default because it gives a
clear per-node result.

## 8. Cross-platform notes

- **Linux** — primary target; xray binary from release tarball.
- **Windows** — `%APPDATA%` config; console via `cmd`/PowerShell; ensure the
  process is killed cleanly on Ctrl+C and no console window flashes (use
  `subprocess.CREATE_NO_WINDOW`).
- **Termux (Android)** — Python via `pkg install python`; xray arm64 binary;
  binding `0.0.0.0` works so LAN devices can connect; show the phone's LAN IP.

## 9. Risks / open questions to verify during implementation

1. **Mixed inbound** — confirm the pinned xray build answers HTTP CONNECT on the
   SOCKS inbound (single-port SOCKS+HTTP). Fallback documented above.
2. **Chaining field** — confirm `proxySettings` placement for the pinned xray.
3. **Subscription encodings** — base64 (standard/url-safe, with or without
   padding), plain newline lists, and Clash YAML (optional stretch).
4. **SS/SSR link variants** — legacy base64 vs SIP002 `ss://` forms.
5. **Android DNS/TLS** — Termux may need `udp: true` and specific DNS settings.

## 10. Phase order

See `todos/README.md` for the ordered, dependency-annotated backlog.
