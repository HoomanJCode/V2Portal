"""Connection lifecycle: run an engine (or VPN client) for a selected target."""

from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .engines import get_adapter
from .engines.base import validate_config, write_runtime_config
from .engines.binary import BinaryError, locate_binary
from .geo import GeoError, ensure_geo_assets
from .outbounds.groups import resolve_target
from .outbounds.vpn import VPN_KINDS, client_install_hint, detect_clients
from .routing.rules import uses_geo
from .runner import Proc


class ConnectionError(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ConnectionStatus:
    state: str = "idle"  # idle | connected | error
    target_name: str = ""
    engine: str = ""
    inbound: dict = field(default_factory=dict)
    pid: int | None = None
    started_at: str | None = None
    error: str | None = None


def lan_ips() -> list[str]:
    """Best-effort detection of this host's IPv4 LAN address.

    Uses a UDP connect to discover the source address without sending any
    packets, so it stays fast and works offline.
    """
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
        probe.close()
        return [ip] if ip and ip != "0.0.0.0" else []
    except Exception:
        return []


class ConnectionController:
    def __init__(
        self,
        store,
        bin_dir: Path | None = None,
        runtime_dir: Path | None = None,
        geo_dir: Path | None = None,
    ):
        self.store = store
        self.bin_dir = bin_dir
        self.runtime_dir = runtime_dir
        self.geo_dir = geo_dir
        self.proc = Proc()
        self.status = ConnectionStatus()
        self._selection = None

    # -- public API ---------------------------------------------------------

    def connect(self, selection) -> ConnectionStatus:
        self.disconnect()
        self._selection = selection
        target = None
        engine_label = ""
        try:
            target = resolve_target(
                self.store, selection, default_engine=self.store.config.settings.default_engine
            )
            is_vpn = target.type == "single" and target.profiles and target.profiles[0].kind in VPN_KINDS
            engine_label = target.profiles[0].kind if is_vpn else target.engine
            if is_vpn:
                return self._connect_vpn(target.profiles[0])
            return self._connect_proxy(target)
        except (ConnectionError, BinaryError, OSError, TypeError, ValueError) as exc:
            self._selection = None
            self.status = ConnectionStatus(
                state="error",
                target_name=target.name if target is not None else getattr(selection, "name", ""),
                engine=engine_label if target is not None else "",
                error=str(exc),
            )
            return self.status

    def switch(self, selection) -> ConnectionStatus:
        return self.connect(selection)

    def disconnect(self) -> None:
        self._record_traffic()
        self.proc.stop()
        self.status = ConnectionStatus()
        self._selection = None

    def traffic(self) -> dict | None:
        """Return the engine's cumulative ``{"up", "down"}`` bytes, or None."""
        settings = self.store.config.settings
        if not settings.traffic_api or self.status.state != "connected":
            return None
        from .traffic import read_traffic

        return read_traffic("127.0.0.1", settings.traffic_api_port)

    def _record_traffic(self) -> None:
        """Accumulate this session's traffic onto the connected target."""
        selection = self._selection
        if selection is None:
            return
        current = self.traffic()
        if not current:
            return
        try:
            up = int(current.get("up", 0))
            down = int(current.get("down", 0))
        except (AttributeError, TypeError, ValueError):
            return
        if up < 0 or down < 0:
            return
        try:
            existing_up = int(selection.traffic_up)
            existing_down = int(selection.traffic_down)
        except (AttributeError, TypeError, ValueError):
            return
        if existing_up < 0 or existing_down < 0:
            return
        selection.traffic_up = existing_up + up
        selection.traffic_down = existing_down + down
        try:
            self.store.save()
        except OSError:
            pass

    # -- proxy connections --------------------------------------------------

    def _connect_proxy(self, target) -> ConnectionStatus:
        settings = self.store.config.settings
        adapter = get_adapter(target.engine)
        cfg = adapter.generate(settings, self.store.config.routing, target)
        path = write_runtime_config(target.engine, cfg, runtime_dir=self.runtime_dir)

        options = self.store.config.engines.get(target.engine, {})
        try:
            binary = locate_binary(target.engine, options, bin_dir=self.bin_dir)
        except BinaryError as exc:
            raise ConnectionError(f"missing binary for {target.engine}: {exc}") from exc

        env = None
        if target.engine == "xray" and uses_geo(self.store.config.routing):
            try:
                geo_dir = ensure_geo_assets("xray", geo_dir=self.geo_dir)
            except GeoError as exc:
                raise ConnectionError(f"geo assets: {exc}") from exc
            env = {**os.environ, "XRAY_LOCATION_ASSET": str(geo_dir)}

        try:
            validate_config(target.engine, path, binary=binary, env=env)
        except RuntimeError as exc:
            raise ConnectionError(f"invalid config: {exc}") from exc

        self.proc.start([str(binary), *adapter.run_args(str(path))], env=env)
        time.sleep(0.2)
        if not self.proc.is_running():
            tail = " ".join(self.proc.logs()[-3:])
            self.proc.stop()
            raise ConnectionError(f"{target.engine} exited immediately: {tail}")

        self.status = ConnectionStatus(
            state="connected",
            target_name=target.name,
            engine=target.engine,
            inbound=self._inbound_info(settings, target.engine),
            pid=self.proc.pid,
            started_at=_now(),
        )
        return self.status

    def _inbound_info(self, settings, engine: str = "sing-box") -> dict:
        port = settings.mixed_port
        listen = settings.listen if settings.allow_lan else "127.0.0.1"
        host = listen if listen not in ("0.0.0.0", "", None) else "0.0.0.0"
        http_port = port + 1 if engine == "xray" else port
        info: dict = {
            "listen": listen,
            "mixed_port": port,
            "urls": [f"socks5://{host}:{port}", f"http://{host}:{http_port}"],
        }
        if engine == "xray":
            info["http_port"] = http_port
        if settings.inbound_auth.get("enabled"):
            info["auth"] = {
                "username": settings.inbound_auth["username"],
                "password": settings.inbound_auth["password"],
            }
        if settings.allow_lan and listen in ("0.0.0.0", ""):
            info["lan"] = [f"http://{ip}:{http_port}" for ip in lan_ips()]
        return info

    # -- VPN connections ----------------------------------------------------

    def _connect_vpn(self, profile) -> ConnectionStatus:
        clients = detect_clients()
        vpn = profile.vpn or {}
        vtype = vpn.get("type") or profile.kind
        if vtype == "openvpn":
            config_path = vpn.get("config_path")
            if config_path:
                if not Path(config_path).is_file():
                    raise ConnectionError(f"openvpn config not found: {config_path}")
            elif not vpn.get("inline"):
                raise ConnectionError("openvpn profile needs a config_path or inline config")
        elif vtype == "openconnect" and not str(vpn.get("server", "")).strip():
            raise ConnectionError("openconnect profile needs a server")
        if vtype not in VPN_KINDS:
            raise ConnectionError(f"unsupported VPN kind: {vtype}")
        client = clients.get(vtype)
        if not client:
            raise ConnectionError(client_install_hint(vtype))

        argv = self.vpn_argv(vtype, client, vpn, profile)
        self.proc.start(argv)
        time.sleep(0.2)
        if not self.proc.is_running():
            tail = " ".join(self.proc.logs()[-3:])
            self.proc.stop()
            raise ConnectionError(f"{vtype} exited immediately: {tail}")

        self.status = ConnectionStatus(
            state="connected",
            target_name=profile.name,
            engine=vtype,
            inbound={},
            pid=self.proc.pid,
            started_at=_now(),
        )
        return self.status

    def vpn_argv(self, vtype: str, client: str, vpn: dict, profile) -> list[str]:
        argv = [client, *vpn.get("args", [])]
        if vtype == "openvpn":
            if vpn.get("config_path"):
                argv += ["--config", str(vpn["config_path"])]
            elif vpn.get("inline"):
                argv += ["--config", str(self._write_inline(vpn["inline"], profile.id))]
        elif vtype == "openconnect":
            argv += [vpn.get("server", "")]
        return argv

    def _write_inline(self, inline: str, name: str) -> Path:
        directory = self.runtime_dir or config.RUNTIME_DIR
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name}.ovpn"
        path.write_text(inline, encoding="utf-8")
        return path
