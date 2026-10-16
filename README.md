# v2portal — Cross-Platform V2Ray CLI Proxy Client

> **Experimental / laboratory use only.** This project is under active development and
> its behavior, commands, and configuration format can change between releases.
> Do not rely on it in production or for network traffic you cannot afford to lose.

[![CI](https://github.com/HoomanJCode/V2Portal/actions/workflows/ci.yml/badge.svg)](https://github.com/HoomanJCode/V2Portal/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/v2portal)](https://pypi.org/project/v2portal/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue?logo=python&logoColor=white)](https://www.python.org/)

**v2portal is a headless, cross-platform V2Ray CLI client and proxy manager for
sing-box and Xray-core.** Manage VLESS, VMess, Trojan, Shadowsocks, SOCKS5,
HTTP, WireGuard, Hysteria2, and TUIC profiles; import proxy subscriptions and
share links; create proxy groups and chains; and run persistent LAN proxy
servers with rule-based split routing.

It runs on **Linux, Windows, macOS, and Termux**, stores configuration locally
as JSON, and provides one scriptable command-line interface instead of a GUI.

> v2portal manages proxy connections and exposes local inbounds. It does not
> change the operating system's global proxy settings or routing table.

## Why v2portal?

- **One V2Ray CLI for two engines** — use sing-box by default and Xray-core
  when a protocol or balancing strategy requires it.
- **Subscription manager** — import a URL, local file, or pasted subscription;
  decode supported share links into profiles; update nodes; and remove nodes
  that disappear upstream.
- **Persistent proxy servers** — run multiple SOCKS5, HTTP, or mixed
  SOCKS5+HTTP inbounds at the same time, each on its own port and forwarding to
  a different outbound.
- **Proxy groups and load balancing** — combine profiles, subscriptions,
  nested groups, and other servers into latency, random, round-robin, or
  least-load groups.
- **Proxy chaining** — send traffic through an ordered sequence of proxy hops.
- **Split routing / split tunneling** — route domains, IP ranges, geo-IP, and
  geo-site matches through different profiles, groups, or servers; bypass or
  block selected traffic.
- **Testing and health** — check endpoint reachability, measure proxy latency,
  test WebSocket handshakes, and inspect subscription expiry and traffic data.
- **Safe local configuration** — automatic rolling backups plus full-config and
  share-link export/import.
- **Automation-friendly** — non-interactive commands, JSON output for several
  list/status commands, and optional Linux, macOS, or Termux boot services.

## Supported protocols

| Protocol | Import / use | Engine |
| --- | --- | --- |
| VLESS | Share links and profiles | sing-box or Xray-core |
| VMess | Share links and profiles | sing-box or Xray-core |
| Trojan | Share links and profiles | sing-box or Xray-core |
| Shadowsocks (SS) | Share links and profiles | sing-box or Xray-core |
| ShadowsocksR (SSR) | Share links and profiles | Xray-core |
| SOCKS5 | Share links and manual profiles | sing-box or Xray-core |
| HTTP proxy | Share links and manual profiles | sing-box or Xray-core |
| WireGuard | Share links and manual profiles | sing-box or Xray-core |
| Hysteria2 | Share links and manual profiles | sing-box |
| TUIC | Share links and manual profiles | sing-box |
| OpenVPN | `.ovpn` config or inline config | System `openvpn` client |
| Cisco AnyConnect | Server profile | System `openconnect` client |

Engine binaries are downloaded automatically when needed. You can also select
an installed binary or configure a custom path.

## Installation

### Install from PyPI

Requires **Python 3.10 or newer**.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue?logo=python&logoColor=white)](https://www.python.org/)

```bash
python -m pip install v2portal
```

For an isolated command-line installation, use pipx:

```bash
pipx install v2portal
```

### Install from source

```bash
git clone https://github.com/HoomanJCode/V2Portal.git
cd V2Portal
python -m pip install -e ".[dev]"
```

### Termux

```bash
pkg update
pkg install python
python -m pip install v2portal
```

OpenVPN and OpenConnect profiles require the corresponding system client to be
installed separately. All other supported proxy engines are managed by
v2portal.

## Quick start

### 1. Import a V2Ray subscription

```bash
v2portal subscription add my-provider https://example.com/subscription
v2portal subscription list
v2portal profile list
```

The command prints the new subscription ID and imports its proxy nodes as
profiles. The same subscription can be refreshed later:

```bash
v2portal subscription refresh SUBSCRIPTION_ID
# or update every enabled subscription
v2portal subscription refresh --all
```

You can also add an individual V2Ray share link directly:

```bash
v2portal profile add link 'vless://UUID@example.com:443?security=tls&type=ws#my-node'
v2portal profile add link 'vmess://BASE64_PAYLOAD' --name 'US node'
```

### 2. Create and start a local proxy server

A server is a persistent local inbound that forwards traffic to a profile,
subscription, group, another server, or directly to the internet.

```bash
# Replace SUBSCRIPTION_ID with the ID printed above.
v2portal server add --port 1080 SUBSCRIPTION_ID --name 'Balanced proxy'
v2portal server start SERVER_ID
v2portal server list --running
```

The default `mixed` inbound accepts both SOCKS5 and HTTP connections on the
same port. Other devices on the LAN can connect to the host at:

```text
SOCKS5:  <host-ip>:1080
HTTP:    http://<host-ip>:1080
```

Run several proxy servers simultaneously by giving each one a different port:

```bash
v2portal server add --port 1081 PROFILE_ID --protocol socks --name 'Single node'
v2portal server add --port 1082 GROUP_ID --protocol http --name 'HTTP group'
v2portal server start --all
```

Use `v2portal server stop SERVER_ID` to stop one server or
`v2portal server stop --all` to stop every running server.

Multi-node subscription and group servers enable health-based failover by
default, probing every 10 seconds. Set `--failover 0` for the engine default,
`--failover N` for a custom interval, or `--failover -1` to disable it. With
failover enabled, `random` and `roundRobin` server targets use latency-based
selection so unhealthy nodes can be skipped and rejoin after recovery. Existing
connections through a failed node may still need to be retried by the client.

### 3. Create a proxy group

IDs are automatically detected as profile, subscription, group, or server IDs.
Subscriptions and nested groups are resolved dynamically, so refreshed nodes
flow into a group without rebuilding it.

```bash
# Latency-based balancing through the fastest available profile.
v2portal group add balancer fast PROFILE_A PROFILE_B --strategy latency

# A subscription is expanded into a dynamic balancer target.
v2portal group add balancer provider SUBSCRIPTION_ID --strategy latency

# Send traffic through ordered proxy hops.
v2portal group add chain tunnel PROFILE_A PROFILE_B

v2portal group tree
```

Available balancing strategies are `latency`, `random`, `roundRobin`, and
`leastLoad`. The `leastLoad` strategy uses Xray-core; sing-box-only protocols
cannot be used with strategies that require Xray-core.

### 4. Configure split routing

Routing is `all` by default. In `split` mode, the first matching rule wins.
Rules can proxy, bypass, or block traffic based on domains, IP/CIDR ranges,
geo-IP lists, and geo-site lists.

```bash
v2portal route mode split

# Route streaming through one proxy target.
v2portal route add proxy --domain youtube.com --target PROFILE_ID
v2portal route add proxy --domain netflix.com --target GROUP_ID

# Bypass private networks.
v2portal route add direct --ip 192.168.0.0/16
v2portal route add direct --geoip private

# Block advertising domains using a geo-site list.
v2portal route add block --geosite category-ads-all

v2portal route list
```

Domain matchers support exact domains plus `keyword:` and `regex:` prefixes.
Use `route move RULE_ID up|down` to change rule priority. `routing` remains an
accepted alias for `route`.

## Common commands

```text
config        validate | export | import
profile       list | add | rename | edit | remove | export
subscription  list | add | refresh | edit | remove
group         list | add | member add | member remove | tree | edit | remove
server        list | add | start | stop | restart | edit | remove
route         list | mode | add | move | enable | disable | remove
settings      show | get KEY | set KEY VALUE
backup        create | list | restore
engine        update
service       install | uninstall
firewall      allow | remove | list
test          latency | endpoint | websocket
status        show a configuration summary
health        show subscription expiry and traffic usage
```

Every command provides detailed help:

```bash
v2portal --help
v2portal subscription --help
v2portal server add --help
v2portal route add --help
```

### Useful examples

```bash
# Add a manual SOCKS5 or HTTP proxy.
v2portal profile add socks office 127.0.0.1 1080
v2portal profile add http upstream proxy.example.com 8080

# Test all profiles, a subscription, or a group.
v2portal test endpoint all
v2portal test latency SUBSCRIPTION_ID
v2portal test websocket GROUP_ID

# Get machine-readable output.
v2portal status --json
v2portal profile list --json
v2portal subscription list --json
v2portal server list --json

# Install a boot service for enabled servers.
v2portal service install

# Manage group members with a nested action.
v2portal group member add GROUP_ID PROFILE_OR_GROUP_ID
v2portal group member remove GROUP_ID PROFILE_OR_GROUP_ID

# Validate and transfer the full configuration.
v2portal settings show
v2portal settings get default-engine
v2portal settings set default-engine sing-box
v2portal config validate
v2portal config export ./v2portal-config.json --redact
v2portal config import ./v2portal-config.json --mode merge
```

## Configuration and data storage

The configuration is stored in a platform-specific application directory:

- **Linux / Termux:** `~/.config/v2portal/`
- **Windows:** `%APPDATA%\\v2portal\\`
- **macOS:** the platform directory returned by `platformdirs`

Important data includes:

- `config.json` — settings, profiles, subscriptions, groups, servers, and
  routing rules.
- `runtime/` — generated engine configs, process state, and test runtime data.
- `bin/` — automatically downloaded sing-box and Xray-core binaries.
- `geo/` — geo-IP and geo-site assets when required by routing.
- `backup/` — timestamped rolling configuration backups.

The configuration contains proxy credentials, UUIDs, passwords, and keys. Keep
its directory private and use redacted exports when sharing configuration.
When exposing a server to a LAN, enable inbound authentication if the network
is not fully trusted.

Useful settings include:

```bash
v2portal settings set listen 0.0.0.0
v2portal settings set mixed-port 1080
v2portal settings set allow-lan true
v2portal settings set default-engine sing-box
v2portal settings set backup-keep 10
v2portal settings set subscription-proxy socks5://127.0.0.1:1080
```

## Development

```bash
git clone https://github.com/HoomanJCode/V2Portal.git
cd V2Portal
python -m pip install -e ".[dev]"
python -m pytest
python scripts/verify_acceptance.py --json
```

The project uses Python 3.10+, `argparse`, `httpx`, `platformdirs`, and the
sing-box/Xray adapter layer. The data model is defined in
[`src/v2portal/models.py`](src/v2portal/models.py); architecture and engine
mapping details are documented in [`PLAN.md`](PLAN.md).

## Frequently asked questions

### Is v2portal a V2Ray GUI client?

No. v2portal is a non-interactive V2Ray command-line client designed for
terminals, automation, servers, home labs, and LAN proxy sharing. It does not
provide a desktop GUI or alter system-wide proxy settings.

### Is v2portal compatible with sing-box and Xray?

Yes. sing-box is the default engine. Xray-core is selected automatically for
Xray-only protocols and compatible strategies, or can be selected explicitly.

### Can I use a V2Ray subscription URL?

Yes. `subscription add` accepts HTTP(S) URLs as well as `file://` and
`paste://` sources. The subscription parser decodes supported V2Ray share-link
formats and stores each node as a manageable profile.

### Can I run more than one local proxy port?

Yes. Each configured server has its own inbound port and engine process. Start
all enabled servers with `v2portal server start --all`.

### Does it support split tunneling?

It supports rule-based split routing inside the managed proxy servers. You can
send selected domains, IP ranges, or geo categories through a proxy, directly,
or to a block rule. It does not configure the host operating system's routing
table.

## Project links

- [Source code](https://github.com/HoomanJCode/V2Portal)
- [PyPI package](https://pypi.org/project/v2portal/)
- [Architecture and configuration plan](PLAN.md)
- [Issue tracker](https://github.com/HoomanJCode/V2Portal/issues)

## License

See the repository for the current license and contribution terms.
