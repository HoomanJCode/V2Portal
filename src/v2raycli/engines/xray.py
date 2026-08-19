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


@register
class XrayAdapter(EngineAdapter):
    name = "xray"
    supported_kinds = frozenset(
        {"vmess", "vless", "trojan", "ss", "ssr", "socks", "http", "wireguard", "manual"}
    )
    supported_strategies = frozenset({"latency", "random", "roundRobin", "leastLoad"})

    def generate(self, settings: "Settings", routing: "RoutingConfig", target: "Target") -> dict:
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

        rules: list[dict] = []
        if routing.mode == "split":
            for rule in normalize_rules(routing, selected):
                rules.append(self._rule(rule))
        rules.append(
            {
                "type": "field",
                "inboundTag": [INBOUND_TAG, HTTP_INBOUND_TAG],
                "outboundTag": selected,
            }
        )

        config: dict = {
            "log": {"loglevel": settings.log_level},
            "inbounds": [inbound, http_inbound],
            "outbounds": outbounds,
            "routing": {"rules": rules, "balancers": balancers},
        }
        if settings.dns:
            config["dns"] = {"servers": settings.dns}
        if target.type == "balancer" and target.strategy in ("latency", "leastLoad"):
            # xray's leastPing/leastLoad balancers require the observatory.
            config["observatory"] = {
                "subjectSelector": [p.id for p in target.profiles],
                "probeURL": settings.test_url,
                "probeInterval": "1m",
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
