"""sing-box config generator.

Profiles store xray-style outbound objects for protocols xray supports; this
adapter translates those to sing-box outbounds. sing-box-only kinds
(hysteria2/tuic) already store sing-box-style fields and pass through.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING

from ..routing.rules import normalize_rules
from .base import EngineAdapter, register

if TYPE_CHECKING:
    from ..models import RoutingConfig, Settings
    from ..outbounds.groups import Target

INBOUND_TAG = "mixed-in"
SOCKS_INBOUND_TAG = "socks-in"
HTTP_INBOUND_TAG = "http-in"
BALANCER_TAG = "balancer"


def _first_server(profile) -> dict:
    if not isinstance(profile.outbound, dict):
        raise ValueError(f"{profile.kind} outbound must be an object")
    settings = profile.outbound.get("settings")
    if not isinstance(settings, dict):
        raise ValueError(f"{profile.kind} outbound is missing settings")
    servers = settings.get("servers") or settings.get("vnext")
    if not isinstance(servers, list) or not servers or not isinstance(servers[0], dict):
        raise ValueError(f"{profile.kind} outbound is missing a server")
    server = servers[0]
    if not isinstance(server.get("address"), str) or not server["address"].strip():
        raise ValueError(f"{profile.kind} outbound is missing a server address")
    port = server.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError(f"{profile.kind} outbound has an invalid server port")
    return server


def _vnext_user(profile) -> tuple[dict, dict]:
    if not isinstance(profile.outbound, dict):
        raise ValueError(f"{profile.kind} outbound must be an object")
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
    user = users[0]
    if not isinstance(user.get("id"), str) or not user["id"].strip():
        raise ValueError(f"{profile.kind} outbound user is missing an id")
    return server, user


def _positive_int(value: int, label: str) -> int:
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        raise ValueError(f"{label} must be a positive integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a positive integer") from exc
    if normalized <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return normalized


def _wireguard_network(value: str, label: str, *, interface: bool = False) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"wireguard {label} must be a CIDR")
    try:
        if interface:
            ipaddress.ip_interface(value)
        else:
            ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise ValueError(f"wireguard {label} must be a CIDR") from exc


def _native_outbound(profile) -> dict:
    if not isinstance(profile.outbound, dict):
        raise ValueError(f"{profile.kind} outbound must be an object")
    outbound = dict(profile.outbound)
    server = outbound.get("server")
    if not isinstance(server, str) or not server.strip():
        raise ValueError(f"{profile.kind} outbound is missing a server")
    port = outbound.get("server_port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError(f"{profile.kind} outbound has an invalid server port")
    if profile.kind == "hysteria2":
        password = outbound.get("password")
        if not isinstance(password, str) or not password.strip():
            raise ValueError("hysteria2 password is required")
        for field, label in (("up_mbps", "hysteria2 upload rate"), ("down_mbps", "hysteria2 download rate")):
            if field in outbound and outbound[field] is not None:
                outbound[field] = _positive_int(outbound[field], label)
    else:
        uuid = outbound.get("uuid")
        if not isinstance(uuid, str) or not uuid.strip():
            raise ValueError("tuic UUID is required")
        password = outbound.get("password")
        if not isinstance(password, str) or not password.strip():
            raise ValueError("tuic password is required")
    return outbound


def _split_endpoint(endpoint: str) -> tuple[str, int]:
    if not isinstance(endpoint, str):
        raise ValueError("endpoint must be text")
    if not endpoint:
        return "", 0
    if endpoint.startswith("["):  # IPv6 [::1]:443
        host, _, rest = endpoint[1:].partition("]")
        return host, int(rest.lstrip(":") or 0)
    host, _, port = endpoint.rpartition(":")
    return host, int(port or 0)


def _tls(stream: dict) -> dict | None:
    if not isinstance(stream, dict):
        raise ValueError("streamSettings must be an object")
    if stream.get("security") != "tls":
        return None
    tls = stream.get("tlsSettings", {})
    if not isinstance(tls, dict):
        raise ValueError("tlsSettings must be an object")
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


def _geo_tags(rule) -> list[str]:
    """Return the rule-set tags referenced by a rule's geo matchers."""
    tags: list[str] = []
    for value in rule.match.get("geosite", []):
        tags.append(f"geosite-{value}")
    for value in rule.match.get("geoip", []):
        tags.append(f"geoip-{value}")
    for domain in rule.match.get("domains", []):
        if domain.startswith("geosite:"):
            tags.append(f"geosite-{domain[len('geosite:'):]}")
    for ip in rule.match.get("ips", []):
        if ip.startswith("geoip:"):
            tags.append(f"geoip-{ip[len('geoip:'):]}")
    return tags


def _rule_set_entry(tag: str) -> dict:
    """Build a remote (auto-download) rule-set entry for a geo tag."""
    if tag.startswith("geosite-"):
        value = tag[len("geosite-") :]
        url = f"https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-{value}.srs"
    else:
        value = tag[len("geoip-") :]
        url = f"https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set/geoip-{value}.srs"
    return {
        "type": "remote",
        "tag": tag,
        "format": "binary",
        "url": url,
        # Route the download through sing-box's own DNS; the Go system
        # resolver has no localhost nameserver on Termux/minimal systems.
        "download_detour": "direct",
    }


def _transport(stream: dict) -> dict | None:
    if not isinstance(stream, dict):
        raise ValueError("streamSettings must be an object")
    net = stream.get("network", "tcp")
    if net == "ws":
        ws = stream.get("wsSettings", {})
        if not isinstance(ws, dict):
            raise ValueError("wsSettings must be an object")
        obj: dict = {"type": "ws"}
        if ws.get("path"):
            obj["path"] = ws["path"]
        headers = ws.get("headers") or {}
        if not isinstance(headers, dict):
            raise ValueError("WebSocket headers must be an object")
        if headers.get("Host"):
            obj["headers"] = {"Host": headers["Host"]}
        return obj
    if net == "grpc":
        grpc = stream.get("grpcSettings") or {}
        if not isinstance(grpc, dict):
            raise ValueError("grpcSettings must be an object")
        obj = {"type": "grpc"}
        service_name = grpc.get("serviceName")
        if service_name:
            obj["service_name"] = service_name
        return obj
    if net == "h2":
        http = stream.get("httpSettings", {})
        if not isinstance(http, dict):
            raise ValueError("httpSettings must be an object")
        obj = {"type": "http"}
        if http.get("path"):
            obj["path"] = http["path"]
        if http.get("host"):
            obj["host"] = http["host"]
        return obj
    return None


def _validate_settings(settings) -> None:
    listen = getattr(settings, "listen", None)
    if not isinstance(listen, str) or not listen.strip():
        raise ValueError("sing-box listen address is required")
    if not isinstance(getattr(settings, "allow_lan", None), bool):
        raise ValueError("sing-box allow_lan must be boolean")

    mixed_port = getattr(settings, "mixed_port", None)
    if isinstance(mixed_port, bool) or not isinstance(mixed_port, int) or not 1 <= mixed_port <= 65535:
        raise ValueError("sing-box mixed_port must be between 1 and 65535")

    auth = getattr(settings, "inbound_auth", None)
    if not isinstance(auth, dict):
        raise ValueError("sing-box inbound_auth must be an object")
    enabled = auth.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("sing-box inbound_auth.enabled must be boolean")
    if enabled:
        for field in ("username", "password"):
            value = auth.get(field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"sing-box inbound_auth.{field} is required")

    dns = getattr(settings, "dns", None)
    if not isinstance(dns, list):
        raise ValueError("sing-box DNS servers must be a list")
    for server in dns:
        if not isinstance(server, str) or not server.strip():
            raise ValueError("sing-box DNS servers must contain non-empty text")

    traffic_api = getattr(settings, "traffic_api", None)
    if not isinstance(traffic_api, bool):
        raise ValueError("sing-box traffic_api must be boolean")
    if traffic_api:
        api_port = getattr(settings, "traffic_api_port", None)
        if isinstance(api_port, bool) or not isinstance(api_port, int) or not 1 <= api_port <= 65535:
            raise ValueError("sing-box traffic_api_port must be between 1 and 65535")


@register
class SingBoxAdapter(EngineAdapter):
    name = "sing-box"
    supported_kinds = frozenset(
        {"vmess", "vless", "trojan", "ss", "socks", "http", "wireguard", "hysteria2", "tuic"}
    )
    supported_strategies = frozenset({"latency", "random", "roundRobin"})

    def generate(self, settings: "Settings", routing: "RoutingConfig", target: "Target") -> dict:
        _validate_settings(settings)
        outbounds = [
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"},
        ]
        endpoints: list[dict] = []
        for idx, profile in enumerate(target.profiles):
            if profile.kind == "wireguard":
                # Since sing-box 1.13 WireGuard is an endpoint, not an
                # outbound. Its tag is a first-class route target: it can be
                # referenced by route.final, selector/urltest groups, rules
                # and detour in either direction.
                endpoint = self._endpoint_for(profile)
                endpoint["tag"] = profile.id
                if target.type == "chain" and idx > 0:
                    endpoint["detour"] = target.profiles[idx - 1].id
                endpoints.append(endpoint)
                continue
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

        listen = settings.listen if settings.allow_lan else "127.0.0.1"
        inbounds: list[dict] = []
        inbound_tags: list[str] = []

        mixed_inbound: dict = {
            "type": "mixed",
            "tag": INBOUND_TAG,
            "listen": listen,
            "listen_port": settings.mixed_port,
        }
        if settings.inbound_auth.get("enabled"):
            mixed_inbound["users"] = [
                {"username": settings.inbound_auth["username"], "password": settings.inbound_auth["password"]}
            ]
        inbounds.append(mixed_inbound)
        inbound_tags.append(INBOUND_TAG)

        socks_inbound: dict | None = None
        http_inbound: dict | None = None
        if getattr(settings, "socks_port", 0):
            socks_inbound = {
                "type": "socks",
                "tag": SOCKS_INBOUND_TAG,
                "listen": listen,
                "listen_port": settings.socks_port,
            }
            if settings.inbound_auth.get("enabled"):
                socks_inbound["users"] = [
                    {"username": settings.inbound_auth["username"], "password": settings.inbound_auth["password"]}
                ]
            inbounds.append(socks_inbound)
            inbound_tags.append(SOCKS_INBOUND_TAG)
        if getattr(settings, "http_port", 0):
            http_inbound = {
                "type": "http",
                "tag": HTTP_INBOUND_TAG,
                "listen": listen,
                "listen_port": settings.http_port,
            }
            if settings.inbound_auth.get("enabled"):
                http_inbound["users"] = [
                    {"username": settings.inbound_auth["username"], "password": settings.inbound_auth["password"]}
                ]
            inbounds.append(http_inbound)
            inbound_tags.append(HTTP_INBOUND_TAG)

        rules: list[dict] = []
        rule_sets: dict[str, dict] = {}
        if routing.mode == "split":
            for rule in normalize_rules(routing, selected):
                rules.append(self._rule(rule, selected))
                for tag in _geo_tags(rule):
                    rule_sets.setdefault(tag, _rule_set_entry(tag))

        config: dict = {
            "log": {"level": settings.log_level},
            "inbounds": inbounds,
            "outbounds": outbounds,
            "route": {"rules": rules, "final": selected},
        }
        if endpoints:
            config["endpoints"] = endpoints
        if rule_sets:
            config["route"]["rule_set"] = list(rule_sets.values())
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
            outbound = _native_outbound(profile)
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
            vnext, user = _vnext_user(profile)
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
            raise ValueError("wireguard is an endpoint, not an outbound")
        if kind == "ssr":
            raise ValueError("sing-box does not support ssr")
        raise ValueError(f"sing-box cannot translate kind {kind}")

    def _endpoint_for(self, profile) -> dict:
        """Build a sing-box >= 1.13 WireGuard endpoint (top-level `endpoints`)."""
        if not isinstance(profile.outbound, dict):
            raise ValueError("wireguard outbound must be an object")
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
            _wireguard_network(item, "address", interface=True)
        peer_settings = settings.get("peers")
        if not isinstance(peer_settings, list) or not peer_settings:
            raise ValueError("wireguard requires at least one peer")
        peers = []
        for peer in peer_settings:
            if not isinstance(peer, dict):
                raise ValueError("wireguard peer must be an object")
            public_key = peer.get("publicKey")
            if not isinstance(public_key, str) or not public_key.strip():
                raise ValueError("wireguard peer public key is required")
            endpoint = peer.get("endpoint")
            try:
                host, port = _split_endpoint(endpoint)
            except (TypeError, ValueError) as exc:
                raise ValueError("wireguard peer endpoint must be host:port") from exc
            if not host or not 1 <= port <= 65535:
                raise ValueError("wireguard peer endpoint must be host:port")
            allowed = peer.get("allowedIps")
            if not isinstance(allowed, list) or not allowed:
                raise ValueError("wireguard peer allowed IPs are required")
            for item in allowed:
                _wireguard_network(item, "peer allowed IP")
            entry: dict = {
                "address": host,
                "port": port,
                "public_key": public_key,
                "allowed_ips": allowed,
            }
            if peer.get("preSharedKey"):
                entry["pre_shared_key"] = peer["preSharedKey"]
            if peer.get("reserved"):
                entry["reserved"] = peer["reserved"]
            if peer.get("persistentKeepaliveInterval"):
                entry["persistent_keepalive_interval"] = peer["persistentKeepaliveInterval"]
            peers.append(entry)
        endpoint: dict = {
            "type": "wireguard",
            "address": address,
            "private_key": private_key,
            "peers": peers,
        }
        mtu = settings.get("mtu")
        if mtu is not None:
            if isinstance(mtu, bool) or not isinstance(mtu, int) or not 576 <= mtu <= 65535:
                raise ValueError("wireguard MTU must be between 576 and 65535")
            endpoint["mtu"] = mtu
        return endpoint

    def _apply_stream(self, profile, outbound: dict) -> None:
        stream = profile.outbound.get("streamSettings", {})
        if not isinstance(stream, dict):
            raise ValueError("streamSettings must be an object")
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

        suffix, keyword, regex = [], [], []
        for domain in rule.match.get("domains", []):
            if domain.startswith("keyword:"):
                keyword.append(domain[len("keyword:") :])
            elif domain.startswith("regex:"):
                regex.append(domain[len("regex:") :])
            elif domain.startswith("geosite:"):
                continue  # handled via rule_set
            else:
                suffix.append(domain)
        cidr: list[str] = []
        for ip in rule.match.get("ips", []):
            if ip.startswith("geoip:"):
                continue  # handled via rule_set
            cidr.append(ip)

        field: dict = {}
        if suffix:
            field["domain_suffix"] = suffix
        if keyword:
            field["domain_keyword"] = keyword
        if regex:
            field["domain_regex"] = regex
        if cidr:
            field["ip_cidr"] = cidr
        rule_set_tags = _geo_tags(rule)
        if rule_set_tags:
            field["rule_set"] = rule_set_tags
        field["outbound"] = outbound
        return field

    def run_args(self, config_path: str) -> list[str]:
        return ["run", "-c", config_path]

    def validate_args(self, config_path: str) -> list[str]:
        return ["check", "-c", config_path]

    def binary_filename(self, platform: str, arch: str) -> str:
        return "sing-box.exe" if platform == "windows" else "sing-box"
