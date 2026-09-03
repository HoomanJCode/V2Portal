# v2portal

Non-interactive CLI proxy client for Linux, Windows, and Termux. Wraps
**sing-box** and **xray-core** behind a single config.

---

## What makes v2portal different

### 1 — Smarter load balancing

Most clients offer a static round-robin or random pick. v2portal gives you
adaptive balancing that actually reacts to conditions:

- **Latency** — engines continuously probe outbounds and route to the fastest
  one in real time. If a server slows down, traffic shifts automatically.
- **Least load** — xray's `leastLoad` balancer sends traffic to the server
  with the fewest active connections.
- **Round robin / random** — simple distribution when you don't need
  intelligence.

But the real difference is **how groups work**:

- **Subscriptions are balancers.** Point a routing rule or server at a
  subscription ID and it auto-resolves to a strategy-based balancer over that
  subscription's *current* profiles. Update the subscription and every
  target that references it picks up the new nodes — no manual reconfiguration.
- **Groups can nest.** A balancer can contain other balancers, chains,
  subscriptions, and servers. Members resolve recursively with dedup and
  cycle detection. Build complex topologies without worrying about
  circular references.

```bash
# Create a latency balancer over two profiles
v2portal group add balancer fast PROFILE_A PROFILE_B --strategy latency

# Use a subscription as a target — it becomes a balancer automatically
v2portal routing add proxy --domain netflix.com --target SUBSCRIPTION_ID

# Nest a chain inside a balancer
v2portal group add chain chained GROUP_BALANCER PROFILE_C

# See the full hierarchy
v2portal group tree
```

### 2 — Multiple servers on one device

A typical proxy client runs one inbound on one port. v2portal lets you run
**as many inbound servers as you want**, each on its own port, each forwarding
to a different outbound. Every server is a separate engine process that runs
in the background and survives terminal close.

Real use case — one laptop exposing four inbounds simultaneously:

| Port | Server name | Outbound |
|------|-------------|----------|
| 1080 | US proxy | Subscription (balanced across US nodes) |
| 1081 | Berlin direct | A single Berlin profile |
| 1082 | Latency group | Balancer group (auto-picks fastest) |
| 1083 | HTTP only | Same group, HTTP-only inbound |

Each server can optionally have its own username/password auth. Other devices
on your network connect to whichever port they need.

```bash
v2portal server add --port 1080 SUBSCRIPTION_ID --name 'US proxy'
v2portal server add --port 1081 BERLIN_PROFILE_ID --name 'Berlin direct'
v2portal server add --port 1082 GROUP_ID --name 'Latency group'
v2portal server add --port 1083 GROUP_ID --protocol http --name 'HTTP only'

v2portal server start --all
v2portal server list
```

### 3 — Split routing across multiple outbounds

Most clients route all traffic through one proxy. v2portal lets you **route
different traffic through different outbounds** based on rules that match
domains, IPs, or geo data. Rules can target any reference — profile,
subscription, group, or server — not just the default outbound.

```bash
v2portal routing mode split

# Streaming through a US profile
v2portal routing add proxy --domain youtube.com --target US_PROFILE_ID
v2portal routing add proxy --domain netflix.com --target US_PROFILE_ID

# Gaming through a low-latency balancer
v2portal routing add proxy --domain epicgames.com --target BALANCER_GROUP_ID
v2portal routing add proxy --domain fortnite.com --target BALANCER_GROUP_ID

# Corporate traffic through a dedicated server
v2portal routing add proxy --domain intranet.corp --target SERVER_ID

# Local and private traffic — bypass the proxy
v2portal routing add direct --ip 192.168.0.0/16
v2portal routing add direct --geoip cn --geoip private

# Block ads globally
v2portal routing add block --geosite category-ads-all

# First match wins — reorder as needed
v2portal routing list
v2portal routing move RULE_ID up
```

**Match types:** domain (exact / keyword / regex / geosite), IP/CIDR, geoip.
Rules auto-clean when their target profile, group, or server is deleted.

---

## Other features

- **Dual engine** — sing-box (default) + xray-core. xray is used automatically
  for `ssr` and `leastLoad`. Override per profile or globally.
- **Subscriptions** — URL, file, or paste import. Deleted upstream nodes are
  pruned on update. Auto-update on a configurable schedule.
- **Protocols** — vmess, vless, trojan, ss, ssr, socks, http, wireguard,
  hysteria2, tuic, raw JSON. OpenVPN / OpenConnect via system clients.
- **Chaining** — route traffic through an ordered sequence of proxies.
- **Traffic stats** — cumulative up/down bytes per profile (sing-box Clash API).
- **Outbound testing** — `test latency`, `test endpoint`, `test websocket`.
- **Config** — single JSON file. Automatic rolling backups, full export/import,
  share-link export/import.
- **Service** — systemd (Linux), termux-services (Termux), launchd (macOS).
  Keeps servers running across reboots.
- **Health checks** — `v2portal health` shows subscription expiry and traffic.
- **Windows Firewall** — `v2portal settings firewall allow sing-box` adds an
  outbound rule so engine binaries can reach remote servers.

---

## Install

```bash
pip install v2portal
# or, with pipx:
pipx install v2portal
```

From source:

```bash
git clone https://github.com/HoomanJCode/V2Portal.git
pip install -e "V2Portal[dev]"
```

Termux:

```bash
pkg update && pkg install python
pip install v2portal
```

Engine binaries download automatically on first use.

---

## Quickstart

```bash
# Import a subscription
v2portal subscription add my-provider https://example.com/sub

# List everything
v2portal profile list
v2portal subscription list
v2portal group list
v2portal group tree

# Test latency of all profiles
v2portal test latency all

# Start a server
v2portal server add --port 1080 SUBSCRIPTION_ID --name 'My proxy'
v2portal server start --all
```

### One ID space

Profiles, subscriptions, groups, and servers share a single ID counter.
Any command that takes a target auto-detects the type — no `--profile` /
`--group` / `--subscription` flags.

```bash
v2portal routing add proxy --domain netflix.com --target 3f2b
# ^ could be a profile, subscription, group, or server — auto-detected
```

### Command tree

```text
profile       list | add link|raw|socks|http|wireguard|hysteria2|tuic|openvpn|openconnect|server |
               rename | edit | remove | export
subscription  list | add | edit | rename | update [--all] | remove
group         list | add balancer|chain | tree | edit | remove |
               add-member | remove-member | add-sub | remove-sub
server        list | add --port PORT [REF] [--protocol mixed|socks|http] [--direct] |
               start [--all] | stop [--all] | restart [--all] | edit | remove
routing       list | mode all|split | add proxy|direct|block | move | enable | disable | remove
settings      listen | mixed-port | socks-port | http-port | allow-lan | dns |
               log-level | test-url | default-engine | backup-keep | traffic-api |
               traffic-api-port | subscription-proxy |
               backup create|list|restore |
               service install|uninstall |
               firewall allow|remove|list (Windows) |
               engine update sing-box|xray|both
test          latency | endpoint | websocket
status        show config summary [--json]
health        show subscription expiry and traffic [--json]
```

---

## Development

```bash
git clone https://github.com/HoomanJCode/V2Portal.git
pip install -e "V2Portal[dev]"
pytest
python scripts/verify_acceptance.py --json
```

## Documentation

- **PLAN.md** — architecture, decisions, data model, and config mapping.

## Config

JSON at `<platform config dir>/v2portal/config.json`.

- `runtime/` — generated engine configs, test results, server state
- `bin/` — downloaded engine binaries
- `geo/` — geoip/geosite assets (xray)
- `backup/` — automatic config backups

### Schema

- **settings** — listen, ports, auth, DNS, log level, test URL, default engine,
  backup count, traffic API, subscription proxy.
- **routing** — `mode` (all|split) and ordered rules (proxy|direct|block by
  domain/IP/geo).
- **engines** — per-engine binary path (`auto`/`system`/custom path) and version.
- **profiles** — one concrete outbound or VPN (vmess/vless/trojan/ss/ssr/socks/http/
  wireguard/hysteria2/tuic/manual/openvpn/openconnect).
- **subscriptions** — URL + list of profile IDs, auto-update schedule.
- **groups** — balancer (latency/random/roundRobin/leastLoad) or chain; members
  can be profiles, subscriptions, nested groups, or servers.
- **servers** — persistent inbound (mixed/socks/http) on a port, forwarding to
  a profile/subscription/group/server/direct.
