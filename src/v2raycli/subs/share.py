"""Share-link codec for v2ray-family proxy links.

`decode_link` turns a share link into a `Profile`. `encode_link` reverses it
for the "export" action.

Canonical `Profile.outbound` shape: an xray-core-style object
(`settings` + optional `streamSettings`) for protocols xray supports
(vmess/vless/trojan/ss/ssr/socks/http/wireguard). sing-box-only protocols
(hysteria2/tuic) store sing-box-style fields (minus `type`). The engine
adapters in a later phase translate these to the target engine's config.
"""

from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, quote, unquote

from ..engines import engine_for_kind
from ..models import Profile


class ShareLinkError(ValueError):
    """Raised when a share link cannot be parsed."""


def _b64decode(s: str) -> bytes:
    """Decode base64, tolerating url-safe chars and missing padding."""
    s = "".join(s.split()).replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)


def _make_profile(raw: str, kind: str, name: str, outbound: dict) -> Profile:
    return Profile(
        name=name,
        kind=kind,
        engine=engine_for_kind(kind),
        share_link=raw,
        outbound=outbound,
        source="manual",
    )


def _split_authority(rest: str) -> tuple[str, str, str, str, str]:
    """Split ``[userinfo@]host[:port][?query][#fragment]``.

    Returns ``(userinfo, host, port, query, name)`` (port/name are str, may be
    empty).
    """
    fragment = ""
    if "#" in rest:
        rest, fragment = rest.split("#", 1)
    query = ""
    if "?" in rest:
        rest, query = rest.split("?", 1)
    userinfo, hostport = "", rest
    if "@" in rest:
        userinfo, hostport = rest.rsplit("@", 1)
    host, port = hostport, ""
    if hostport.startswith("["):  # IPv6 [::1]:443
        end = hostport.find("]")
        host = hostport[1:end]
        after = hostport[end + 1 :]
        if after.startswith(":"):
            port = after[1:]
    elif ":" in hostport:
        host, port = hostport.rsplit(":", 1)
    return userinfo, host, port, query, unquote(fragment)


def _query_dict(query: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(query).items()}


# -- vmess ----------------------------------------------------------------


def parse_vmess(raw: str) -> Profile:
    payload = unquote(raw[len("vmess://") :])
    data = json.loads(_b64decode(payload).decode("utf-8"))
    address = data.get("add", "")
    port = int(data.get("port", 0))
    uid = data.get("id", "")
    alter_id = int(data.get("aid", 0) or 0)
    security = data.get("scy", "auto")
    net = data.get("net", "tcp")
    host = data.get("host", "")
    path = data.get("path", "")
    tls = data.get("tls", "") or ""
    sni = data.get("sni", "") or host
    alpn = data.get("alpn", "")
    fp = data.get("fp", "")

    stream: dict = {"network": net}
    if net == "ws":
        stream["wsSettings"] = {"path": path}
        if host:
            stream["wsSettings"]["headers"] = {"Host": host}
    elif net == "grpc":
        stream["grpcSettings"] = {"serviceName": path}
    elif net == "h2":
        stream["httpSettings"] = {"path": path}
        if host:
            stream["httpSettings"]["host"] = [host]
    if tls == "tls":
        stream["security"] = "tls"
        tls_settings: dict = {}
        if sni:
            tls_settings["serverName"] = sni
        if alpn:
            tls_settings["alpn"] = [a for a in alpn.split(",") if a]
        if fp:
            tls_settings["fingerprint"] = fp
        stream["tlsSettings"] = tls_settings

    outbound = {
        "settings": {
            "vnext": [
                {
                    "address": address,
                    "port": port,
                    "users": [{"id": uid, "alterId": alter_id, "security": security}],
                }
            ]
        },
        "streamSettings": stream,
    }
    name = data.get("ps", "") or f"{address}:{port}"
    return _make_profile(raw, "vmess", name, outbound)


# -- vless ----------------------------------------------------------------


def parse_vless(raw: str) -> Profile:
    userinfo, host, port_s, query, name = _split_authority(raw[len("vless://") :])
    q = _query_dict(query)
    port = int(port_s or 0)
    flow = q.get("flow", "")
    encryption = q.get("encryption", "none")
    security = q.get("security", "none")
    sni = q.get("sni", "")
    fp = q.get("fp", "")
    alpn = q.get("alpn", "")
    net = q.get("type", "tcp")
    host_param = q.get("host", "")
    path = q.get("path", "")
    service_name = q.get("serviceName", "")
    pbk = q.get("pbk", "")
    sid = q.get("sid", "")
    spx = q.get("spx", "")

    stream: dict = {"network": net}
    if net == "ws":
        stream["wsSettings"] = {"path": path}
        if host_param:
            stream["wsSettings"]["headers"] = {"Host": host_param}
    elif net == "grpc":
        stream["grpcSettings"] = {"serviceName": service_name}
    elif net == "h2":
        stream["httpSettings"] = {"path": path}
        if host_param:
            stream["httpSettings"]["host"] = [host_param]

    if security == "tls":
        stream["security"] = "tls"
        tls_settings: dict = {}
        if sni:
            tls_settings["serverName"] = sni
        if fp:
            tls_settings["fingerprint"] = fp
        if alpn:
            tls_settings["alpn"] = [a for a in alpn.split(",") if a]
        stream["tlsSettings"] = tls_settings
    elif security == "reality":
        stream["security"] = "reality"
        stream["realitySettings"] = {
            "serverName": sni or host,
            "publicKey": pbk,
            "shortId": sid,
            "spiderX": spx,
            "fingerprint": fp or "chrome",
        }

    outbound = {
        "settings": {
            "vnext": [
                {
                    "address": host,
                    "port": port,
                    "users": [{"id": userinfo, "flow": flow, "encryption": encryption}],
                }
            ]
        },
        "streamSettings": stream,
    }
    return _make_profile(raw, "vless", name or f"{host}:{port}", outbound)


# -- trojan ---------------------------------------------------------------


def parse_trojan(raw: str) -> Profile:
    userinfo, host, port_s, query, name = _split_authority(raw[len("trojan://") :])
    q = _query_dict(query)
    port = int(port_s or 0)
    security = q.get("security", "")
    sni = q.get("sni", "")
    alpn = q.get("alpn", "")
    fp = q.get("fp", "")
    allow_insecure = q.get("allowInsecure", "") in ("1", "true", "True")
    net = q.get("type", "tcp")
    path = q.get("path", "")
    host_param = q.get("host", "")
    service_name = q.get("serviceName", "")

    stream: dict = {"network": net}
    if net == "ws":
        stream["wsSettings"] = {"path": path}
        if host_param:
            stream["wsSettings"]["headers"] = {"Host": host_param}
    elif net == "grpc":
        stream["grpcSettings"] = {"serviceName": service_name}

    if security == "tls" or sni:
        stream["security"] = "tls"
        tls_settings: dict = {"serverName": sni or host, "allowInsecure": allow_insecure}
        if alpn:
            tls_settings["alpn"] = [a for a in alpn.split(",") if a]
        if fp:
            tls_settings["fingerprint"] = fp
        stream["tlsSettings"] = tls_settings

    outbound = {
        "settings": {"servers": [{"address": host, "port": port, "password": userinfo}]},
        "streamSettings": stream,
    }
    return _make_profile(raw, "trojan", name or f"{host}:{port}", outbound)


# -- shadowsocks / ssr ----------------------------------------------------


def parse_ss(raw: str) -> Profile:
    rest = raw[len("ss://") :]
    fragment = ""
    if "#" in rest:
        rest, fragment = rest.split("#", 1)
    query = ""
    if "?" in rest:
        rest, query = rest.split("?", 1)
    if "@" not in rest:
        raise ShareLinkError("invalid ss link (missing @)")
    userinfo, _, hostport = rest.rpartition("@")
    if ":" in userinfo:  # SIP002 plain form
        method, password = (unquote(x) for x in userinfo.split(":", 1))
    else:  # legacy base64(method:password)
        method, password = _b64decode(userinfo).decode("utf-8").split(":", 1)
    host, port_s = hostport.rsplit(":", 1) if ":" in hostport else (hostport, "443")
    port = int(port_s)

    outbound: dict = {
        "settings": {
            "servers": [{"address": host, "port": port, "method": method, "password": password}]
        }
    }
    if query:  # plugin params (v2ray-plugin / obfs)
        outbound["plugin"] = _query_dict(query)
    return _make_profile(raw, "ss", unquote(fragment) or f"{host}:{port}", outbound)


def parse_ssr(raw: str) -> Profile:
    body = unquote(raw[len("ssr://") :])
    query = ""
    if "/?" in body:
        body, query = body.split("/?", 1)
    decoded = _b64decode(body).decode("utf-8")
    parts = decoded.split(":", 5)
    if len(parts) < 6:
        raise ShareLinkError("invalid ssr link")
    host, port_s, protocol, method, obfs, password_b64 = parts
    port = int(port_s)
    password = _b64decode(password_b64).decode("utf-8") if password_b64 else ""

    params: dict = {}
    if query:
        for kv in query.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                params[k] = _b64decode(unquote(v)).decode("utf-8", errors="replace")

    outbound = {
        "settings": {
            "servers": [
                {
                    "address": host,
                    "port": port,
                    "method": method,
                    "password": password,
                    "protocol": protocol,
                    "protocolParam": params.get("protoparam", ""),
                    "obfs": obfs,
                    "obfsParam": params.get("obfsparam", ""),
                }
            ]
        }
    }
    name = params.get("remarks", "") or f"{host}:{port}"
    return _make_profile(raw, "ssr", name, outbound)


# -- plain socks / http proxies -------------------------------------------


def _parse_plain_proxy(raw: str, kind: str) -> Profile:
    scheme = raw.split("://", 1)[0].lower()
    userinfo, host, port_s, _query, name = _split_authority(raw[len(scheme) + 3 :])
    port = int(port_s or 0)
    server: dict = {"address": host, "port": port}
    if userinfo:
        u, _, p = userinfo.partition(":")
        server["users"] = [{"user": unquote(u), "pass": unquote(p)}]
    outbound = {"settings": {"servers": [server]}}
    return _make_profile(raw, kind, name or f"{host}:{port}", outbound)


def parse_socks(raw: str) -> Profile:
    return _parse_plain_proxy(raw, "socks")


def parse_http(raw: str) -> Profile:
    return _parse_plain_proxy(raw, "http")


# -- hysteria2 -----------------------------------------------------------


def parse_hysteria2(raw: str) -> Profile:
    userinfo, host, port_s, query, name = _split_authority(raw[len("hysteria2://") :])
    q = _query_dict(query)
    port = int(port_s or 0)
    insecure = q.get("insecure", "") in ("1", "true", "True")
    sni = q.get("sni", "") or host
    obfs = q.get("obfs", "")
    obfs_password = q.get("obfs-password", "")
    pin = q.get("pinSHA256", "")

    outbound: dict = {
        "server": host,
        "server_port": port,
        "password": userinfo,
        "tls": {"enabled": True, "server_name": sni, "insecure": insecure},
    }
    if pin:
        outbound["tls"]["pinSHA256"] = pin
    if obfs:
        obfs_obj: dict = {"type": obfs}
        if obfs_password:
            obfs_obj["password"] = obfs_password
        outbound["obfs"] = obfs_obj
    up = q.get("up", "")
    down = q.get("down", "")
    if up:
        outbound["up_mbps"] = int(up)
    if down:
        outbound["down_mbps"] = int(down)
    return _make_profile(raw, "hysteria2", name or f"{host}:{port}", outbound)


# -- tuic -----------------------------------------------------------------


def parse_tuic(raw: str) -> Profile:
    userinfo, host, port_s, query, name = _split_authority(raw[len("tuic://") :])
    q = _query_dict(query)
    port = int(port_s or 0)
    uuid, _, password = userinfo.partition(":")
    sni = q.get("sni", "") or host
    alpn = q.get("alpn", "")
    allow_insecure = q.get("allow_insecure", "") in ("1", "true", "True")

    outbound: dict = {
        "server": host,
        "server_port": port,
        "uuid": uuid,
        "password": password,
        "congestion_control": q.get("congestion_control", "cubic"),
        "udp_relay_mode": q.get("udp_relay_mode", "native"),
        "tls": {"enabled": True, "server_name": sni, "insecure": allow_insecure},
    }
    if alpn:
        outbound["tls"]["alpn"] = [a for a in alpn.split(",") if a]
    return _make_profile(raw, "tuic", name or f"{host}:{port}", outbound)


# -- wireguard ------------------------------------------------------------


def parse_wireguard(raw: str) -> Profile:
    payload = unquote(raw[len("wireguard://") :])
    if "#" in payload:
        payload, _ = payload.split("#", 1)
    if payload.startswith("{"):
        data = json.loads(payload)
    else:
        data = json.loads(_b64decode(payload).decode("utf-8"))

    peers = []
    for peer in data.get("peers", []):
        entry = {
            "publicKey": peer.get("public_key", ""),
            "endpoint": peer.get("endpoint", ""),
            "allowedIps": peer.get("allowed_ips", []),
        }
        if peer.get("preshared_key"):
            entry["preSharedKey"] = peer["preshared_key"]
        peers.append(entry)

    outbound: dict = {
        "settings": {
            "secretKey": data.get("private_key", ""),
            "address": data.get("address", []),
            "peers": peers,
        }
    }
    if data.get("mtu"):
        outbound["settings"]["mtu"] = int(data["mtu"])
    name = data.get("name", "") or "wireguard"
    return _make_profile(raw, "wireguard", name, outbound)


# -- dispatch -------------------------------------------------------------


_HANDLERS = {
    "vmess": parse_vmess,
    "vless": parse_vless,
    "trojan": parse_trojan,
    "ss": parse_ss,
    "ssr": parse_ssr,
    "socks": parse_socks,
    "socks5": parse_socks,
    "http": parse_http,
    "https": parse_http,
    "hysteria2": parse_hysteria2,
    "tuic": parse_tuic,
    "wireguard": parse_wireguard,
}


def decode_link(raw: str) -> Profile:
    """Decode a share link into a Profile, raising ShareLinkError on failure."""
    if not isinstance(raw, str):
        raise ShareLinkError("link must be text")
    raw = raw.strip()
    if not raw:
        raise ShareLinkError("empty link")
    scheme = raw.split("://", 1)[0].lower()
    handler = _HANDLERS.get(scheme)
    if handler is None:
        raise ShareLinkError(f"unsupported scheme: {scheme}")
    try:
        return handler(raw)
    except ShareLinkError:
        raise
    except Exception as exc:  # noqa: BLE001 - normalize malformed links at the public boundary
        raise ShareLinkError(f"invalid {scheme} link: {exc}") from exc


# -- encode (reverse) -----------------------------------------------------


def _encode_vmess(p: Profile) -> str:
    vnext = p.outbound["settings"]["vnext"][0]
    user = vnext["users"][0]
    ss = p.outbound.get("streamSettings", {})
    net = ss.get("network", "tcp")
    data: dict = {
        "v": "2",
        "ps": p.name,
        "add": vnext["address"],
        "port": str(vnext["port"]),
        "id": user.get("id", ""),
        "aid": str(user.get("alterId", 0)),
        "scy": user.get("security", "auto"),
        "net": net,
        "type": "none",
        "host": "",
        "path": "",
        "tls": "",
        "sni": "",
        "alpn": "",
        "fp": "",
    }
    if net == "ws":
        ws = ss.get("wsSettings", {})
        data["path"] = ws.get("path", "")
        data["host"] = (ws.get("headers") or {}).get("Host", "")
    elif net == "grpc":
        data["path"] = ss.get("grpcSettings", {}).get("serviceName", "")
    if ss.get("security") == "tls":
        data["tls"] = "tls"
        tls = ss.get("tlsSettings", {})
        data["sni"] = tls.get("serverName", "")
        data["fp"] = tls.get("fingerprint", "")
        data["alpn"] = ",".join(tls.get("alpn", []))
    payload = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return "vmess://" + payload


def _encode_ss(p: Profile) -> str:
    srv = p.outbound["settings"]["servers"][0]
    userinfo = base64.urlsafe_b64encode(
        f"{srv['method']}:{srv['password']}".encode()
    ).decode().rstrip("=")
    link = f"ss://{userinfo}@{srv['address']}:{srv['port']}"
    if p.name:
        link += "#" + quote(p.name)
    return link


def _encode_proxy(p: Profile, scheme: str) -> str:
    srv = p.outbound["settings"]["servers"][0]
    userinfo = ""
    users = srv.get("users") or []
    if users:
        u = users[0]
        userinfo = f"{u.get('user', '')}:{u.get('pass', '')}@"
    link = f"{scheme}://{userinfo}{srv['address']}:{srv['port']}"
    if p.name:
        link += "#" + quote(p.name)
    return link


def encode_link(profile: Profile) -> str:
    """Reverse a Profile into a share link (for export)."""
    if profile.kind == "vmess":
        return _encode_vmess(profile)
    if profile.kind == "ss":
        return _encode_ss(profile)
    if profile.kind == "socks":
        return _encode_proxy(profile, "socks")
    if profile.kind == "http":
        return _encode_proxy(profile, "http")
    raise ShareLinkError(f"cannot encode kind: {profile.kind}")
