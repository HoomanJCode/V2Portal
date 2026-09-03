"""Core data models for v2portal.

These dataclasses are the single source of truth for the on-disk config.
Storage, config generation, and the TUI all consume them.

ID generation
-------------
Short numeric IDs (001, 002, …) are produced by :class:`_IdCounter`. Each
:class:`ConfigStore` owns its own counter, seeded from the highest existing ID
in the loaded config. Models created outside a store (tests, manual
construction) use the module-level fallback counter.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class _IdCounter:
    """Thread-unsafe sequential ID generator producing short numeric IDs.

    Each ConfigStore creates its own instance seeded from existing config IDs;
    the module-level fallback is used only for models created outside any store
    (tests, manual construction).
    """

    def __init__(self, start: int = 0) -> None:
        self._next = start

    def next(self) -> str:
        self._next += 1
        return f"{self._next:03d}"


# Module-level fallback counter for models created outside a store.
_fallback_counter = _IdCounter()


def new_id() -> str:
    """Return the next short numeric ID from the fallback counter.

    Prefer using a store-scoped :class:`_IdCounter` via
    :meth:`ConfigStore.next_id` when a store is available.
    """
    return _fallback_counter.next()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProfileKind(str, Enum):
    VMESS = "vmess"
    VLESS = "vless"
    TROJAN = "trojan"
    SS = "ss"
    SSR = "ssr"
    SOCKS = "socks"
    HTTP = "http"
    WIREGUARD = "wireguard"
    HYSTERIA2 = "hysteria2"
    TUIC = "tuic"
    MANUAL = "manual"
    OPENVPN = "openvpn"
    OPENCONNECT = "openconnect"


class GroupType(str, Enum):
    SINGLE = "single"
    BALANCER = "balancer"
    CHAIN = "chain"


class Strategy(str, Enum):
    LATENCY = "latency"
    RANDOM = "random"
    ROUND_ROBIN = "roundRobin"
    LEAST_LOAD = "leastLoad"


class EngineName(str, Enum):
    AUTO = "auto"
    SINGBOX = "sing-box"
    XRAY = "xray"


def _pick(data: dict, cls: type) -> dict[str, Any]:
    """Filter a raw dict to the dataclass's known fields."""
    known = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in known}


@dataclass
class Settings:
    listen: str = "0.0.0.0"
    mixed_port: int = 1080
    socks_port: int = 0  # 0 = disabled; when set, a dedicated SOCKS-only inbound
    http_port: int = 0  # 0 = disabled; when set, a dedicated HTTP-only inbound
    allow_lan: bool = True
    inbound_auth: dict[str, Any] = field(
        default_factory=lambda: {"enabled": False, "username": "", "password": ""}
    )
    dns: list[str] = field(default_factory=lambda: ["1.1.1.1", "8.8.8.8"])
    log_level: str = "info"
    test_url: str = "http://cp.cloudflare.com/generate_204"
    default_engine: str = "sing-box"
    backup_keep: int = 10
    traffic_api: bool = False
    traffic_api_port: int = 9090
    subscription_proxy: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Settings":
        return cls(**_pick(data, cls))


@dataclass
class RoutingRule:
    id: str = field(default_factory=new_id)
    action: str = "proxy"  # proxy | direct | block
    target_id: str | None = None
    enabled: bool = True
    match: dict[str, Any] = field(
        default_factory=lambda: {"domains": [], "ips": [], "geoip": [], "geosite": []}
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RoutingRule":
        return cls(**_pick(data, cls))


@dataclass
class RoutingConfig:
    mode: str = "all"  # all | split
    rules: list[RoutingRule] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "rules": [r.to_dict() for r in self.rules]}

    @classmethod
    def from_dict(cls, data: dict) -> "RoutingConfig":
        return cls(
            mode=data.get("mode", "all"),
            rules=[RoutingRule.from_dict(r) for r in data.get("rules", [])],
        )


@dataclass
class Profile:
    id: str = field(default_factory=new_id)
    name: str = ""
    kind: str = "manual"
    engine: str = "auto"
    share_link: str | None = None
    outbound: dict[str, Any] = field(default_factory=dict)
    vpn: dict[str, Any] | None = None
    source: str = "manual"
    subscription_id: str | None = None
    enabled: bool = True
    traffic_up: int = 0
    traffic_down: int = 0
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        return cls(**_pick(data, cls))


@dataclass
class Subscription:
    id: str = field(default_factory=new_id)
    name: str = ""
    url: str = ""
    user_agent: str | None = None
    last_updated: str | None = None
    expires: str | None = None
    traffic_used: int = 0
    profile_ids: list[str] = field(default_factory=list)
    auto_update_days: int = 0
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Subscription":
        return cls(**_pick(data, cls))


@dataclass
class Group:
    id: str = field(default_factory=new_id)
    name: str = ""
    type: str = "single"  # single | balancer | chain
    strategy: str = "latency"
    profile_ids: list[str] = field(default_factory=list)
    subscription_ids: list[str] = field(default_factory=list)
    group_ids: list[str] = field(default_factory=list)  # nested groups (Phase 01)
    server_ids: list[str] = field(default_factory=list)  # servers as members: resolved to socks/http profiles via their local inbound
    engine: str = "auto"
    enabled: bool = True
    traffic_up: int = 0
    traffic_down: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Group":
        return cls(**_pick(data, cls))


@dataclass
class Server:
    """A persistent inbound proxy bound to a port, forwarding to an outbound."""

    id: str = field(default_factory=new_id)
    name: str = ""
    port: int = 1080
    protocol: str = "mixed"  # mixed | socks | http
    outbound_id: str = ""  # profile, subscription, group, or server ID
    outbound_type: str = "profile"  # profile | subscription | group | server | direct
    listen: str = "0.0.0.0"
    auth: dict[str, Any] = field(
        default_factory=lambda: {"enabled": False, "username": "", "password": ""}
    )
    enabled: bool = True
    traffic_api_port: int = 0  # 0 = disabled; enables sing-box Clash API for live node reads
    failover: int = -1  # seconds between health probes; -1 = off, 0 = engine default (10s), >0 = custom
    traffic_up: int = 0
    traffic_down: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Server":
        return cls(**_pick(data, cls))


@dataclass
class Config:
    schema_version: int = 2
    settings: Settings = field(default_factory=Settings)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    engines: dict[str, dict[str, Any]] = field(default_factory=dict)
    profiles: list[Profile] = field(default_factory=list)
    subscriptions: list[Subscription] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)
    servers: list[Server] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "settings": self.settings.to_dict(),
            "routing": self.routing.to_dict(),
            "engines": self.engines,
            "profiles": [p.to_dict() for p in self.profiles],
            "subscriptions": [s.to_dict() for s in self.subscriptions],
            "groups": [g.to_dict() for g in self.groups],
            "servers": [s.to_dict() for s in self.servers],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        return cls(
            schema_version=data.get("schema_version", 2),
            settings=Settings.from_dict(data.get("settings", {})),
            routing=RoutingConfig.from_dict(data.get("routing", {})),
            engines=data.get("engines", {}),
            profiles=[Profile.from_dict(p) for p in data.get("profiles", [])],
            subscriptions=[Subscription.from_dict(s) for s in data.get("subscriptions", [])],
            groups=[Group.from_dict(g) for g in data.get("groups", [])],
            servers=[Server.from_dict(s) for s in data.get("servers", [])],
        )
