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


def add_manual_config(json_text: str, name: str, engine: str = "xray") -> Profile:
    """Build a ``kind=manual`` Profile from a raw xray outbound object.

    Raw manual objects use xray's ``protocol``/``settings`` shape, so they are
    always resolved by xray. The protocol is validated and the object is stored
    minus ``tag`` (the engine adapter assigns the stable profile id later).
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
    if engine == "auto":
        engine = "xray"
    if engine != "xray":
        raise ValueError("raw manual configs use xray's outbound format; choose engine='xray'")
    # Keep the protocol (it identifies a manual outbound); drop only the tag,
    # which is assigned from the profile id at config-generation time.
    outbound = {k: v for k, v in data.items() if k != "tag"}
    return Profile(name=name, kind="manual", engine=engine, outbound=outbound, source="manual")


def _endpoint(host: str, port: int) -> tuple[str, int]:
    if not isinstance(host, str) or not host.strip():
        raise ValueError("proxy host is required")
    if isinstance(port, bool) or (
        isinstance(port, float) and not port.is_integer()
    ):
        raise ValueError("proxy port must be an integer")
    try:
        normalized_port = int(port)
    except (TypeError, ValueError) as exc:
        raise ValueError("proxy port must be an integer") from exc
    if not 1 <= normalized_port <= 65535:
        raise ValueError("proxy port must be between 1 and 65535")
    return host.strip(), normalized_port


def _wireguard_endpoint(endpoint: str) -> None:
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ValueError("wireguard peer endpoint is required")
    value = endpoint.strip()
    if value.startswith("["):
        end = value.find("]")
        host = value[1:end] if end >= 0 else ""
        port = value[end + 2 :] if end >= 0 and value[end + 1 :].startswith(":") else ""
    else:
        host, separator, port = value.rpartition(":")
        if not separator:
            host, port = "", ""
    try:
        _endpoint(host, port)
    except ValueError as exc:
        raise ValueError("wireguard peer endpoint must be host:port") from exc


def _plain_proxy(
    kind: str, name: str, host: str, port: int, username: str | None = None, password: str | None = None
) -> Profile:
    host, port = _endpoint(host, port)
    server: dict = {"address": host, "port": port}
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
    if not isinstance(private_key, str) or not private_key.strip():
        raise ValueError("wireguard private key is required")
    if (
        not isinstance(address, list)
        or not address
        or any(not isinstance(item, str) or not item.strip() for item in address)
    ):
        raise ValueError("wireguard address list is required")
    if not isinstance(peers, list) or not peers:
        raise ValueError("wireguard requires at least one peer")
    for peer in peers:
        if not isinstance(peer, dict):
            raise ValueError("wireguard peer must be an object")
        if not str(peer.get("publicKey", "")).strip():
            raise ValueError("wireguard peer public key is required")
        _wireguard_endpoint(peer.get("endpoint"))
        allowed = peer.get("allowedIps")
        if not isinstance(allowed, list) or not allowed:
            raise ValueError("wireguard peer allowed IPs are required")
    if mtu is not None:
        if isinstance(mtu, bool):
            raise ValueError("wireguard MTU must be an integer")
        try:
            mtu = int(mtu)
        except (TypeError, ValueError) as exc:
            raise ValueError("wireguard MTU must be an integer") from exc
        if not 576 <= mtu <= 65535:
            raise ValueError("wireguard MTU must be between 576 and 65535")
    settings: dict = {"secretKey": private_key, "address": address, "peers": peers}
    if mtu is not None:
        settings["mtu"] = mtu
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
    server, server_port = _endpoint(server, server_port)
    outbound: dict = {
        "server": server,
        "server_port": server_port,
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
    server, server_port = _endpoint(server, server_port)
    outbound: dict = {
        "server": server,
        "server_port": server_port,
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
