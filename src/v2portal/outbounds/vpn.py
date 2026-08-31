"""OpenVPN / OpenConnect VPN profile helpers.

VPN profiles run the system client directly and are intentionally excluded
from proxy chaining/balancing.
"""

from __future__ import annotations

import shutil

from ..models import Profile

VPN_KINDS = ("openvpn", "openconnect")


def detect_clients() -> dict[str, str | None]:
    """Return the detected path (or None) for each VPN client binary."""
    return {
        "openvpn": shutil.which("openvpn"),
        "openconnect": shutil.which("openconnect"),
    }


def is_vpn(profile: Profile) -> bool:
    return profile.kind in VPN_KINDS


def client_install_hint(kind: str) -> str:
    """Return an actionable message for a missing system VPN client."""
    if kind not in VPN_KINDS:
        return f"unsupported VPN kind: {kind}"
    return f"{kind} client not found on PATH; install {kind} and ensure it is available on PATH"


def validate_vpn_profile(profile: Profile) -> dict:
    """Validate a persisted VPN profile before constructing client argv."""
    if not isinstance(profile, Profile) or profile.kind not in VPN_KINDS:
        raise ValueError("profile is not a supported VPN")
    vpn = profile.vpn
    if not isinstance(vpn, dict):
        raise ValueError(f"{profile.kind} profile is missing vpn settings")
    vpn_type = vpn.get("type", profile.kind)
    if vpn_type != profile.kind or vpn_type not in VPN_KINDS:
        raise ValueError(f"{profile.kind} profile has an invalid VPN type")
    args = vpn.get("args", [])
    if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
        raise ValueError(f"{profile.kind} VPN args must be a list of text")

    if profile.kind == "openvpn":
        config_path = vpn.get("config_path")
        inline = vpn.get("inline")
        if config_path is not None and (not isinstance(config_path, str) or not config_path.strip()):
            raise ValueError("openvpn config_path must be non-empty text")
        if inline is not None and (not isinstance(inline, str) or not inline):
            raise ValueError("openvpn inline config must be non-empty text")
        if not config_path and not inline:
            raise ValueError("openvpn profile needs a config_path or inline config")
    else:
        server = vpn.get("server")
        if not isinstance(server, str) or not server.strip():
            raise ValueError("openconnect profile needs a server")
        auth_hint = vpn.get("auth_hint")
        if auth_hint is not None and not isinstance(auth_hint, str):
            raise ValueError("openconnect auth_hint must be text")
    return vpn


def add_openvpn(
    name: str,
    config_path: str | None = None,
    inline: str | None = None,
    args: list[str] | None = None,
) -> Profile:
    if not config_path and not inline:
        raise ValueError("openvpn profile needs a config_path or inline config")
    vpn: dict = {"type": "openvpn", "args": list(args) if args else []}
    if config_path:
        vpn["config_path"] = str(config_path)
    if inline:
        vpn["inline"] = inline
    return Profile(name=name, kind="openvpn", engine="auto", outbound={}, vpn=vpn, source="manual")


def add_openconnect(
    name: str,
    server: str,
    args: list[str] | None = None,
    auth_hint: str | None = None,
) -> Profile:
    if not server or not server.strip():
        raise ValueError("openconnect profile needs a server")
    vpn: dict = {
        "type": "openconnect",
        "server": server,
        "args": list(args) if args else [],
        "auth_hint": auth_hint or "",
    }
    return Profile(name=name, kind="openconnect", engine="auto", outbound={}, vpn=vpn, source="manual")
