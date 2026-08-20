"""Engine-aware outbound latency / reachability testing.

Each profile is tested by launching a short-lived engine with a local SOCKS
inbound routed through that profile, then timing an HTTP request through it.
"""

from __future__ import annotations

import errno
import json
import math
import os
import socket
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
class TestResult:
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
    results: dict[str, EndpointResult] = {}
    workers = max(1, min(int(concurrency), 32))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(probe_endpoint, profile, timeout): profile.id for profile in profiles}
        for future in as_completed(futures):
            result = future.result()
            results[result.profile_id] = result
    return [results[profile.id] for profile in profiles]


def render_endpoint_table(results: list[EndpointResult]) -> None:
    from rich.console import Console
    from rich.table import Table

    table = Table(title="Endpoint probes")
    for column in ("Name", "Endpoint", "ICMP", "TCP", "Status"):
        table.add_column(column)
    for result in results:
        icmp = f"{result.icmp_ms:.0f} ms" if result.icmp_ms is not None else result.icmp_status
        tcp = f"{result.tcp_ms:.0f} ms" if result.tcp_ms is not None else result.tcp_status
        status = "OK" if result.tcp_status == "ok" else (result.error or result.tcp_status)
        style = "green" if result.tcp_status == "ok" else "red"
        table.add_row(result.name, f"{result.host}:{result.port or '-'}", icmp, tcp, status, style=style)
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
    results: dict[str, TestResult] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(test_profile, p, settings, engines, bin_dir): p.id
            for p in profiles
        }
        for future in as_completed(futures):
            result = future.result()
            results[result.profile_id] = result
    return [results[p.id] for p in profiles]


def select_profiles(store, scope) -> list[Profile]:
    """Resolve a scope to a list of profiles.

    ``scope`` is ``"all"``, ``("subscription", sub_id)``, or
    ``("profiles", [ids])``.
    """
    if scope == "all":
        return store.list_profiles()
    if isinstance(scope, tuple) and scope and scope[0] == "subscription":
        return [p for p in store.list_profiles() if p.subscription_id == scope[1]]
    if isinstance(scope, tuple) and scope and scope[0] == "profiles":
        ids = set(scope[1])
        return [p for p in store.list_profiles() if p.id in ids]
    return []


def render_table(results: list[TestResult]) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="Outbound latency")
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
        table.add_row(result.name, result.kind, result.engine, connect, latency, status, style=style)
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
