"""sing-box config generator.

Profiles store xray-style outbound objects for protocols xray supports; this
adapter translates those to sing-box outbounds. sing-box-only kinds
(hysteria2/tuic) already store sing-box-style fields and pass through.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..routing.rules import normalize_rules
from .base import EngineAdapter, register

if TYPE_CHECKING:
    from ..models import RoutingConfig, Settings
    from ..outbounds.groups import Target

INBOUND_TAG = "mixed-in"
BALANCER_TAG = "balancer"


def _first_server(profile) -> dict:
    settings = profile.outbound.get("settings", {})
    servers = settings.get("servers") or settings.get("vnext")
    return servers[0] if servers else {}


def _split_endpoint(endpoint: str) -> tuple[str, int]:
    if not endpoint:
        return "", 0
    if endpoint.startswith("["):  # IPv6 [::1]:443
        host, _, rest = endpoint[1:].partition("]")
        return host, int(rest.lstrip(":") or 0)
    host, _, port = endpoint.rpartition(":")
    return host, int(port or 0)


def _tls(stream: dict) -> dict | None:
    if stream.get("security") != "tls":
        return None
    tls = stream.get("tlsSettings", {})
    obj: dict = {"enabled": True}
    if tls.get("serverName"):
        obj["server_name"] = tls["serverName"]
    if tls.get("alpn"):
        obj["alpn"] = tls["alpn"]
    if tls.get("allowInsecure"):
        obj["insecure"] = True
    if tls.get("fingerprint"):
        obj["utls"] = {"enabled": True, "fingerprint": tls["fingerprint"]}
    return obj


def _transport(stream: dict) -> dict | None:
    net = stream.get("network", "tcp")
    if net == "ws":
        ws = stream.get("wsSettings", {})
        obj: dict = {"type": "ws"}
        if ws.get("path"):
            obj["path"] = ws["path"]
        headers = ws.get("headers") or {}
        if headers.get("Host"):
            obj["headers"] = {"Host": headers["Host"]}
        return obj
    if net == "grpc":
        obj = {"type": "grpc"}
        service_name = (stream.get("grpcSettings") or {}).get("serviceName")
        if service_name:
            obj["service_name"] = service_name
        return obj
    if net == "h2":
        http = stream.get("httpSettings", {})
        obj = {"type": "http"}
        if http.get("path"):
            obj["path"] = http["path"]
        if http.get("host"):
            obj["host"] = http["host"]
        return obj
    return None


@register
class SingBoxAdapter(EngineAdapter):
    name = "sing-box"
    supported_kinds = frozenset(
        {"vmess", "vless", "trojan", "ss", "socks", "http", "wireguard", "hysteria2", "tuic"}
    )
    supported_strategies = frozenset({"latency", "random", "roundRobin"})

    def generate(self, settings: "Settings", routing: "RoutingConfig", target: "Target") -> dict:
        outbounds = [
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"},
        ]
        for idx, profile in enumerate(target.profiles):
            outbound = self._outbound_for(profile)
            outbound["tag"] = profile.id
            if target.type == "chain" and idx > 0:
                outbound["detour"] = target.profiles[idx - 1].id
            outbounds.append(outbound)

        selected = target.profiles[-1].id if target.type == "chain" else target.profiles[0].id
        if target.type == "balancer":
            tags = [p.id for p in target.profiles]
            if target.strategy == "latency":
                outbounds.append({"type": "urltest", "tag": BALANCER_TAG, "outbounds": tags})
            else:
                outbounds.append(
                    {"type": "selector", "tag": BALANCER_TAG, "outbounds": tags, "default": tags[0]}
                )
            selected = BALANCER_TAG

        inbound: dict = {
            "type": "mixed",
            "tag": INBOUND_TAG,
            "listen": settings.listen,
            "listen_port": settings.mixed_port,
        }
        if settings.inbound_auth.get("enabled"):
            inbound["users"] = [
                {"username": settings.inbound_auth["username"], "password": settings.inbound_auth["password"]}
            ]

        rules: list[dict] = []
        if routing.mode == "split":
            for rule in normalize_rules(routing, selected):
                rules.append(self._rule(rule, selected))

        config: dict = {
            "log": {"level": settings.log_level},
            "inbounds": [inbound],
            "outbounds": outbounds,
            "route": {"rules": rules, "final": selected},
        }
        if settings.dns:
            # sing-box >= 1.12 uses the typed DNS server format and requires a
            # default domain resolver when DNS servers are configured.
            config["dns"] = {
                "servers": [
                    {"type": "udp", "tag": f"dns-{index}", "server": server}
                    for index, server in enumerate(settings.dns, start=1)
                ]
            }
            config["route"]["default_domain_resolver"] = "dns-1"
        if settings.traffic_api:
            # Expose the Clash API so the controller can poll cumulative
            # traffic via GET /connections (uploadTotal/downloadTotal).
            config["experimental"] = {
                "clash_api": {
                    "external_controller": f"127.0.0.1:{settings.traffic_api_port}"
                }
            }
        return config

    def _outbound_for(self, profile) -> dict:
        kind = profile.kind
        if kind in ("hysteria2", "tuic"):
            outbound = dict(profile.outbound)
            outbound["type"] = kind
            return outbound
        if kind in ("socks", "http"):
            server = _first_server(profile)
            outbound: dict = {
                "type": kind,
                "server": server.get("address", ""),
                "server_port": server.get("port", 0),
            }
            users = server.get("users") or []
            if users:
                outbound["username"] = users[0].get("user", "")
                outbound["password"] = users[0].get("pass", "")
            return outbound
        if kind in ("vmess", "vless"):
            vnext = profile.outbound["settings"]["vnext"][0]
            user = vnext["users"][0]
            outbound = {
                "type": kind,
                "server": vnext["address"],
                "server_port": vnext["port"],
                "uuid": user["id"],
            }
            if kind == "vmess":
                outbound["security"] = user.get("security", "auto")
                outbound["alter_id"] = user.get("alterId", 0)
            elif user.get("flow"):
                outbound["flow"] = user["flow"]
            self._apply_stream(profile, outbound)
            return outbound
        if kind == "trojan":
            server = _first_server(profile)
            outbound = {
                "type": "trojan",
                "server": server.get("address", ""),
                "server_port": server.get("port", 0),
                "password": server.get("password", ""),
            }
            self._apply_stream(profile, outbound)
            return outbound
        if kind == "ss":
            server = _first_server(profile)
            return {
                "type": "shadowsocks",
                "server": server.get("address", ""),
                "server_port": server.get("port", 0),
                "method": server.get("method", ""),
                "password": server.get("password", ""),
            }
        if kind == "wireguard":
            settings = profile.outbound["settings"]
            outbound = {
                "type": "wireguard",
                "private_key": settings.get("secretKey", ""),
                "local_address": settings.get("address", []),
            }
            peers = []
            for peer in settings.get("peers", []):
                host, port = _split_endpoint(peer.get("endpoint", ""))
                entry = {
                    "server": host,
                    "server_port": port,
                    "public_key": peer.get("publicKey", ""),
                    "allowed_ips": peer.get("allowedIps", []),
                }
                if peer.get("preSharedKey"):
                    entry["pre_shared_key"] = peer["preSharedKey"]
                peers.append(entry)
            outbound["peers"] = peers
            if settings.get("mtu"):
                outbound["mtu"] = settings["mtu"]
            return outbound
        if kind == "ssr":
            raise ValueError("sing-box does not support ssr")
        raise ValueError(f"sing-box cannot translate kind {kind}")

    def _apply_stream(self, profile, outbound: dict) -> None:
        stream = profile.outbound.get("streamSettings", {})
        tls = _tls(stream)
        transport = _transport(stream)
        if tls:
            outbound["tls"] = tls
        if transport:
            outbound["transport"] = transport

    def _rule(self, rule, selected: str) -> dict:
        if rule.action == "direct":
            outbound = "direct"
        elif rule.action == "block":
            outbound = "block"
        else:
            outbound = rule.target_id or selected

        suffix, keyword, regex, geosite = [], [], [], []
        for domain in rule.match.get("domains", []):
            if domain.startswith("keyword:"):
                keyword.append(domain[len("keyword:") :])
            elif domain.startswith("regex:"):
                regex.append(domain[len("regex:") :])
            elif domain.startswith("geosite:"):
                geosite.append(domain[len("geosite:") :])
            else:
                suffix.append(domain)
        cidr: list[str] = []
        geoip = list(rule.match.get("geoip", []))
        for ip in rule.match.get("ips", []):
            if ip.startswith("geoip:"):
                geoip.append(ip[len("geoip:") :])
            else:
                cidr.append(ip)
        geosite += rule.match.get("geosite", [])

        field: dict = {}
        if suffix:
            field["domain_suffix"] = suffix
        if keyword:
            field["domain_keyword"] = keyword
        if regex:
            field["domain_regex"] = regex
        if geosite:
            field["geosite"] = geosite
        if cidr:
            field["ip_cidr"] = cidr
        if geoip:
            field["geoip"] = geoip
        field["outbound"] = outbound
        return field

    def run_args(self, config_path: str) -> list[str]:
        return ["run", "-c", config_path]

    def validate_args(self, config_path: str) -> list[str]:
        return ["check", "-c", config_path]

    def binary_filename(self, platform: str, arch: str) -> str:
        return "sing-box.exe" if platform == "windows" else "sing-box"
