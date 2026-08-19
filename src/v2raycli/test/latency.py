"""Engine-aware outbound latency / reachability testing.

Each profile is tested by launching a short-lived engine with a local SOCKS
inbound routed through that profile, then timing an HTTP request through it.
"""

from __future__ import annotations

import json
import os
import socket
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
class TestResult:
    profile_id: str = ""
    name: str = ""
    kind: str = ""
    engine: str = ""
    ok: bool = False
    latency_ms: float | None = None
    error: str | None = None
    not_testable: bool = False


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
        with httpx.Client(
            proxies={"http://": proxy, "https://": proxy},
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            response = client.get(url)
            elapsed = (time.monotonic() - start) * 1000.0
            ok = response.status_code < 400
            return ok, elapsed, "" if ok else f"http {response.status_code}"
    except Exception as exc:
        return False, (time.monotonic() - start) * 1000.0, str(exc)


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
    runtime_dir=None,
) -> TestResult:
    if profile.kind in VPN_KINDS:
        return TestResult(
            profile_id=profile.id, name=profile.name, kind=profile.kind, not_testable=True
        )
    engines = engines or {}
    engine = resolve_engine(profile.kind, "", profile.engine, settings.default_engine)
    try:
        port = _free_port()
        engine, config_dict = build_test_config(profile, settings, port)
        adapter = get_adapter(engine)
        path = _write_temp_config(engine, config_dict)
        binary = locate_binary(engine, engines.get(engine, {}), bin_dir=bin_dir)
        proc = Proc()
        proc.start([str(binary), *adapter.run_args(path)])
        try:
            if not _wait_port(port):
                return TestResult(
                    profile_id=profile.id, name=profile.name, kind=profile.kind,
                    engine=engine, ok=False, error="engine did not start",
                )
            ok, latency, error = _http_latency(settings.test_url, port)
            return TestResult(
                profile_id=profile.id, name=profile.name, kind=profile.kind,
                engine=engine, ok=ok, latency_ms=latency, error=error,
            )
        finally:
            proc.stop()
            try:
                os.unlink(path)
            except OSError:
                pass
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


def test_many(
    profiles,
    settings,
    engines: dict | None = None,
    concurrency: int = 8,
    bin_dir=None,
    runtime_dir=None,
) -> list[TestResult]:
    results: dict[str, TestResult] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(test_profile, p, settings, engines, bin_dir, runtime_dir): p.id
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
    table.add_column("Latency")
    table.add_column("Status")

    def sort_key(r: TestResult):
        return (not r.ok, r.latency_ms if r.latency_ms is not None else float("inf"))

    for result in sorted(results, key=sort_key):
        latency = f"{result.latency_ms:.0f} ms" if result.latency_ms is not None else "-"
        if result.not_testable:
            status, style = "skip", "dim"
        elif result.ok:
            status, style = "OK", "green"
        else:
            status, style = "FAIL", "red"
        table.add_row(result.name, result.kind, result.engine, latency, status, style=style)
    console.print(table)


def save_results(results: list[TestResult], path=None) -> None:
    target = path or (config.RUNTIME_DIR / "test_results.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
