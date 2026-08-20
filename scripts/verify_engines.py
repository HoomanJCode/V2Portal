#!/usr/bin/env python3
"""Live verification of v2raycli's engine integration.

Downloads sing-box + xray, validates generated configs with each engine's own
check command, and runs end-to-end proxy smoke tests. Requires network access.

This is NOT part of the default test suite (it downloads binaries and reaches
out to the internet). Run it on any platform to confirm the engine layer works:

    pip install -e .          # or: PYTHONPATH=src python scripts/verify_engines.py
    python scripts/verify_engines.py
    python scripts/verify_engines.py --proxy socks5://127.0.0.1:10808

The optional proxy is used only for GitHub release metadata and binary
downloads; it is never written to the v2raycli config.

Exit code is non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from v2raycli.connection import ConnectionController, lan_ips
from v2raycli.engines import get_adapter
from v2raycli.engines.binary import download_binary, platform_name, arch_name
from v2raycli.models import Profile, RoutingConfig, RoutingRule
from v2raycli.outbounds.groups import create_balancer_group, create_chain_group, resolve_target
from v2raycli.storage import ConfigStore

TEST_URL = "http://example.com/"
SOCKS_OUTBOUND = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}
VMESS_OUTBOUND = {
    "settings": {
        "vnext": [
            {
                "address": "vm.example.com",
                "port": 443,
                "users": [{"id": "00000000-0000-0000-0000-000000000000", "alterId": 0, "security": "auto"}],
            }
        ]
    },
    "streamSettings": {"network": "tcp"},
}


class Checks:
    def __init__(self):
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((name, ok, detail))
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}" + (f"  {detail}" if detail else ""))
        return ok

    def summary(self) -> bool:
        failed = [r for r in self.results if not r[1]]
        print("\n" + ("ALL CHECKS PASSED" if not failed else f"{len(failed)} CHECK(S) FAILED"))
        return not failed


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def wait_port(port: int, timeout: float = 8.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def run_config(binary: Path, args: list[str], config_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run([str(binary), *args, str(config_path)], capture_output=True, text=True, timeout=30)


def socks_http_get(
    proxy_port: int, host: str, dst_port: int = 80, path: str = "/", timeout: float = 15.0, proxy_host: str = "127.0.0.1"
) -> str:
    """Do a SOCKS5 handshake then an HTTP GET over the tunnel; return status line."""
    sock = socket.create_connection((proxy_host, proxy_port), timeout=10)
    sock.settimeout(timeout)
    sock.sendall(b"\x05\x01\x00")
    if sock.recv(2) != b"\x05\x00":
        raise RuntimeError("socks5 greeting rejected")
    host_bytes = host.encode()
    sock.sendall(b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes + dst_port.to_bytes(2, "big"))
    reply = sock.recv(4)
    if reply[:2] != b"\x05\x00":
        raise RuntimeError(f"socks5 connect failed: {reply.hex()}")
    atyp = reply[3]
    if atyp == 1:
        sock.recv(6)
    elif atyp == 3:
        n = sock.recv(1)[0]
        sock.recv(n + 2)
    elif atyp == 4:
        sock.recv(18)
    sock.sendall(f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
    data = b""
    while True:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        data += chunk
    sock.close()
    return data.split(b"\r\n", 1)[0].decode(errors="replace")


def start_socks_server(binary: Path, port: int) -> subprocess.Popen:
    """Run a throwaway sing-box socks server (inbound -> direct) as an upstream."""
    config = {
        "inbounds": [{"type": "socks", "listen": "127.0.0.1", "listen_port": port}],
        "outbounds": [{"type": "direct", "tag": "direct"}],
        # Explicit DNS: Termux and minimal systems have no localhost resolver.
        "dns": {"servers": [{"type": "udp", "tag": "dns-1", "server": "1.1.1.1"}]},
        "route": {"final": "direct", "default_domain_resolver": "dns-1"},
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(config, fh)
        path = fh.name
    return subprocess.Popen([str(binary), "run", "-c", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def check_configs(checks: Checks, bin_dir: Path) -> None:
    store = ConfigStore(Path(tempfile.mkdtemp()) / "config.json")
    store.load()
    a = store.add_profile(Profile(name="s1", kind="socks", outbound=SOCKS_OUTBOUND))
    b = store.add_profile(Profile(name="s2", kind="socks", outbound=SOCKS_OUTBOUND))
    vm = store.add_profile(Profile(name="vm", kind="vmess", outbound=VMESS_OUTBOUND))
    wg = store.add_profile(
        Profile(
            name="wg",
            kind="wireguard",
            outbound={
                "settings": {
                    "secretKey": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=",
                    "address": ["10.0.0.2/32"],
                    "peers": [
                        {
                            "publicKey": "ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8=",
                            "endpoint": "1.2.3.4:51820",
                            "allowedIps": ["0.0.0.0/0"],
                        }
                    ],
                }
            },
        )
    )
    bal = store.add_group(create_balancer_group("bal", "latency", [a.id, b.id], store))
    chain = store.add_group(create_chain_group("chain", [a.id, b.id], store))
    wg_chain = store.add_group(create_chain_group("wg-chain", [vm.id, wg.id], store))
    wg_bal = store.add_group(create_balancer_group("wg-bal", "latency", [vm.id, wg.id], store))

    cases = [
        ("sing-box", "single", a, ["check", "-c"]),
        ("sing-box", "balancer", bal, ["check", "-c"]),
        ("sing-box", "chain", chain, ["check", "-c"]),
        ("sing-box", "vmess", vm, ["check", "-c"]),
        ("sing-box", "wireguard", wg, ["check", "-c"]),
        ("sing-box", "wireguard chain", wg_chain, ["check", "-c"]),
        ("sing-box", "wireguard balancer", wg_bal, ["check", "-c"]),
        ("xray", "single", a, ["run", "-test", "-config"]),
        ("xray", "vmess", vm, ["run", "-test", "-config"]),
        ("xray", "chain", chain, ["run", "-test", "-config"]),
    ]
    for engine, label, selection, check_args in cases:
        target = resolve_target(store, selection, default_engine=engine)
        cfg = get_adapter(engine).generate(store.config.settings, store.config.routing, target)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(cfg, fh)
            path = fh.name
        binary = bin_dir / ("sing-box" if engine == "sing-box" else "xray")
        result = run_config(binary, check_args, Path(path))
        checks.check(f"{engine} {label} config", result.returncode == 0, (result.stdout + result.stderr).strip().splitlines()[-1] if result.returncode else "")


def check_mixed_inbound(checks: Checks, singbox: Path) -> None:
    port = free_port()
    store = ConfigStore(Path(tempfile.mkdtemp()) / "config.json")
    store.load()
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS_OUTBOUND))
    target = resolve_target(store, profile, default_engine="sing-box")
    cfg = get_adapter("sing-box").generate(store.config.settings, store.config.routing, target)
    cfg["route"]["final"] = "direct"
    cfg["inbounds"][0]["listen"] = "127.0.0.1"
    cfg["inbounds"][0]["listen_port"] = port
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(cfg, fh)
        path = fh.name
    proc = subprocess.Popen([str(singbox), "run", "-c", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_port(port):
            checks.check("mixed inbound (engine start)", False, "port never opened")
            return
        import httpx
        with httpx.Client(proxy=f"http://127.0.0.1:{port}", timeout=15, follow_redirects=False) as client:
            r = client.get(TEST_URL)
            checks.check("mixed inbound HTTP proxy", 200 <= r.status_code < 400, f"status={r.status_code}")
        status = socks_http_get(port, "example.com")
        checks.check("mixed inbound SOCKS5", status.startswith("HTTP/1."), status)
    finally:
        stop(proc)


def check_outbound_routing(checks: Checks, singbox: Path) -> None:
    upstream_port = free_port()
    inbound_port = free_port()
    upstream = start_socks_server(singbox, upstream_port)
    try:
        if not wait_port(upstream_port):
            checks.check("outbound routing (upstream start)", False, "upstream port never opened")
            return

        store = ConfigStore(Path(tempfile.mkdtemp()) / "config.json")
        store.load()
        store.config.settings.mixed_port = inbound_port
        store.config.settings.listen = "127.0.0.1"
        profile = store.add_profile(
            Profile(
                name="upstream",
                kind="socks",
                outbound={"settings": {"servers": [{"address": "127.0.0.1", "port": upstream_port}]}},
            )
        )

        controller = ConnectionController(store, bin_dir=singbox.parent, runtime_dir=Path(tempfile.mkdtemp()))
        status = controller.connect(profile)
        if status.state != "connected":
            checks.check("outbound routing (connect)", False, status.error or status.state)
            return
        try:
            if not wait_port(inbound_port):
                checks.check("outbound routing (inbound listen)", False, "inbound port never opened")
                return
            checks.check("outbound routing (connect)", True, f"engine={status.engine}")
            line = socks_http_get(inbound_port, "example.com")
            checks.check("outbound routing (egress via socks outbound)", line.startswith("HTTP/1."), line)
        finally:
            controller.disconnect()
    finally:
        stop(upstream)


def _socks_profile(name: str, port: int) -> Profile:
    return Profile(
        name=name,
        kind="socks",
        outbound={"settings": {"servers": [{"address": "127.0.0.1", "port": port}]}},
    )


def check_chain(checks: Checks, singbox: Path) -> None:
    hop1_port, hop2_port, inbound_port = free_port(), free_port(), free_port()
    hop1 = start_socks_server(singbox, hop1_port)
    hop2 = start_socks_server(singbox, hop2_port)
    try:
        if not (wait_port(hop1_port) and wait_port(hop2_port)):
            checks.check("chain (upstreams)", False, "upstream ports never opened")
            return
        store = ConfigStore(Path(tempfile.mkdtemp()) / "config.json")
        store.load()
        store.config.settings.mixed_port = inbound_port
        store.config.settings.listen = "127.0.0.1"
        a = store.add_profile(_socks_profile("hop1", hop1_port))
        b = store.add_profile(_socks_profile("hop2", hop2_port))
        chain = store.add_group(create_chain_group("chain", [a.id, b.id], store))

        controller = ConnectionController(store, bin_dir=singbox.parent, runtime_dir=Path(tempfile.mkdtemp()))
        status = controller.connect(chain)
        if status.state != "connected":
            checks.check("chain (connect)", False, status.error or status.state)
            return
        try:
            if not wait_port(inbound_port):
                checks.check("chain egress (2 hops)", False, "inbound port never opened")
                return
            line = socks_http_get(inbound_port, "example.com")
            checks.check("chain egress (2 hops)", line.startswith("HTTP/1."), line)
        finally:
            controller.disconnect()

        # Negative control: a dead first hop must break egress (proves the chain
        # actually routes through hop 1, not straight to hop 2).
        dead = free_port()
        a2 = store.add_profile(_socks_profile("dead", dead))
        chain2 = store.add_group(create_chain_group("chain2", [a2.id, b.id], store))
        status2 = controller.connect(chain2)
        if status2.state != "connected":
            checks.check("chain dead-hop (connect)", False, status2.error or status2.state)
            return
        try:
            if not wait_port(inbound_port):
                checks.check("chain dead first hop fails", False, "inbound port never opened")
                return
            try:
                line = socks_http_get(inbound_port, "example.com")
                checks.check("chain dead first hop fails", False, f"unexpected success: {line}")
            except Exception as exc:
                checks.check("chain dead first hop fails", True, type(exc).__name__)
        finally:
            controller.disconnect()
    finally:
        stop(hop1)
        stop(hop2)


def check_split_routing(checks: Checks, singbox: Path) -> None:
    dead, inbound_port = free_port(), free_port()  # dead port = the "proxy"
    store = ConfigStore(Path(tempfile.mkdtemp()) / "config.json")
    store.load()
    store.config.settings.mixed_port = inbound_port
    store.config.settings.listen = "127.0.0.1"
    proxy = store.add_profile(_socks_profile("proxy", dead))
    store.config.routing = RoutingConfig(
        mode="split",
        rules=[RoutingRule(action="direct", match={"domains": ["example.com"]})],
    )

    controller = ConnectionController(store, bin_dir=singbox.parent, runtime_dir=Path(tempfile.mkdtemp()))
    status = controller.connect(proxy)
    if status.state != "connected":
        checks.check("split routing (connect)", False, status.error or status.state)
        return
    try:
        if not wait_port(inbound_port):
            checks.check("split routing (inbound listen)", False, "inbound port never opened")
            return
        try:
            line = socks_http_get(inbound_port, "example.com")
            checks.check("split routing direct rule", line.startswith("HTTP/1."), line)
        except Exception as exc:
            checks.check("split routing direct rule", False, type(exc).__name__)
        try:
            line2 = socks_http_get(inbound_port, "www.gstatic.com")
            checks.check("split routing fallthrough to proxy", False, f"unexpected: {line2}")
        except Exception as exc:
            checks.check("split routing fallthrough to proxy", True, type(exc).__name__)
    finally:
        controller.disconnect()


def check_lan_binding(checks: Checks, singbox: Path) -> None:
    ips = lan_ips()
    if not ips:
        checks.check("LAN binding", False, "no LAN IP detected")
        return
    port = free_port()
    store = ConfigStore(Path(tempfile.mkdtemp()) / "config.json")
    store.load()
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS_OUTBOUND))
    target = resolve_target(store, profile, default_engine="sing-box")
    cfg = get_adapter("sing-box").generate(store.config.settings, store.config.routing, target)
    cfg["route"]["final"] = "direct"
    cfg["inbounds"][0]["listen"] = "0.0.0.0"
    cfg["inbounds"][0]["listen_port"] = port
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(cfg, fh)
        path = fh.name
    proc = subprocess.Popen([str(singbox), "run", "-c", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_port(port):
            checks.check("LAN binding (engine start)", False, "port never opened")
            return
        line = socks_http_get(port, "example.com", proxy_host=ips[0])
        checks.check(f"LAN binding (0.0.0.0 via {ips[0]})", line.startswith("HTTP/1."), line)
    finally:
        stop(proc)


def check_traffic_stats(checks: Checks, singbox: Path) -> None:
    """Confirm the sing-box Clash API meters real traffic and the controller records it."""
    import http.server
    import socketserver
    import threading

    upstream_port, inbound_port, api_port = free_port(), free_port(), free_port()
    upstream = start_socks_server(singbox, upstream_port)
    try:
        if not wait_port(upstream_port):
            checks.check("traffic stats (upstream)", False, "upstream port never opened")
            return

        # Serve a local file so this check doesn't depend on internet egress.
        www = Path(tempfile.mkdtemp())
        (www / "big.bin").write_bytes(b"x" * 300_000)

        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def translate_path(self, path):
                return str(www / path.lstrip("/"))

        httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        http_port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        store = ConfigStore(Path(tempfile.mkdtemp()) / "config.json")
        store.load()
        store.config.settings.mixed_port = inbound_port
        store.config.settings.listen = "127.0.0.1"
        store.config.settings.traffic_api = True
        store.config.settings.traffic_api_port = api_port
        profile = store.add_profile(_socks_profile("up", upstream_port))

        controller = ConnectionController(store, bin_dir=singbox.parent, runtime_dir=Path(tempfile.mkdtemp()))
        status = controller.connect(profile)
        if status.state != "connected":
            checks.check("traffic stats (connect)", False, status.error or status.state)
            return
        try:
            if not wait_port(inbound_port):
                checks.check("traffic stats (inbound listen)", False, "inbound port never opened")
                return
            import httpx

            with httpx.Client(proxy=f"http://127.0.0.1:{inbound_port}", timeout=20) as client:
                resp = client.get(f"http://127.0.0.1:{http_port}/big.bin")
                checks.check("traffic stats (egress)", resp.status_code == 200, f"status={resp.status_code}")
            time.sleep(0.5)
            live = controller.traffic()
            checks.check(
                "traffic stats (meter)",
                bool(live and live["down"] > 100_000),
                f"live={live}",
            )
        finally:
            controller.disconnect()
            httpd.shutdown()

        checks.check(
            "traffic stats (recorded)",
            profile.traffic_down > 100_000,
            f"profile.traffic_down={profile.traffic_down}",
        )
    finally:
        stop(upstream)


def check_websocket_transport(checks: Checks, singbox: Path) -> None:
    """Drive the SOCKS-connect + WebSocket handshake/ping probe path live."""
    import base64
    import hashlib
    import threading

    from v2raycli.test import latency

    ws_port, proxy_port = free_port(), free_port()
    ready = threading.Event()
    guid = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def ws_server() -> None:
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", ws_port))
        server.listen(1)
        ready.set()
        try:
            conn, _ = server.accept()
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
            key = next(
                (
                    line.split(": ", 1)[1]
                    for line in data.decode("latin-1").split("\r\n")
                    if line.lower().startswith("sec-websocket-key")
                ),
                "",
            )
            accept = base64.b64encode(hashlib.sha1((key + guid).encode()).digest()).decode()
            conn.sendall(
                (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                ).encode("ascii")
            )
            header = conn.recv(2)
            if len(header) == 2:
                length = header[1] & 0x7F
                mask = conn.recv(4) if header[1] & 0x80 else b""
                payload = b""
                while len(payload) < length:
                    payload += conn.recv(length - len(payload))
                if mask:
                    payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
                conn.sendall(bytes([0x8A, length]) + payload)
            conn.close()
        finally:
            server.close()

    threading.Thread(target=ws_server, daemon=True).start()
    proxy = start_socks_server(singbox, proxy_port)
    try:
        if not (wait_port(proxy_port) and ready.wait(timeout=8)):
            checks.check("websocket transport (setup)", False, "proxy or ws server never started")
            return
        sock = latency._socks_connect(proxy_port, "127.0.0.1", ws_port, 5.0)
        try:
            ok, ms, status = latency._websocket_handshake(sock, "127.0.0.1", "/", {})
            checks.check("websocket handshake", ok, f"status={status} ms={ms:.1f}")
            if ok:
                pok, pms, pstatus = latency._websocket_ping(sock, timeout=5.0)
                checks.check("websocket ping/pong", pok, f"status={pstatus} ms={pms:.1f}")
        finally:
            sock.close()
    finally:
        stop(proxy)


def acquire_binaries(
    checks: Checks,
    bin_dir: Path,
    *,
    skip_download: bool = False,
    proxy: str | None = None,
) -> dict[str, Path]:
    """Resolve both engine binaries and report failures without raising.

    The live checks require both engines. A failed download should be reported
    as a normal verification result instead of producing a second, misleading
    missing-file traceback from the engine checks.
    """
    binaries: dict[str, Path] = {}
    for engine in ("sing-box", "xray"):
        binary = bin_dir / engine
        try:
            if not skip_download or not binary.exists():
                binary = download_binary(
                    engine,
                    "latest",
                    platform_name(),
                    arch_name(),
                    bin_dir=bin_dir,
                    proxy=proxy,
                )
            if not binary.exists():
                raise FileNotFoundError(binary)
        except Exception as exc:  # pragma: no cover - network/platform dependent
            checks.check(f"{engine} binary", False, f"{type(exc).__name__}: {exc}")
            continue
        checks.check(f"{engine} binary", True, str(binary))
        binaries[engine] = binary
    return binaries


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify v2raycli engine integration live.")
    parser.add_argument("--bin-dir", type=Path, default=None, help="cache engine binaries here")
    parser.add_argument("--skip-download", action="store_true", help="reuse --bin-dir binaries, don't download")
    parser.add_argument(
        "--proxy",
        metavar="URL",
        help="optional HTTP/SOCKS proxy for GitHub metadata and binary downloads (not stored)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    checks = Checks()
    bin_dir = args.bin_dir or Path(tempfile.mkdtemp(prefix="v2raycli-verify-"))
    bin_dir.mkdir(parents=True, exist_ok=True)

    binaries = acquire_binaries(
        checks,
        bin_dir,
        skip_download=args.skip_download,
        proxy=args.proxy,
    )
    if len(binaries) != 2:
        checks.check("engine checks", False, "skipped because both engine binaries are required")
        return 0 if checks.summary() else 1

    check_configs(checks, bin_dir)
    check_mixed_inbound(checks, bin_dir / "sing-box")
    check_outbound_routing(checks, bin_dir / "sing-box")
    check_chain(checks, bin_dir / "sing-box")
    check_split_routing(checks, bin_dir / "sing-box")
    check_lan_binding(checks, bin_dir / "sing-box")
    check_traffic_stats(checks, bin_dir / "sing-box")
    check_websocket_transport(checks, bin_dir / "sing-box")

    return 0 if checks.summary() else 1


if __name__ == "__main__":
    sys.exit(main())
