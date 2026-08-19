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
- **LAN mixed inbound** — one port serving SOCKS5 *and* HTTP on `0.0.0.0`, with
  optional username/password auth.
- **Latency testing** — test all outbounds, one subscription, or a selection,
  with a sorted, color-coded table.
- **Config on disk** — a single JSON file in your platform config dir.

## Install

### pip (Linux / macOS / Termux)

```bash
pip install .
# or, for development:
pip install -e .[dev]
```

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

```bash
v2raycli
```

Start screen:

- **Connect** — pick a config (subscription node, manual proxy, or group) and
  start the proxy.
- **Manage** — add subscriptions, share links, manual proxies, VPN profiles, and
  groups.
- **Test** — latency-test all outbounds or one subscription.
- **Routing** — edit split-routing rules.
- **Settings** — port, LAN sharing, inbound auth, default engine, test URL.

### Scripting / headless

```bash
v2raycli --version
v2raycli --config-dir /path/to/dir          # alternate config location
v2raycli --headless                          # print a summary, no TUI
v2raycli --connect <profile-or-group-id>     # connect and stay running (Ctrl+C to stop)
v2raycli --test all                          # latency-test every outbound
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

In **Manage → Add**, you can add:

| Type | What it asks for |
|---|---|
| Subscription | URL (also `file://` and `paste://` accepted) |
| Share link | a `vmess://`, `vless://`, `trojan://`, `ss://`, `ssr://`, `hysteria2://`, `tuic://`, `wireguard://`, `socks://`, `http://` link |
| Socks / HTTP | server address, port, optional username/password |
| WireGuard | private key, address, peers |
| Hysteria2 / TUIC | server, auth, TLS/transport options |
| Raw config | paste a v2ray/xray outbound JSON object |
| OpenVPN | config file path or inline config + args |
| OpenConnect | server + args |

## Groups

- **Balancer** — pick 2+ profiles and a strategy (`latency`, `random`,
  `roundRobin`, `leastLoad`). `leastLoad` forces xray-core.
- **Chain** — pick an ordered list; traffic flows through each in order.
- VPN profiles cannot join balancers/chains.

## Split routing

Switch `routing.mode` to `split` (Routing screen) and add rules with:

- domains (`example.com`, `keyword:ads`, `regex:...`, `geosite:category`)
- IPs (`1.2.3.0/24`, `geoip:cn`)

Each rule targets a profile, a group, `direct`, or `block`.

## LAN sharing

In Settings, enable `allow_lan` (default on) — the inbound listens on `0.0.0.0`
so other devices on your network can use `socks5://<your-ip>:1080` /
`http://<your-ip>:1080`. Optionally enable inbound auth (username/password).

## Run as a service

Keep a chosen config connected across reboots:

```bash
v2raycli --install-service <profile-or-group-id>
```

- **Linux** — writes a systemd *user* unit to
  `~/.config/systemd/user/v2raycli.service`; enable it with
  `systemctl --user enable --now v2raycli`.
- **Termux** — writes a `termux-services` run script to
  `~/.termux/sv/v2raycli/run`; enable with `sv-enable v2raycli`.

Remove it with `v2raycli --uninstall-service`.

## Engine selection

- **sing-box** is the default and serves most protocols plus `latency`/`random`/
  `roundRobin`.
- **xray-core** is used automatically for `ssr` and `leastLoad`.
- Override per profile/group, or change the global default in Settings.

## Troubleshooting

- **Port in use** — change `mixed_port` in Settings.
- **"binary not found"** — binaries download on first use; if download fails,
  set `engines.<name>.binary_path` in the config to a local binary, or
  `"system"` to use one on `PATH`.
- **LAN unreachable** — check the firewall (Windows) and that devices share the
  network.
- **Geo rules silent** — geoip/geosite files download to `geo/`; a manual
  `geoip:`/`geosite:` entry needs the corresponding asset present.
- **VPN client missing** — install `openvpn` / `openconnect` and ensure it's on
  `PATH`.

## Config layout

Config is JSON at `<config-dir>/config.json`. Derived dirs under the same base:

- `runtime/` — generated engine configs and test results
- `bin/` — downloaded engine binaries
- `geo/` — geoip/geosite assets
- `backup/` — automatic config backups

## Development

```bash
pip install -e .[dev]
pytest
```

Live engine verification (downloads sing-box + xray, runs their own config
checks, and exercises the proxy end-to-end):

```bash
python scripts/verify_engines.py
```
