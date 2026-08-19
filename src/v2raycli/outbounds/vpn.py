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
    vpn: dict = {
        "type": "openconnect",
        "server": server,
        "args": list(args) if args else [],
        "auth_hint": auth_hint or "",
    }
    return Profile(name=name, kind="openconnect", engine="auto", outbound={}, vpn=vpn, source="manual")
