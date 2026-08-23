"""Engine-aware outbound latency / reachability testing.

Each profile is tested by launching a short-lived engine with a local SOCKS
inbound routed through that profile, then timing an HTTP request through it.
"""

from __future__ import annotations

import base64
import errno
import hashlib
import json
import math
import os
import secrets
import socket
import ssl
import struct
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, replace

from .. import config
from ..engines import get_adapter, resolve_engine
from ..engines.binary import BinaryError, locate_binary
from ..models import Profile, RoutingConfig
from ..outbounds.groups import Target
from ..outbounds.vpn import VPN_KINDS
from ..runner import Proc


@dataclass
class EndpointResult:
    profile_id: str = ""
    name: str = ""
    kind: str = ""
    host: str = ""
    port: int | None = None
    icmp_ms: float | None = None
    icmp_status: str = "not_testable"
    tcp_ms: float | None = None
    tcp_status: str = "not_testable"
    error: str | None = None


@dataclass
class WebSocketResult:
    profile_id: str = ""
    name: str = ""
    kind: str = ""
    engine: str = ""
    host: str = ""
    port: int | None = None
    handshake_ms: float | None = None
    handshake_status: str = "not_testable"
    payload_ms: float | None = None
    payload_status: str = "not_testable"
    error: str | None = None
    not_testable: bool = False


@dataclass
class TestResult:
    __test__ = False  # a dataclass, not a pytest test class

    profile_id: str = ""
    name: str = ""
    kind: str = ""
    engine: str = ""
    ok: bool = False
    latency_ms: float | None = None
    connect_ms: float | None = None
    error: str | None = None
    not_testable: bool = False


def _normalized_port(value) -> int | None:
    if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
        return None
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def _split_endpoint(value) -> tuple[str, int | None]:
    if not isinstance(value, str) or not value.strip():
        return "", None
    value = value.strip()
    if value.startswith("["):
        end = value.find("]")
        if end < 0:
            return "", None
        host = value[1:end]
        port_text = value[end + 1 :].lstrip(":")
    else:
        host, separator, port_text = value.rpartition(":")
        if not separator:
            return value, None
    return host, _normalized_port(port_text)


def profile_endpoint(profile) -> tuple[str, int | None]:
    """Extract the first remote endpoint from a supported profile shape."""
    outbound = profile.outbound if isinstance(profile.outbound, dict) else {}
    server = outbound.get("server")
    port = outbound.get("server_port")
    if isinstance(server, str) and server.strip():
        return server.strip(), _normalized_port(port)

    settings = outbound.get("settings")
    if isinstance(settings, dict):
        servers = settings.get("vnext") or settings.get("servers")
        if isinstance(servers, list) and servers and isinstance(servers[0], dict):
            remote = servers[0]
            address = remote.get("address")
            remote_port = remote.get("port")
            if isinstance(address, str) and address.strip():
                return address.strip(), _normalized_port(remote_port)
        peers = settings.get("peers")
        if isinstance(peers, list) and peers and isinstance(peers[0], dict):
            return _split_endpoint(peers[0].get("endpoint"))
    return "", None


def _icmp_probe(host: str, timeout: float = 3.0) -> tuple[float | None, str]:
    """Probe one host with the platform ping utility."""
    if not host:
        return None, "not_testable"
    started = time.monotonic()
    if os.name == "nt":
        argv = ["ping", "-n", "1", "-w", str(max(1, math.ceil(timeout * 1000))), host]
    else:
        argv = ["ping", "-c", "1", "-W", str(max(1, math.ceil(timeout))), host]
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout + 1.0)
    except FileNotFoundError:
        return None, "unsupported"
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except OSError:
        return None, "unsupported"
    if result.returncode == 0:
        return (time.monotonic() - started) * 1000.0, "ok"
    return None, "blocked"


def _tcp_probe(host: str, port: int | None, timeout: float = 5.0) -> tuple[float | None, str]:
    """Measure a direct TCP connection and preserve common failure classes."""
    if not host or port is None:
        return None, "not_testable"
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return (time.monotonic() - started) * 1000.0, "ok"
    except socket.gaierror:
        return None, "dns_error"
    except TimeoutError:
        return None, "timeout"
    except OSError as exc:
        if exc.errno in (errno.ECONNREFUSED, 10061):
            return None, "refused"
        if exc.errno in (errno.ETIMEDOUT, 10060):
            return None, "timeout"
        return None, "error"


def probe_endpoint(profile, timeout: float = 5.0) -> EndpointResult:
    host, port = profile_endpoint(profile)
    result = EndpointResult(
        profile_id=profile.id,
        name=profile.name,
        kind=profile.kind,
        host=host,
        port=port,
    )
    if not host or port is None:
        result.tcp_status = "invalid"
        result.error = "profile has no valid remote endpoint"
        return result
    result.icmp_ms, result.icmp_status = _icmp_probe(host, min(timeout, 3.0))
    result.tcp_ms, result.tcp_status = _tcp_probe(host, port, timeout)
    if result.tcp_status not in ("ok", "not_testable"):
        result.error = f"tcp {result.tcp_status}"
    return result


def probe_many(profiles, concurrency: int = 8, timeout: float = 5.0) -> list[EndpointResult]:
    """Probe endpoints concurrently while preserving profile input order."""
    import sys
    total = len(profiles)
    results: dict[str, EndpointResult] = {}
    workers = max(1, min(int(concurrency), 32))
    if sys.stderr.isatty():
        print(f"\rprobing {total} endpoints…", end="", file=sys.stderr, flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(probe_endpoint, profile, timeout): profile.id for profile in profiles}
        for future in as_completed(futures):
            result = future.result()
            results[result.profile_id] = result
            if sys.stderr.isatty():
                done = len(results)
                print(f"\rprobing {done}/{total}…", end="", file=sys.stderr, flush=True)
    if sys.stderr.isatty():
        print("\rdone.              ", file=sys.stderr)
    return [results[profile.id] for profile in profiles]


def render_endpoint_table(results: list[EndpointResult]) -> None:
    from rich.console import Console
    from rich.table import Table

    table = Table(title="Endpoint probes")
    for column in ("ID", "Name", "Endpoint", "ICMP", "TCP", "Status"):
        table.add_column(column)
    for result in results:
        icmp = f"{result.icmp_ms:.0f} ms" if result.icmp_ms is not None else result.icmp_status
        tcp = f"{result.tcp_ms:.0f} ms" if result.tcp_ms is not None else result.tcp_status
        status = "OK" if result.tcp_status == "ok" else (result.error or result.tcp_status)
        style = "green" if result.tcp_status == "ok" else "red"
        table.add_row(result.profile_id, result.name, f"{result.host}:{result.port or '-'}", icmp, tcp, status, style=style)
    Console().print(table)


def websocket_transport(profile) -> dict | None:
    """Return normalized Xray WS/WSS settings, or None for other transports."""
    outbound = profile.outbound if isinstance(profile.outbound, dict) else {}
    stream = outbound.get("streamSettings")
    if not isinstance(stream, dict) or stream.get("network") != "ws":
        return None
    ws = stream.get("wsSettings") or {}
    if not isinstance(ws, dict):
        return None
    tls = stream.get("tlsSettings") or {}
    if not isinstance(tls, dict):
        return None
    headers = ws.get("headers") or {}
    if not isinstance(headers, dict):
        return None
    host, _ = profile_endpoint(profile)
    host_header = headers.get("Host") or host
    if not isinstance(host_header, str) or not host_header.strip():
        return None
    path = ws.get("path") or "/"
    if not isinstance(path, str) or not path.startswith("/"):
        return None
    security = stream.get("security", "none")
    if security not in ("none", "tls"):
        return None
    server_name = tls.get("serverName") or host
    if not isinstance(server_name, str) or not server_name.strip():
        return None
    if any(
        isinstance(value, str) and ("\r" in value or "\n" in value)
        for value in (host_header, path, server_name, *headers.values())
    ):
        return None
    return {
        "secure": security == "tls",
        "host": host_header.strip(),
        "server_name": server_name.strip(),
        "path": path,
        "headers": {
            key: value for key, value in headers.items()
            if isinstance(key, str) and isinstance(value, str) and key.lower() != "host"
        },
        "allow_insecure": bool(tls.get("allowInsecure")),
    }


def _recv_exact(sock, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise OSError("connection closed while receiving WebSocket data")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_headers(sock, limit: int = 65536) -> bytes:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(min(4096, limit - len(data)))
        if not chunk:
            raise OSError("connection closed during WebSocket handshake")
        data.extend(chunk)
        if len(data) >= limit:
            raise OSError("WebSocket handshake headers are too large")
    return bytes(data)


def _websocket_handshake(sock, host: str, path: str, headers: dict, timeout: float = 5.0) -> tuple[bool, float, str]:
    """Perform and validate the RFC 6455 HTTP upgrade handshake."""
    started = time.monotonic()
    key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
    request_headers = {
        "Host": host,
        "Upgrade": "websocket",
        "Connection": "Upgrade",
        "Sec-WebSocket-Key": key,
        "Sec-WebSocket-Version": "13",
        **headers,
    }
    request = [f"GET {path} HTTP/1.1"]
    request.extend(f"{name}: {value}" for name, value in request_headers.items())
    sock.settimeout(timeout)
    sock.sendall(("\r\n".join(request) + "\r\n\r\n").encode("ascii"))
    response = _recv_headers(sock).split(b"\r\n\r\n", 1)[0].decode("latin-1")
    lines = response.split("\r\n")
    status = lines[0].split(" ", 2) if lines else []
    response_headers = {}
    for line in lines[1:]:
        name, separator, value = line.partition(":")
        if separator:
            response_headers[name.strip().lower()] = value.strip()
    expected = base64.b64encode(
        hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
    ).decode("ascii")
    elapsed = (time.monotonic() - started) * 1000.0
    if len(status) < 2 or status[1] != "101":
        return False, elapsed, "handshake_status"
    if response_headers.get("upgrade", "").lower() != "websocket":
        return False, elapsed, "handshake_upgrade"
    if response_headers.get("sec-websocket-accept") != expected:
        return False, elapsed, "handshake_accept"
    return True, elapsed, "ok"


def _websocket_ping(sock, payload: bytes = b"v2raycli", timeout: float = 5.0) -> tuple[bool, float, str]:
    """Send a masked client ping and require the matching server pong."""
    started = time.monotonic()
    mask = secrets.token_bytes(4)
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    if len(payload) < 126:
        frame = bytes((0x89, 0x80 | len(payload))) + mask + masked
    elif len(payload) <= 65535:
        frame = bytes((0x89, 0xFE)) + struct.pack("!H", len(payload)) + mask + masked
    else:
        raise ValueError("WebSocket ping payload is too large")
    sock.settimeout(timeout)
    sock.sendall(frame)
    first, second = _recv_exact(sock, 2)
    opcode = first & 0x0F
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _recv_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _recv_exact(sock, 8))[0]
    if second & 0x80:
        response_mask = _recv_exact(sock, 4)
    else:
        response_mask = b""
    response = _recv_exact(sock, length)
    if response_mask:
        response = bytes(value ^ response_mask[index % 4] for index, value in enumerate(response))
    elapsed = (time.monotonic() - started) * 1000.0
    if opcode != 0x0A or response != payload:
        return False, elapsed, "payload_invalid"
    return True, elapsed, "ok"


def _socks_connect(local_port: int, host: str, port: int, timeout: float) -> socket.socket:
    """Connect to a remote host through the local SOCKS5 inbound."""
    sock = socket.create_connection(("127.0.0.1", local_port), timeout=timeout)
    try:
        sock.settimeout(timeout)
        if _recv_exact_after_send(sock, b"\x05\x01\x00", 2) != b"\x05\x00":
            raise OSError("local SOCKS5 proxy rejected unauthenticated handshake")
        encoded_host = host.encode("idna")
        if not 1 <= len(encoded_host) <= 255:
            raise OSError("remote host is not valid for SOCKS5")
        request = b"\x05\x01\x00\x03" + bytes([len(encoded_host)]) + encoded_host + port.to_bytes(2, "big")
        reply = _recv_exact_after_send(sock, request, 4)
        if reply[:2] != b"\x05\x00":
            raise OSError(f"SOCKS5 CONNECT failed ({reply[1] if len(reply) > 1 else 'unknown'})")
        atyp = reply[3]
        if atyp == 1:
            _recv_exact(sock, 6)
        elif atyp == 3:
            length = _recv_exact(sock, 1)[0]
            _recv_exact(sock, length + 2)
        elif atyp == 4:
            _recv_exact(sock, 18)
        else:
            raise OSError("SOCKS5 proxy returned an invalid address type")
        return sock
    except Exception:
        sock.close()
        raise


def _recv_exact_after_send(sock, data: bytes, size: int) -> bytes:
    sock.sendall(data)
    return _recv_exact(sock, size)


def _websocket_probe(profile, local_port: int, timeout: float = 5.0) -> tuple[str, int | None, str, float | None, str, float | None, str | None]:
    transport = websocket_transport(profile)
    host, port = profile_endpoint(profile)
    if transport is None:
        return host, port, "not_testable", None, "not_testable", None, "profile does not use WebSocket transport"
    if not host or port is None:
        return host, port, "invalid", None, "not_testable", None, "profile has no valid remote endpoint"
    sock = _socks_connect(local_port, host, port, timeout)
    try:
        if transport["secure"]:
            context = ssl._create_unverified_context() if transport["allow_insecure"] else ssl.create_default_context()
            sock = context.wrap_socket(sock, server_hostname=transport["server_name"])
        handshake_ok, handshake_ms, handshake_status = _websocket_handshake(
            sock, transport["host"], transport["path"], transport["headers"], timeout
        )
        if not handshake_ok:
            return host, port, handshake_status, handshake_ms, "not_tested", None, handshake_status
        payload_ok, payload_ms, payload_status = _websocket_ping(sock, timeout=timeout)
        return host, port, "ok", handshake_ms, payload_status, payload_ms, None if payload_ok else payload_status
    finally:
        sock.close()


def test_websocket_profile(
    profile: Profile,
    settings,
    engines: dict | None = None,
    bin_dir=None,
) -> WebSocketResult:
    host, port = profile_endpoint(profile)
    result = WebSocketResult(profile_id=profile.id, name=profile.name, kind=profile.kind, host=host, port=port)
    if profile.kind in VPN_KINDS or websocket_transport(profile) is None:
        result.error = "profile does not use WebSocket transport"
        result.not_testable = True
        return result
    engines = engines or {}
    engine = resolve_engine(profile.kind, "", profile.engine, settings.default_engine)
    result.engine = engine
    proc: Proc | None = None
    path: str | None = None
    try:
        local_port = _free_port()
        engine, config_dict = build_test_config(profile, settings, local_port)
        adapter = get_adapter(engine)
        path = _write_temp_config(engine, config_dict)
        binary = locate_binary(engine, engines.get(engine, {}), bin_dir=bin_dir)
        proc = Proc()
        proc.start([str(binary), *adapter.run_args(path)])
        if not _wait_port(local_port):
            result.error = "engine did not start"
            result.handshake_status = "engine_failed"
            return result
        host, port, handshake_status, handshake_ms, payload_status, payload_ms, error = _websocket_probe(profile, local_port)
        result.host, result.port = host, port
        result.handshake_status, result.handshake_ms = handshake_status, handshake_ms
        result.payload_status = payload_status
        result.payload_ms = payload_ms
        result.error = error
        return result
    except BinaryError as exc:
        result.error = str(exc)
        result.handshake_status = "binary_failed"
        return result
    except Exception as exc:  # pragma: no cover - defensive
        result.error = str(exc)
        result.handshake_status = "error"
        return result
    finally:
        if proc is not None:
            proc.stop()
        if path is not None:
            try:
                os.unlink(path)
            except OSError:
                pass


def websocket_test_many(
    profiles,
    settings,
    engines: dict | None = None,
    concurrency: int = 4,
    bin_dir=None,
) -> list[WebSocketResult]:
    import sys
    total = len(profiles)
    results: dict[str, WebSocketResult] = {}
    workers = max(1, min(int(concurrency), 16))
    if sys.stderr.isatty():
        print(f"\rtesting {total} websockets…", end="", file=sys.stderr, flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(test_websocket_profile, profile, settings, engines, bin_dir): profile.id
            for profile in profiles
        }
        for future in as_completed(futures):
            result = future.result()
            results[result.profile_id] = result
            if sys.stderr.isatty():
                done = len(results)
                print(f"\rtesting {done}/{total} websockets…", end="", file=sys.stderr, flush=True)
    if sys.stderr.isatty():
        print("\rdone.              ", file=sys.stderr)
    return [results[profile.id] for profile in profiles]


def render_websocket_table(results: list[WebSocketResult]) -> None:
    from rich.console import Console
    from rich.table import Table

    table = Table(title="WebSocket tests")
    for column in ("ID", "Name", "Endpoint", "Handshake", "Payload", "Status"):
        table.add_column(column)
    for result in results:
        handshake = f"{result.handshake_ms:.0f} ms" if result.handshake_ms is not None else result.handshake_status
        payload = f"{result.payload_ms:.0f} ms" if result.payload_ms is not None else result.payload_status
        ok = result.handshake_status == "ok" and result.payload_status == "ok"
        status = "skip" if result.not_testable else ("OK" if ok else (result.error or "FAIL"))
        table.add_row(result.profile_id, result.name, f"{result.host}:{result.port or '-'}", handshake, payload, status,
                      style="green" if ok else ("dim" if result.not_testable else "red"))
    Console().print(table)


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _wait_port(port: int, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _http_latency(url: str, port: int, timeout: float = 10.0) -> tuple[bool, float, str]:
    import httpx

    proxy = f"socks5://127.0.0.1:{port}"
    start = time.monotonic()
    try:
        with httpx.Client(proxy=proxy, timeout=timeout, follow_redirects=True) as client:
            response = client.get(url)
            elapsed = (time.monotonic() - start) * 1000.0
            ok = response.status_code < 400
            return ok, elapsed, "" if ok else f"http {response.status_code}"
    except Exception as exc:
        return False, (time.monotonic() - start) * 1000.0, str(exc)


def _url_authority(url: str) -> tuple[str, int]:
    """Return (host, port) for a URL, defaulting to the scheme's port."""
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return host, port


def _connect_ms(port: int, host: str, dst_port: int, timeout: float = 10.0) -> float | None:
    """Time the SOCKS5 CONNECT phase (TCP through the proxy) to ``host:dst_port``."""
    if not host:
        return None
    start = time.monotonic()
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        sock.settimeout(timeout)
        sock.sendall(b"\x05\x01\x00")
        if sock.recv(2) != b"\x05\x00":
            return None
        host_bytes = host.encode()
        sock.sendall(b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes + dst_port.to_bytes(2, "big"))
        reply = sock.recv(4)
        if reply[:2] != b"\x05\x00":
            return None
        atyp = reply[3]
        if atyp == 1:
            sock.recv(6)
        elif atyp == 3:
            n = sock.recv(1)[0]
            sock.recv(n + 2)
        elif atyp == 4:
            sock.recv(18)
        sock.close()
        return (time.monotonic() - start) * 1000.0
    except OSError:
        return None


def build_test_config(profile: Profile, settings, port: int) -> tuple[str, dict]:
    """Build the minimal engine config used to probe one profile."""
    engine = resolve_engine(profile.kind, "", profile.engine, settings.default_engine)
    adapter = get_adapter(engine)
    test_settings = replace(settings, listen="127.0.0.1", mixed_port=port, log_level="error")
    target = Target(
        type="single",
        name=profile.name,
        engine=engine,
        profile_ids=[profile.id],
        profiles=[profile],
    )
    config_dict = adapter.generate(test_settings, RoutingConfig(mode="all"), target)
    # Strip custom DNS to avoid circular dependency: the DNS servers would be
    # resolved through the proxy outbound which itself needs DNS to resolve the
    # server hostname.  System DNS is sufficient for the short-lived probe.
    config_dict.pop("dns", None)
    if "route" in config_dict:
        config_dict["route"].pop("default_domain_resolver", None)
    return engine, config_dict


def _write_temp_config(engine: str, config_dict: dict) -> str:
    fd, path = tempfile.mkstemp(prefix=f"v2raycli-{engine}-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(config_dict, fh, ensure_ascii=False, indent=2)
    return path


def test_profile(
    profile: Profile,
    settings,
    engines: dict | None = None,
    bin_dir=None,
) -> TestResult:
    if profile.kind in VPN_KINDS:
        return TestResult(
            profile_id=profile.id, name=profile.name, kind=profile.kind, not_testable=True
        )
    engines = engines or {}
    engine = resolve_engine(profile.kind, "", profile.engine, settings.default_engine)
    proc: Proc | None = None
    path: str | None = None
    try:
        port = _free_port()
        engine, config_dict = build_test_config(profile, settings, port)
        adapter = get_adapter(engine)
        path = _write_temp_config(engine, config_dict)
        binary = locate_binary(engine, engines.get(engine, {}), bin_dir=bin_dir)
        proc = Proc()
        proc.start([str(binary), *adapter.run_args(path)])
        if not _wait_port(port):
            return TestResult(
                profile_id=profile.id, name=profile.name, kind=profile.kind,
                engine=engine, ok=False, error="engine did not start",
            )
        ok, latency, error = _http_latency(settings.test_url, port)
        host, dst_port = _url_authority(settings.test_url)
        connect_ms = _connect_ms(port, host, dst_port) if ok else None
        return TestResult(
            profile_id=profile.id, name=profile.name, kind=profile.kind,
            engine=engine, ok=ok, latency_ms=latency, error=error, connect_ms=connect_ms,
        )
    except BinaryError as exc:
        return TestResult(
            profile_id=profile.id, name=profile.name, kind=profile.kind,
            engine=engine, ok=False, error=str(exc),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return TestResult(
            profile_id=profile.id, name=profile.name, kind=profile.kind,
            engine=engine, ok=False, error=str(exc),
        )
    finally:
        if proc is not None:
            proc.stop()
        if path is not None:
            try:
                os.unlink(path)
            except OSError:
                pass


def test_many(
    profiles,
    settings,
    engines: dict | None = None,
    concurrency: int = 8,
    bin_dir=None,
) -> list[TestResult]:
    import sys
    total = len(profiles)
    results: dict[str, TestResult] = {}
    workers = max(1, min(int(concurrency), 32))
    if sys.stderr.isatty():
        print(f"\rtesting {total} profiles…", end="", file=sys.stderr, flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(test_profile, p, settings, engines, bin_dir): p.id
            for p in profiles
        }
        for future in as_completed(futures):
            result = future.result()
            results[result.profile_id] = result
            if sys.stderr.isatty():
                done = len(results)
                print(f"\rtesting {done}/{total}…", end="", file=sys.stderr, flush=True)
    if sys.stderr.isatty():
        print("\rdone.              ", file=sys.stderr)
    return [results[p.id] for p in profiles]


def select_profiles(store, scope) -> list[Profile]:
    """Resolve a scope to a list of profiles.

    ``scope`` is ``"all"``, ``("subscription", sub_id)``,
    ``("profiles", [ids])``, or ``"routing_targets"``.
    """
    if scope == "all":
        return store.list_profiles()
    if isinstance(scope, tuple) and scope and scope[0] == "subscription":
        return [p for p in store.list_profiles() if p.subscription_id == scope[1]]
    if isinstance(scope, tuple) and scope and scope[0] == "group":
        group = store.get_group(scope[1])
        if group is None:
            return []
        ids = set(group.profile_ids)
        return [p for p in store.list_profiles() if p.id in ids]
    if isinstance(scope, tuple) and scope and scope[0] == "profiles":
        ids = set(scope[1])
        return [p for p in store.list_profiles() if p.id in ids]
    if scope == "routing_targets":
        return collect_routing_target_profiles(store)
    return []


def collect_routing_target_profiles(store) -> list[Profile]:
    """Collect profiles referenced by split-routing rules.

    Returns profiles that are targets of proxy routing rules, including
    members of any referenced groups.  Deduplicates and preserves order.
    """
    routing = store.config.routing
    if routing.mode != "split" or not routing.rules:
        return []

    seen_ids: set[str] = set()
    result: list[Profile] = []

    def _add(profile_id: str) -> None:
        if profile_id in seen_ids:
            return
        seen_ids.add(profile_id)
        profile = store.get_profile(profile_id)
        if profile is not None:
            result.append(profile)

    for rule in routing.rules:
        if not rule.enabled or rule.action != "proxy" or not rule.target_id:
            continue
        # Check if it's a profile directly.
        profile = store.get_profile(rule.target_id)
        if profile is not None:
            _add(rule.target_id)
            continue
        # Check if it's a group — add its member profiles.
        group = store.get_group(rule.target_id)
        if group is not None:
            for pid in group.profile_ids:
                _add(pid)

    return result


def render_table(results: list[TestResult]) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="Outbound latency")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Kind")
    table.add_column("Engine")
    table.add_column("Connect")
    table.add_column("Latency")
    table.add_column("Status")

    def sort_key(r: TestResult):
        return (not r.ok, r.latency_ms if r.latency_ms is not None else float("inf"))

    for result in sorted(results, key=sort_key):
        connect = f"{result.connect_ms:.0f} ms" if result.connect_ms is not None else "-"
        latency = f"{result.latency_ms:.0f} ms" if result.latency_ms is not None else "-"
        if result.not_testable:
            status, style = "skip", "dim"
        elif result.ok:
            status, style = "OK", "green"
        else:
            status, style = "FAIL", "red"
        table.add_row(result.profile_id, result.name, result.kind, result.engine, connect, latency, status, style=style)
    console.print(table)


def save_results(results: list[TestResult], path=None) -> None:
    target = path or (config.RUNTIME_DIR / "test_results.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_results(path=None) -> list[TestResult]:
    """Load the cached result table, returning an empty list if unavailable."""
    target = path or (config.RUNTIME_DIR / "test_results.json")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    try:
        return [TestResult(**item) for item in payload if isinstance(item, dict)]
    except (TypeError, ValueError):
        return []
