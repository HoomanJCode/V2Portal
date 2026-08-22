# v2raycli

Interactive v2ray client for the terminal. It wraps two proxy engines —
**sing-box** (default) and **xray-core** — behind a single config, and gives you
a full-screen menu to add subscriptions/proxies, chain or balance them, and
share a mixed SOCKS5+HTTP proxy over your LAN.

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
- **Groups** — `balancer` (latency / random / roundRobin / leastLoad), `chain`
  (proxy through proxy), and `single`.
- **Split routing** — domain/keyword/regex rules, IP CIDR, and geoip/geosite.
  Rules can target any profile, group, `direct`, or `block`. Stale rules
  are auto-cleaned when a profile or group is deleted.
- **LAN proxy inbound** — sing-box serves SOCKS5 *and* HTTP on one port;
  xray exposes SOCKS5 plus HTTP CONNECT on adjacent ports, with optional
  username/password auth.
- **Outbound testing** — `--probe` separately measures endpoint ICMP/TCP
  reachability with DNS/refusal/timeout classification; `--ws-test` validates
  WS/WSS handshake and ping/pong; `--test` measures real proxy request delay
  through the engine.
- **Traffic stats** — cumulative per-profile/group up/down usage (sing-box),
  recorded on disconnect.
- **Config on disk** — a single JSON file in your platform config dir.

## Install

### pip (Linux / macOS / Termux)

```bash
pip install .
# or, for development:
pip install -e .[dev]
```

> **Tip:** If the `v2raycli` command is not found after install, use
> `python -m v2raycli` as a fallback, or install with `pipx install .`
> (install pipx first: `pip install pipx`). `pipx` handles PATH setup
> automatically.

### Termux (Android)

```bash
pkg update && pkg install python
pip install .
```

The engine binaries (sing-box / xray) download automatically to
`~/.config/v2raycli/bin` on first use, with arm64 assets on Termux.

> Note: OpenVPN / OpenConnect may require root on Android and are not
> chainable/balanceable — they run the system client directly.

### Windows

```bash
pip install .
```

After installing, the `v2raycli` command is placed in Python's `Scripts`
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

2. Or use `python -m v2raycli` instead of `v2raycli` — this always works
   regardless of PATH.

Config lives in `%APPDATA%\v2raycli`. Engine binaries download to
`%APPDATA%\v2raycli\bin`. When LAN sharing is enabled, allow the program
through the Windows firewall.

### PyInstaller (single folder)

A spec is included:

```bash
pip install pyinstaller
pyinstaller v2raycli.spec
```

Engine binaries and geo assets still download on first run.

## Quickstart

The primary interface is non-interactive and safe for scripts. Run
`v2raycli --help` or `v2raycli COMMAND --help` for the complete tree:

```bash
v2raycli status
v2raycli profile list
v2raycli subscription list
v2raycli group list
v2raycli test latency all
```

Every mutating command uses explicit arguments and writes the config only after
validation. The full command layout is:

```text
profile       list | add | rename | remove | export
subscription  list | add | update | remove
group          list | create balancer | create chain | remove
server        list | add | start | stop | remove
test          latency | endpoint | websocket
backup        create | list | restore
config        show | set | export | import
engine        update
service       install | uninstall
routing       list | mode | add | move | remove
status        health
```

Examples:

```bash
# Add a manual proxy
v2raycli profile add socks office-proxy 127.0.0.1 1080
v2raycli profile add share us-node 'vless://...'
v2raycli profile rename PROFILE_ID 'Office proxy'

# Import a subscription
v2raycli subscription add my-provider https://example.com/sub --proxy socks5://127.0.0.1:1080
v2raycli profile list --subscription SUB_ID

# Start a proxy server on a port
v2raycli server add --port 1080 --profile PROFILE_ID --name 'US proxy'
v2raycli server start SERVER_ID

# Update all subscriptions, filter profiles by kind
v2raycli subscription update --all
v2raycli profile list --kind socks

# Create groups and routing rules
v2raycli group create balancer fastest PROFILE_A PROFILE_B --strategy latency
v2raycli group create chain chained PROFILE_A PROFILE_B
v2raycli routing add block --domain 'keyword:ads'
v2raycli routing add direct --geoip cn
v2raycli routing add proxy --domain netflix.com --target PROFILE_A
v2raycli routing list

# Run multiple proxy servers on different ports
v2raycli server add --port 1081 --group GROUP_B --protocol http --name 'Balancer'
v2raycli server list
v2raycli server start --all
```

### Legacy flags / scripting

```bash
v2raycli --version
v2raycli --config-dir /path/to/dir          # alternate config location
v2raycli --headless                          # print a summary (compatibility alias)
v2raycli --probe all                         # ICMP/TCP probe every endpoint
v2raycli --probe <subscription-id>           # probe one subscription's endpoints
v2raycli --ws-test all                        # validate WS/WSS profiles
v2raycli --test all                           # full proxy delay-test every outbound
v2raycli --update sing-box                    # explicitly update sing-box
v2raycli --update xray                        # explicitly update xray
v2raycli --update both                        # explicitly update both engines
v2raycli --update both --proxy socks5://127.0.0.1:10808  # update through a temporary proxy
v2raycli --test <subscription-id>            # test one subscription's nodes
v2raycli --test <id1,id2>                    # test specific profiles
v2raycli --backup                            # snapshot the config, print its path
v2raycli --list-backups                      # list snapshots (newest first)
v2raycli --restore <backup.json>             # restore a snapshot (safety backup first)
v2raycli --export <out.json> [--redact]      # export the full config (mask credentials)
v2raycli --import <out.json> [--replace]     # import (merge by default, or replace)
v2raycli --install-service <id>              # install a boot service (systemd/Termux)
v2raycli --uninstall-service                 # remove the installed service
v2raycli --health                            # show subscription expiry/traffic status
```

### Engine updates

Engine updates are never automatic. Use `v2raycli engine update sing-box`,
`v2raycli engine update xray`, or `v2raycli engine update both`. Only binaries
configured with `binary_path: "auto"` are replaceable; custom and system paths
are protected. Downloads are staged, version-checked, atomically replaced, and
rolled back if verification fails. For restricted networks, the CLI accepts an
ephemeral HTTP/SOCKS proxy with `--proxy`; it is never stored.

### Auto-update

Set `auto_update_days` on a subscription to have it re-fetched automatically
on startup when stale (never updated, or older than N days). Fetch failures are
logged and skipped — they never block startup. Disable per-run with
`--no-auto-update`.

### Subscription health

On startup the CLI warns (to stderr) about expired subscriptions and those
expiring within 7 days. `v2raycli --health` prints a table of expiry status and
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

- **Balancer** — pick 2+ profiles and a strategy (`latency`, `random`,
  `roundRobin`, `leastLoad`). `leastLoad` forces xray-core.
- **Chain** — pick an ordered list; traffic flows through each in order.
- VPN profiles cannot join balancers/chains.

## Split routing

In **split** mode, the first matching rule wins. Rules can target a specific
profile, group, `direct` (bypass proxy), or `block` (drop traffic).

### CLI

```bash
# Switch to split mode
v2raycli routing mode split

# Block ads
v2raycli routing add block --domain keyword:ads
v2raycli routing add block --geosite category-ads-all

# Bypass local and Chinese IPs
v2raycli routing add direct --ip 192.168.0.0/16
v2raycli routing add direct --geoip cn --geoip private

# Route specific sites through a profile
v2raycli routing add proxy --domain netflix.com --target PROFILE_ID
v2raycli routing add proxy --geosite gfw --target GROUP_ID

# List all rules
v2raycli routing list
v2raycli routing list --json

# Reorder rules (first match wins)
v2raycli routing move RULE_ID up
v2raycli routing move RULE_ID down

# Remove a rule
v2raycli routing remove RULE_ID
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

### Target profiles and groups

Proxy rules can target any profile or group by ID — not just the currently
connected target. This lets you route different traffic through different
outbounds:

```bash
# Route Netflix through a US profile
v2raycli routing add proxy --domain netflix.com --target US_PROFILE_ID

# Route streaming through a low-latency balancer group
v2raycli routing add proxy --geosite streaming --target BALANCER_GROUP_ID

# Route all traffic through the connected target (default)
v2raycli routing add proxy --domain example.com
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
adds them to the connected profile or group on disconnect. Works with sing-box
(the default engine); xray has no Clash-compatible HTTP API so its traffic is
not counted.

## Run as a service

Keep a server running across reboots:

```bash
v2raycli server add --port 1080 --profile PROFILE_ID
v2raycli server start SERVER_ID
v2raycli service install SERVER_ID
```

- **Linux** — writes a systemd *user* unit to
  `~/.config/systemd/user/v2raycli.service`; enable it with
  `systemctl --user enable --now v2raycli`.
- **Termux** — writes a `termux-services` run script to
  `~/.termux/sv/v2raycli/run`; enable with `sv-enable v2raycli`.

Remove it with `v2raycli service uninstall`.

## Engine selection

- **sing-box** is the default and serves most protocols plus `latency`/`random`/
  `roundRobin`. WireGuard profiles are emitted as sing-box **endpoints** (the
  format since 1.13, where the WireGuard outbound was removed) and can be
  chained, balanced and routed to like any other outbound.
- **xray-core** is used automatically for `ssr` and `leastLoad`.
- Override per profile/group, or change the global default in Settings.

## Troubleshooting

- **Port in use** — change the port with `v2raycli config set settings.mixed_port <port>`.
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
- **`v2raycli` command not found after `pip install .`** — the script is in
  Python's `Scripts` directory which may not be on `PATH`. Fix: use
  `python -m v2raycli`, add `Scripts` to your `PATH`, or reinstall with
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
pip install -e .[dev]
pytest
python scripts/verify_acceptance.py --json
```

GitHub Actions runs the pytest suite and the credential-free acceptance smoke
on Python 3.10, 3.11, and 3.12 for pushes and pull requests. Live engine,
remote-node, and platform walkthroughs remain separate from CI.

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
