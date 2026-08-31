"""xray-core config generator."""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

from ..routing.rules import normalize_rules
from .base import EngineAdapter, register

if TYPE_CHECKING:
    from ..models import RoutingConfig, Settings
    from ..outbounds.groups import Target

INBOUND_TAG = "mixed-in"
HTTP_INBOUND_TAG = "http-in"
SOCKS_INBOUND_TAG = "socks-in"
DEDICATED_HTTP_INBOUND_TAG = "http-dedicated-in"
BALANCER_TAG = "balancer"

_KIND_PROTOCOL = {
    "vmess": "vmess",
    "vless": "vless",
    "trojan": "trojan",
    "ss": "shadowsocks",
    "ssr": "shadowsocksr",
    "socks": "socks",
    "http": "http",
    "wireguard": "wireguard",
}

_STRATEGY = {
    "latency": "leastPing",
    "random": "random",
    "roundRobin": "roundRobin",
    "leastLoad": "leastLoad",
}


def _validate_vnext(profile) -> None:
    settings = profile.outbound.get("settings")
    if not isinstance(settings, dict):
        raise ValueError(f"{profile.kind} outbound is missing settings")
    vnext = settings.get("vnext")
    if not isinstance(vnext, list) or not vnext or not isinstance(vnext[0], dict):
        raise ValueError(f"{profile.kind} outbound is missing settings.vnext")
    server = vnext[0]
    if not isinstance(server.get("address"), str) or not server["address"].strip():
        raise ValueError(f"{profile.kind} outbound is missing a server address")
    port = server.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError(f"{profile.kind} outbound has an invalid server port")
    users = server.get("users")
    if not isinstance(users, list) or not users or not isinstance(users[0], dict):
        raise ValueError(f"{profile.kind} outbound is missing a user")
    if not isinstance(users[0].get("id"), str) or not users[0]["id"].strip():
        raise ValueError(f"{profile.kind} outbound user is missing an id")


def _validate_servers(profile) -> None:
    settings = profile.outbound.get("settings")
    if not isinstance(settings, dict):
        raise ValueError(f"{profile.kind} outbound is missing settings")
    servers = settings.get("servers")
    if not isinstance(servers, list) or not servers or not isinstance(servers[0], dict):
        raise ValueError(f"{profile.kind} outbound is missing a server")
    server = servers[0]
    if not isinstance(server.get("address"), str) or not server["address"].strip():
        raise ValueError(f"{profile.kind} outbound is missing a server address")
    port = server.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError(f"{profile.kind} outbound has an invalid server port")


def _validate_wireguard_network(value, label: str, *, interface: bool = False) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"wireguard {label} must be a CIDR")
    try:
        if interface:
            ipaddress.ip_interface(value)
        else:
            ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise ValueError(f"wireguard {label} must be a CIDR") from exc


def _validate_wireguard_endpoint(endpoint) -> None:
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ValueError("wireguard peer endpoint must be host:port")
    value = endpoint.strip()
    if value.startswith("["):
        end = value.find("]")
        host = value[1:end] if end > 1 else ""
        port_text = value[end + 2 :] if end >= 0 and value[end + 1 :].startswith(":") else ""
    else:
        host, separator, port_text = value.rpartition(":")
        if not separator:
            host, port_text = "", ""
    try:
        port = int(port_text)
    except (TypeError, ValueError) as exc:
        raise ValueError("wireguard peer endpoint must be host:port") from exc
    if not host.strip() or not 1 <= port <= 65535:
        raise ValueError("wireguard peer endpoint must be host:port")


def _validate_wireguard(profile) -> None:
    settings = profile.outbound.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("wireguard outbound is missing settings")
    private_key = settings.get("secretKey")
    if not isinstance(private_key, str) or not private_key.strip():
        raise ValueError("wireguard private key is required")
    address = settings.get("address")
    if not isinstance(address, list) or not address:
        raise ValueError("wireguard address list is required")
    for item in address:
        _validate_wireguard_network(item, "address", interface=True)
    peers = settings.get("peers")
    if not isinstance(peers, list) or not peers:
        raise ValueError("wireguard requires at least one peer")
    for peer in peers:
        if not isinstance(peer, dict):
            raise ValueError("wireguard peer must be an object")
        public_key = peer.get("publicKey")
        if not isinstance(public_key, str) or not public_key.strip():
            raise ValueError("wireguard peer public key is required")
        _validate_wireguard_endpoint(peer.get("endpoint"))
        allowed = peer.get("allowedIps")
        if not isinstance(allowed, list) or not allowed:
            raise ValueError("wireguard peer allowed IPs are required")
        for item in allowed:
            _validate_wireguard_network(item, "peer allowed IP")
    mtu = settings.get("mtu")
    if mtu is not None and (isinstance(mtu, bool) or not isinstance(mtu, int) or not 576 <= mtu <= 65535):
        raise ValueError("wireguard MTU must be between 576 and 65535")


def _validate_stream_settings(profile) -> None:
    stream = profile.outbound.get("streamSettings")
    if stream is None:
        return
    if not isinstance(stream, dict):
        raise ValueError("streamSettings must be an object")
    network = stream.get("network")
    if network is not None and not isinstance(network, str):
        raise ValueError("streamSettings network must be text")

    for key in ("tlsSettings", "realitySettings", "wsSettings", "grpcSettings", "httpSettings"):
        value = stream.get(key)
        if value is not None and not isinstance(value, dict):
            raise ValueError(f"{key} must be an object")

    ws = stream.get("wsSettings")
    if isinstance(ws, dict) and "headers" in ws and not isinstance(ws["headers"], dict):
        raise ValueError("WebSocket headers must be an object")

    grpc = stream.get("grpcSettings")
    if isinstance(grpc, dict) and "serviceName" in grpc and not isinstance(grpc["serviceName"], str):
        raise ValueError("gRPC serviceName must be text")

    http = stream.get("httpSettings")
    if isinstance(http, dict) and "host" in http and not isinstance(http["host"], list):
        raise ValueError("HTTP/2 host must be a list")

    tls = stream.get("tlsSettings")
    if isinstance(tls, dict):
        if "serverName" in tls and not isinstance(tls["serverName"], str):
            raise ValueError("TLS serverName must be text")
        if "alpn" in tls and not isinstance(tls["alpn"], list):
            raise ValueError("TLS alpn must be a list")


def _validate_settings(settings) -> None:
    listen = getattr(settings, "listen", None)
    if not isinstance(listen, str) or not listen.strip():
        raise ValueError("xray listen address is required")
    if not isinstance(getattr(settings, "allow_lan", None), bool):
        raise ValueError("xray allow_lan must be boolean")

    mixed_port = getattr(settings, "mixed_port", None)
    if isinstance(mixed_port, bool) or not isinstance(mixed_port, int) or not 1 <= mixed_port <= 65534:
        raise ValueError("xray mixed_port must be between 1 and 65534")

    auth = getattr(settings, "inbound_auth", None)
    if not isinstance(auth, dict):
        raise ValueError("xray inbound_auth must be an object")
    enabled = auth.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("xray inbound_auth.enabled must be boolean")
    if enabled:
        for field in ("username", "password"):
            value = auth.get(field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"xray inbound_auth.{field} is required")

    dns = getattr(settings, "dns", None)
    if not isinstance(dns, list):
        raise ValueError("xray DNS servers must be a list")
    for server in dns:
        if not isinstance(server, str) or not server.strip():
            raise ValueError("xray DNS servers must contain non-empty text")


@register
class XrayAdapter(EngineAdapter):
    name = "xray"
    supported_kinds = frozenset(
        {"vmess", "vless", "trojan", "ss", "ssr", "socks", "http", "wireguard", "manual"}
    )
    supported_strategies = frozenset({"latency", "random", "roundRobin", "leastLoad"})

    def generate(self, settings: "Settings", routing: "RoutingConfig", target: "Target") -> dict:
        _validate_settings(settings)
        outbounds = [
            {"tag": "direct", "protocol": "freedom", "settings": {}},
            {"tag": "block", "protocol": "blackhole", "settings": {}},
        ]
        for idx, profile in enumerate(target.profiles):
            outbound = self._outbound_for(profile)
            if target.type == "chain" and idx > 0:
                outbound["proxySettings"] = {
                    "tag": target.profiles[idx - 1].id,
                    "transportLayer": False,
                }
            outbounds.append(outbound)

        # Direct mode: no profiles → route straight to the direct outbound.
        if not target.profiles:
            selected = "direct"
        else:
            selected = target.profiles[-1].id if target.type == "chain" else target.profiles[0].id
        balancers: list[dict] = []
        if target.type == "balancer":
            balancers.append(
                {
                    "tag": BALANCER_TAG,
                    "selector": [p.id for p in target.profiles],
                    "strategy": {"type": _STRATEGY[target.strategy]},
                }
            )
            selected = BALANCER_TAG

        # Emit outbounds and constructs for profiles/groups referenced by
        # split-routing rules that aren't part of the main target.
        main_ids = {p.id for p in target.profiles}
        extra_added: set[str] = set()
        for profile in target.extra_profiles:
            if profile.id in main_ids or profile.id in extra_added:
                continue
            outbound = self._outbound_for(profile)
            outbound["tag"] = profile.id
            outbounds.append(outbound)
            extra_added.add(profile.id)
        for group in target.extra_groups:
            if group.id in extra_added:
                continue
            member_ids = [pid for pid in group.profile_ids if pid in main_ids or pid in extra_added]
            if not member_ids:
                continue
            if group.type == "balancer":
                strategy_type = _STRATEGY.get(group.strategy, "random")
                balancers.append(
                    {
                        "tag": group.id,
                        "selector": member_ids,
                        "strategy": {"type": strategy_type},
                    }
                )
            elif group.type == "chain":
                for idx, pid in enumerate(member_ids):
                    if idx > 0:
                        ob = next((o for o in outbounds if o.get("tag") == pid), None)
                        if ob is not None:
                            ob["proxySettings"] = {
                                "tag": member_ids[idx - 1],
                                "transportLayer": False,
                            }
            extra_added.add(group.id)

        listen = settings.listen if settings.allow_lan else "127.0.0.1"
        http_port = settings.mixed_port + 1
        if http_port > 65535:
            raise ValueError("xray HTTP inbound requires mixed_port below 65535")
        inbound = {
            "tag": INBOUND_TAG,
            "listen": listen,
            "port": settings.mixed_port,
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True},
        }
        http_inbound = {
            "tag": HTTP_INBOUND_TAG,
            "listen": listen,
            "port": http_port,
            "protocol": "http",
            "settings": {},
        }
        if settings.inbound_auth.get("enabled"):
            accounts = [
                {
                    "user": settings.inbound_auth["username"],
                    "pass": settings.inbound_auth["password"],
                }
            ]
            inbound["settings"] = {
                "auth": "password",
                "udp": True,
                "accounts": accounts,
            }
            http_inbound["settings"] = {"accounts": accounts}

        inbounds = [inbound, http_inbound]
        inbound_tags = [INBOUND_TAG, HTTP_INBOUND_TAG]
        if getattr(settings, "socks_port", 0):
            extra_socks = {
                "tag": SOCKS_INBOUND_TAG,
                "listen": listen,
                "port": settings.socks_port,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True},
            }
            if settings.inbound_auth.get("enabled"):
                extra_socks["settings"] = {
                    "auth": "password",
                    "udp": True,
                    "accounts": accounts,
                }
            inbounds.append(extra_socks)
            inbound_tags.append(SOCKS_INBOUND_TAG)
        if getattr(settings, "http_port", 0):
            extra_http = {
                "tag": DEDICATED_HTTP_INBOUND_TAG,
                "listen": listen,
                "port": settings.http_port,
                "protocol": "http",
                "settings": {},
            }
            if settings.inbound_auth.get("enabled"):
                extra_http["settings"] = {"accounts": accounts}
            inbounds.append(extra_http)
            inbound_tags.append(DEDICATED_HTTP_INBOUND_TAG)

        rules: list[dict] = []
        if routing.mode == "split":
            known_ids: set[str] = {"direct", "block"}
            known_ids.update(p.id for p in target.profiles)
            known_ids.update(p.id for p in target.extra_profiles)
            known_ids.update(g.id for g in target.extra_groups)
            for rule in normalize_rules(routing, selected, known_target_ids=known_ids):
                rules.append(self._rule(rule))
        rules.append(
            {
                "type": "field",
                "inboundTag": inbound_tags,
                "outboundTag": selected,
            }
        )

        config: dict = {
            "log": {"loglevel": settings.log_level},
            "inbounds": inbounds,
            "outbounds": outbounds,
            "routing": {"rules": rules, "balancers": balancers},
        }
        if settings.dns:
            config["dns"] = {"servers": settings.dns}
        if target.type == "balancer" and target.strategy in ("latency", "leastLoad"):
            # xray's leastPing balancer requires the observatory; probeInterval
            # is used for both health and failover cadence. When failover is on
            # we probe at the configured interval and drop/flag dead nodes so
            # leastPing switches to a healthy peer quickly.
            probe_interval = (
                f"{target.health_interval}s" if target.health_interval else "1m"
            )
            config["observatory"] = {
                "subjectSelector": [p.id for p in target.profiles],
                "probeURL": settings.test_url,
                "probeInterval": probe_interval,
            }
        return config

    def _outbound_for(self, profile) -> dict:
        if not isinstance(profile.outbound, dict):
            raise ValueError(f"{profile.kind} outbound must be an object")
        if profile.kind == "manual":
            protocol = profile.outbound.get("protocol")
            if not isinstance(protocol, str) or not protocol:
                raise ValueError("manual outbound is missing its protocol")
            if protocol not in _KIND_PROTOCOL.values():
                raise ValueError(f"xray does not support manual protocol {protocol}")
            outbound = dict(profile.outbound)
            outbound["tag"] = profile.id
            return outbound
        protocol = _KIND_PROTOCOL.get(profile.kind)
        if protocol is None:
            raise ValueError(f"xray does not support kind {profile.kind}")
        if profile.kind in ("vmess", "vless"):
            _validate_vnext(profile)
        else:
            settings = profile.outbound.get("settings")
            if not isinstance(settings, dict):
                raise ValueError(f"{profile.kind} outbound is missing settings")
            if profile.kind in {"trojan", "ss", "ssr", "socks", "http"}:
                _validate_servers(profile)
            elif profile.kind == "wireguard":
                _validate_wireguard(profile)
        _validate_stream_settings(profile)
        outbound = dict(profile.outbound)
        outbound["tag"] = profile.id
        outbound["protocol"] = protocol
        return outbound

    def _rule(self, rule) -> dict:
        field: dict = {}
        domains = list(rule.match.get("domains", []))
        domains += [f"geosite:{g}" for g in rule.match.get("geosite", [])]
        ips = list(rule.match.get("ips", []))
        ips += [f"geoip:{g}" for g in rule.match.get("geoip", [])]
        if domains:
            field["domain"] = domains
        if ips:
            field["ip"] = ips
        if rule.action == "direct":
            field["outboundTag"] = "direct"
        elif rule.action == "block":
            field["outboundTag"] = "block"
        else:
            field["outboundTag"] = rule.target_id
        return {"type": "field", **field}

    def run_args(self, config_path: str) -> list[str]:
        return ["run", "-config", config_path]

    def validate_args(self, config_path: str) -> list[str]:
        return ["run", "-test", "-config", config_path]

    def binary_filename(self, platform: str, arch: str) -> str:
        return "xray.exe" if platform == "windows" else "xray"
