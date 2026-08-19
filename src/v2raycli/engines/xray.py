"""xray-core config generator."""

from __future__ import annotations

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
        if profile.kind == "manual":
            if "protocol" not in profile.outbound:
                raise ValueError("manual outbound is missing its protocol")
            outbound = dict(profile.outbound)
            outbound["tag"] = profile.id
            return outbound
        protocol = _KIND_PROTOCOL.get(profile.kind)
        if protocol is None:
            raise ValueError(f"xray does not support kind {profile.kind}")
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
