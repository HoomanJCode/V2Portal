"""Manual outbound creation (raw config, socks/http, wireguard, hysteria2, tuic)."""

from __future__ import annotations

import json

from ..models import Profile, now_iso

# xray-style protocol names accepted for a pasted manual outbound.
ALLOWED_MANUAL_PROTOCOLS = {
    "vmess",
    "vless",
    "trojan",
    "shadowsocks",
    "shadowsocksr",
    "socks",
    "http",
    "wireguard",
}


def add_manual_config(json_text: str, name: str, engine: str = "auto") -> Profile:
    """Build a ``kind=manual`` Profile from a raw xray outbound object.

    The protocol is validated and the object is stored minus ``protocol``/
    ``tag`` (those are re-added by the engine adapter later).
    """
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("config must be a JSON object")
    if "listen" in data:
        raise ValueError("this looks like an inbound; provide an outbound config")
    protocol = data.get("protocol")
    if protocol not in ALLOWED_MANUAL_PROTOCOLS:
        raise ValueError(f"unsupported protocol: {protocol}")
    outbound = {k: v for k, v in data.items() if k not in ("protocol", "tag")}
    return Profile(name=name, kind="manual", engine=engine, outbound=outbound, source="manual")


def _plain_proxy(
    kind: str, name: str, host: str, port: int, username: str | None = None, password: str | None = None
) -> Profile:
    server: dict = {"address": host, "port": int(port)}
    if username or password:
        server["users"] = [{"user": username or "", "pass": password or ""}]
    outbound = {"settings": {"servers": [server]}}
    return Profile(name=name, kind=kind, engine="auto", outbound=outbound, source="manual")


def add_socks_proxy(
    name: str, host: str, port: int, username: str | None = None, password: str | None = None
) -> Profile:
    return _plain_proxy("socks", name, host, port, username, password)


def add_http_proxy(
    name: str, host: str, port: int, username: str | None = None, password: str | None = None
) -> Profile:
    return _plain_proxy("http", name, host, port, username, password)


def add_wireguard(
    name: str,
    private_key: str,
    address: list[str],
    peers: list[dict],
    mtu: int | None = None,
) -> Profile:
    settings: dict = {"secretKey": private_key, "address": address, "peers": peers}
    if mtu:
        settings["mtu"] = int(mtu)
    outbound = {"settings": settings}
    return Profile(name=name, kind="wireguard", engine="auto", outbound=outbound, source="manual")


def add_hysteria2(
    name: str,
    server: str,
    server_port: int,
    password: str,
    sni: str | None = None,
    insecure: bool = False,
    obfs: str | None = None,
    obfs_password: str | None = None,
    up_mbps: int | None = None,
    down_mbps: int | None = None,
) -> Profile:
    outbound: dict = {
        "server": server,
        "server_port": int(server_port),
        "password": password,
        "tls": {"enabled": True, "server_name": sni or server, "insecure": insecure},
    }
    if obfs:
        obfs_obj: dict = {"type": obfs}
        if obfs_password:
            obfs_obj["password"] = obfs_password
        outbound["obfs"] = obfs_obj
    if up_mbps:
        outbound["up_mbps"] = int(up_mbps)
    if down_mbps:
        outbound["down_mbps"] = int(down_mbps)
    return Profile(name=name, kind="hysteria2", engine="sing-box", outbound=outbound, source="manual")


def add_tuic(
    name: str,
    server: str,
    server_port: int,
    uuid: str,
    password: str,
    sni: str | None = None,
    alpn: str | None = None,
    congestion_control: str = "cubic",
    udp_relay_mode: str = "native",
    allow_insecure: bool = False,
) -> Profile:
    outbound: dict = {
        "server": server,
        "server_port": int(server_port),
        "uuid": uuid,
        "password": password,
        "congestion_control": congestion_control,
        "udp_relay_mode": udp_relay_mode,
        "tls": {"enabled": True, "server_name": sni or server, "insecure": allow_insecure},
    }
    if alpn:
        outbound["tls"]["alpn"] = [a for a in alpn.split(",") if a]
    return Profile(name=name, kind="tuic", engine="sing-box", outbound=outbound, source="manual")


def edit_profile(store, profile_id: str, **fields) -> Profile:
    """Update fields on an existing profile and bump ``updated_at``."""
    profile = store.get_profile(profile_id)
    if profile is None:
        raise ValueError(f"unknown profile id: {profile_id}")
    for key, value in fields.items():
        if hasattr(profile, key):
            setattr(profile, key, value)
    profile.updated_at = now_iso()
    return profile


def remove_profile(store, profile_id: str) -> bool:
    """Remove a profile, pruning it from subscriptions and groups."""
    return store.remove_profile(profile_id)
