# v2portal

Non-interactive CLI client for v2ray proxy management. It wraps two proxy
engines — **sing-box** (default) and **xray-core** — behind a single config,
and lets you add subscriptions/proxies, chain or balance them, test latency,
and run inbound servers from the command line.

Runs on **Linux**, **Windows**, and **Termux (Android)**.

## Features

- **Dual engine** — sing-box (default) + xray-core, resolved per profile/group.
  xray is used automatically for `ssr` and the `leastLoad` strategy.
- **Subscriptions** — paste a subscription URL or raw base64/plain payload;
  import, update (deleted nodes are pruned), test a single subscription, and
  auto-update on a schedule (`auto_update_days`).
- **Protocols** — vmess, vless, trojan, ss, ssr, socks, http, wireguard,
  hysteria2, tuic, plus raw JSON configs. OpenVPN / OpenConnect via the system
  clients.
- **Groups** — `balancer` (latency / random / roundRobin / leastLoad) and
  `chain` (proxy through proxy).
- **Split routing** — domain/keyword/regex rules, IP CIDR, and geoip/geosite.
  Rules can target any profile, subscription, group, or server, plus
  `direct` or `block`. Stale rules are auto-cleaned when a profile, group,
  or server is deleted.
- **LAN proxy inbound** — sing-box serves SOCKS5 *and* HTTP on one port;
  xray exposes SOCKS5 plus HTTP CONNECT on adjacent ports, with optional
  username/password auth.
- **Outbound testing** — `--probe` separately measures endpoint ICMP/TCP
  reachability with DNS/refusal/timeout classification; `--ws-test` validates
  WS/WSS handshake and ping/pong; `--test` measures real proxy request delay
  through the engine.
- **Traffic stats** — cumulative per-profile/group up/down usage (sing-box),
  recorded when a server stops.
- **Config on disk** — a single JSON file in your platform config dir.

## Install

### PyPI (recommended)

```bash
pip install v2portal
# or, with pipx (handles PATH automatically):
pipx install v2portal
```

### From source

```bash
pip install git+https://github.com/HoomanJCode/V2Portal.git
# or, for development:
git clone https://github.com/HoomanJCode/V2Portal.git
pip install -e "V2Portal[dev]"
```

> **Tip:** If the `v2portal` command is not found after install, use
> `python -m v2portal` as a fallback, or install with `pipx install v2portal`
> (install pipx first: `pip install pipx`). `pipx` handles PATH setup
> automatically.

### Termux (Android)

```bash
pkg update && pkg install python
pip install v2portal
```

The engine binaries (sing-box / xray) download automatically to
`~/.config/v2portal/bin` on first use, with arm64 assets on Termux.

> Note: OpenVPN / OpenConnect may require root on Android and are not
> chainable/balanceable — they run the system client directly.

### Windows

```bash
pip install v2portal
```

After installing, the `v2portal` command is placed in Python's `Scripts`
directory (e.g. `%LOCALAPPDATA%\Python\pythonX.Y-64\Scripts`). If the
command is not found, **one of these will work**:

1. Add the `Scripts` folder to your system `PATH` permanently:
   ```powershell
   [Environment]::SetEnvironmentVariable(
       "Path",
       $env:Path + ";" + [IO.Path]::Combine([Environment]::GetFolderPath("LocalApplicationData"), "Python", "python$([Environment]::Version.ToString(3))", "Scripts"),
       "User"
   )
   ```
   Then restart your terminal.

2. Or use `python -m v2portal` instead of `v2portal` — this always works
   regardless of PATH.

Config lives in `%APPDATA%\v2portal`. Engine binaries download to
`%APPDATA%\v2portal\bin`. When LAN sharing is enabled, allow the program
through the Windows firewall.

### PyInstaller (single folder)

A spec is included:

```bash
pip install pyinstaller
pyinstaller v2portal.spec
```

Engine binaries and geo assets still download on first run.

## Quickstart

The primary interface is non-interactive and safe for scripts. Run
`v2portal --help` or `v2portal COMMAND --help` for the complete tree. The
interactive TUI (run `v2portal` with no arguments) is a modern rich-styled
panel UI with screens for Connect, a Servers dashboard (live status +
start/stop), a Groups tree, Subscriptions, Test, Routing, and Settings:

```bash
v2portal status
v2portal profile list
v2portal subscription list
v2portal group list
v2portal group tree
v2portal test latency all
```

Every mutating command uses explicit arguments and writes the config only after
validation. The full command layout is:

```text
profile       list | add | rename | edit | remove | export
subscription  list | add | edit | rename | update | remove  (aliases: sub, subscriptions)
group         list | add | tree | edit | remove | add-member | remove-member  (alias: groups)
server        list | add | edit | start | stop | restart | remove  (alias: sv)
routing       list | mode | add | move | enable | disable | remove
backup        create | list | restore
settings      show/set app settings, engine update
config        show | export | import (backup/restore)
service       install | uninstall
test          latency | endpoint | websocket
```

**One ID space, auto-detected references.** Every entity — profile,
subscription, group, server — has a unique ID from a single counter. Any
command that takes a *target reference* accepts a **profile, subscription,
group, or server ID** and detects the type automatically. References are
resolved at use time: a subscription always contributes its *current*
profiles, nested groups expand recursively (with dedup and cycle protection),
and a server member resolves to a socks/http profile through its local
inbound — so updated subscriptions flow everywhere automatically.

Examples:

```bash
# Add a manual profile
v2portal profile add socks office-proxy 127.0.0.1 1080
v2portal profile add share us-node 'vless://...'
v2portal profile edit ID --name "Office proxy" --host 10.0.0.2

# Import a subscription
v2portal subscription add my-provider https://example.com/sub
v2portal subscription edit SUB_ID --name 'Renamed provider'
v2portal profile list --subscription SUB_ID

# Groups accept profiles, subscriptions, groups, and servers (auto-detected)
v2portal group add balancer fastest PROFILE_A SUB_ID GROUP_B SERVER_ID --strategy latency
v2portal group add chain chained PROFILE_A PROFILE_B
v2portal group edit GROUP_ID --strategy random

# Render the nested group/subscription/server hierarchy
v2portal group tree

# Add a running server as a local socks/http profile
v2portal profile add server via-server SERVER_ID

# Start a proxy server on a port — REF is auto-detected
v2portal server add --port 1080 REF --name 'US proxy'
v2portal server edit SERVER_ID --outbound REF
v2portal server start SERVER_ID

# Servers run in the background and survive terminal close
v2portal server list
v2portal sv stop SERVER_ID
v2portal sv restart --all

# View and change settings
v2portal settings
v2portal settings test-url
v2portal settings mixed-port 1081
v2portal settings default-engine xray
v2portal settings engine update both

# Update all subscriptions, filter profiles by kind
v2portal subscription update --all
v2portal profile list --kind socks

# Test by group, subscription, or profile ID
v2portal test latency GROUP_ID
v2portal test endpoint SUB_ID

# Routing rules can target any reference
v2portal routing add block --domain 'keyword:ads'
v2portal routing add direct --geoip cn
v2portal routing add proxy --domain netflix.com --target SUB_ID

# Multiple servers on different ports
v2portal server add --port 1081 GROUP_ID --protocol http --name 'Balancer'
v2portal server start --all
```

### Engine updates

Engine updates are never automatic. Use `v2portal settings engine update sing-box`,
`v2portal settings engine update xray`, or `v2portal settings engine update both`. Only binaries
configured with `binary_path: "auto"` are replaceable; custom and system paths
are protected. Downloads are staged, version-checked, atomically replaced, and
rolled back if verification fails. For restricted networks, pass an ephemeral
proxy with `--proxy` on the update command (e.g. `v2portal settings engine update both --proxy
socks5://127.0.0.1:1080`); it is never stored.

### Auto-update

Set `auto_update_days` on a subscription to have it re-fetched automatically
on startup when stale (never updated, or older than N days). Fetch failures are
logged and skipped — they never block startup. Disable per-run with
`--no-auto-update`.

### Subscription health

On startup the CLI warns (to stderr) about expired subscriptions and those
expiring within 7 days. `v2portal health` prints a table of expiry status and
traffic used for every enabled subscription.


## Adding proxies

You can add proxies via CLI:

| Type | What it asks for |
|---|---|
| Subscription | URL (also `file://` and `paste://` accepted) |
| Share link | a `vmess://`, `vless://`, `trojan://`, `ss://`, `ssr://`, `hysteria2://`, `tuic://`, `wireguard://`, `socks://`, `http://` link |
| Socks / HTTP | server address, port, optional username/password |
| WireGuard | private key, address, peers |
| Hysteria2 / TUIC | server, auth, TLS/transport options |
| Raw config | paste a v2ray/xray outbound JSON object (uses xray engine) |
| OpenVPN | config file path or inline config + args |
| OpenConnect | server + args |

## Groups

- **Balancer** — pick references (profiles, subscriptions, groups, servers)
  and a strategy (`latency`, `random`, `roundRobin`, `leastLoad`).
  `leastLoad` forces xray-core. Everything resolves dynamically.
  A lone profile is rejected — a single profile is not a group.
- **Chain** — pick an ordered list; traffic flows through each in order.
- Groups can **nest**: a balancer can contain other groups. A server
  member resolves to a socks/http profile pointing at that server's local
  inbound ("localhost calling") — traffic physically passes through it.
  Members are resolved recursively at use time, deduplicated, and cycles
  (group→group and server→group→server) are rejected.
- `v2portal group tree` renders the whole hierarchy — top-level groups with
  their members (profiles, subscriptions and their current nodes, servers,
  nested groups) plus any subscription/server/profile no group references.
- VPN profiles cannot join balancers/chains.

A **subscription used as a target** (server outbound, routing rule, group
member) resolves as a strategy-based balancer over its *current*
profiles — refresh the subscription and the target follows automatically.

## Split routing

In **split** mode, the first matching rule wins. Rules can target a specific
profile, group, `direct` (bypass proxy), or `block` (drop traffic).

### CLI

```bash
# Switch to split mode
v2portal routing mode split

# Block ads
v2portal routing add block --domain keyword:ads
v2portal routing add block --geosite category-ads-all

# Bypass local and Chinese IPs
v2portal routing add direct --ip 192.168.0.0/16
v2portal routing add direct --geoip cn --geoip private

# Route specific sites through a profile, group, or server
v2portal routing add proxy --domain netflix.com --target PROFILE_ID
v2portal routing add proxy --geosite gfw --target GROUP_ID
v2portal routing add proxy --domain intranet.corp --target SERVER_ID

# List all rules
v2portal routing list
v2portal routing list --json

# Reorder rules (first match wins)
v2portal routing move RULE_ID up
v2portal routing move RULE_ID down

# Remove a rule
v2portal routing remove RULE_ID
```

### Match types

| Matcher | Syntax | Example |
|---|---|---|
| Domain (exact) | `--domain example.com` | `--domain netflix.com` |
| Domain (keyword) | `--domain keyword:ads` | `--domain keyword:ads` |
| Domain (regex) | `--domain regex:^x\\.` | `--domain regex:^ads\\.` |
| Domain (geosite) | `--domain geosite:category` | `--domain geosite:gfw` |
| IP/CIDR | `--ip 10.0.0.0/8` | `--ip 192.168.0.0/16` |
| GeoIP | `--geoip cn` | `--geoip cn --geoip private` |
| GeoSite | `--geosite category-ads-all` | `--geosite gfw` |

### Target any reference

Proxy rules can target any profile, subscription, group, or server by ID —
not just the server's default outbound. A server target routes matching
traffic through that server's local inbound. This lets you route different
traffic through different outbounds:

```bash
# Route Netflix through a US profile
v2portal routing add proxy --domain netflix.com --target US_PROFILE_ID

# Route streaming through a low-latency balancer group
v2portal routing add proxy --geosite streaming --target BALANCER_GROUP_ID

# No --target: the rule follows the server's own outbound
v2portal routing add proxy --domain example.com
```

### Automatic cleanup

When you delete a profile or group, any routing rules targeting it are
automatically removed — no broken configs.

### Geo assets

On sing-box, `geosite:`/`geoip:` entries compile to rule-sets that
auto-download from SagerNet/sing-geosite and SagerNet/sing-geoip. On xray,
`geoip.dat`/`geosite.dat` download to `geo/` (found via `XRAY_LOCATION_ASSET`).

## LAN sharing

By default `allow_lan` is enabled — the inbound listens on `0.0.0.0` so other
devices on your network can use `socks5://<your-ip>:1080` /
`http://<your-ip>:1080`. Optionally enable inbound auth (username/password).

## Traffic stats

Enable **Settings → Traffic stats** (or set `settings.traffic_api: true` in the
config) to have sing-box expose its Clash API on `127.0.0.1`
(`traffic_api_port`, default 9090). The CLI polls cumulative up/down bytes and
adds them to the server's outbound target when the server stops. Works with
sing-box (the default engine); xray has no Clash-compatible HTTP API so its
traffic is not counted.

## Run as a service

Keep all enabled servers running across reboots (no ad-hoc `connect` command
— connections are servers):

```bash
v2portal server add --port 1080 REF
v2portal server start --all
v2portal service install
```

- **Linux** — writes a systemd *user* unit to
  `~/.config/systemd/user/v2portal.service`; enable it with
  `systemctl --user enable --now v2portal`.
- **Termux** — writes a `termux-services` run script to
  `~/.termux/sv/v2portal/run`; enable with `sv-enable v2portal`.

Remove it with `v2portal service uninstall`.

## Engine selection

- **sing-box** is the default and serves most protocols plus `latency`/`random`/
  `roundRobin`. WireGuard profiles are emitted as sing-box **endpoints** (the
  format since 1.13, where the WireGuard outbound was removed) and can be
  chained, balanced and routed to like any other outbound.
- **xray-core** is used automatically for `ssr` and `leastLoad`.
- Override per profile/group, or change the global default in Settings.

### Routing guide: per-destination proxy selection

You can route different traffic through different outbounds using split routing
rules. Here's a practical setup:

```bash
# Enable split routing
v2portal routing mode split

# Route Epic Games traffic through a Berlin profile
v2portal routing add proxy --domain epicgames.com --target BERLIN_PROFILE_ID
v2portal routing add proxy --domain fortnite.com --target BERLIN_PROFILE_ID

# Route YouTube traffic through a balancer group
v2portal routing add proxy --domain youtube.com --target GROUP_1_ID
v2portal routing add proxy --domain googlevideo.com --target GROUP_1_ID

# Route everything else through a subscription (auto-detected as a member)
v2portal group add balancer default SUB_ID_A SUB_ID_2

# Route Russian websites directly (no proxy)
v2portal routing add direct --geoip ru
v2portal routing add direct --geosite ru

# Block ads globally
v2portal routing add block --geosite category-ads-all

# Review your rules
v2portal routing list
```

Rules are evaluated in order; the first match wins. Use `v2portal routing move`
to reorder them.

## Troubleshooting

- **Port in use** — change the port with `v2portal settings mixed-port <port>`.
- **"binary not found"** — binaries download on first use; if download fails,
  set `engines.<name>.binary_path` in the config to a local binary, or
  `"system"` to use one on `PATH`.
- **LAN unreachable** — check the firewall (Windows) and that devices share the
  network.
- **Geo rules silent** — sing-box auto-downloads rule-sets, and xray's
  `geoip.dat`/`geosite.dat` download to `geo/` on first use (both need
  network).
- **VPN client missing** — install `openvpn` / `openconnect` and ensure it's on
  `PATH`.
- **`v2portal` command not found after `pip install .`** — the script is in
  Python's `Scripts` directory which may not be on `PATH`. Fix: use
  `python -m v2portal`, add `Scripts` to your `PATH`, or reinstall with
  `pipx install .`.

## Config layout

Config is JSON at `<config-dir>/config.json`. Derived dirs under the same base:

- `runtime/` — generated engine configs and test results
- `bin/` — downloaded engine binaries
- `geo/` — xray `geoip.dat`/`geosite.dat` assets (sing-box rule-sets are
  cached by the engine)
- `backup/` — automatic config backups

## Development

```bash
git clone https://github.com/HoomanJCode/V2Portal.git
pip install -e "V2Portal[dev]"
pytest
python scripts/verify_acceptance.py --json
```

GitHub Actions runs the pytest suite on Ubuntu and Windows (Python 3.12)
for pushes and pull requests. Live engine, remote-node, and platform
walkthroughs remain separate from CI.

Read-only platform diagnostics (does not load or modify the config, download
binaries, or start processes):

```bash
python scripts/verify_platform.py
python scripts/verify_platform.py --json
```

Credential-free orchestration smoke (subscription import, split routing,
connection switching, test dispatch, cleanup, and OpenVPN/OpenConnect argv
validation;
does not download engines or contact remote nodes):

```bash
python scripts/verify_acceptance.py
python scripts/verify_acceptance.py --json
```

Live engine verification (downloads sing-box + xray, runs their own config
checks, and exercises the proxy end-to-end):

```bash
python scripts/verify_engines.py
# If GitHub access requires a local HTTP/SOCKS proxy:
python scripts/verify_engines.py --proxy socks5://127.0.0.1:10808
```
