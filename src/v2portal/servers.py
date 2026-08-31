"""Server management: start, stop, and track multiple inbound proxy servers.

Each server is a separate engine process that listens on a dedicated port
and forwards traffic to a specific profile or group.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Server, Settings
    from .storage import ConfigStore

_log = logging.getLogger(__name__)

DEFAULT_FAILOVER_TIMEOUT = 10  # seconds between engine health probes

# Patterns in engine stderr that indicate the proxy is non-functional.
_ENGINE_ERROR_PATTERNS = (
    "failed to handshake",
    "connection refused",
    "connection reset",
    " dial ",
    " handshake ",
    " i/o timeout",
    " too many connections",
    " no such host",
    " lookup ",
    " permission denied",
    " access denied",
    " address already in use",
    " bind: address already in use",
    " port is already allocated",
    "\nerror",
)

_FIREWALL_HINT_WINDOWS = (
    "On Windows, the engine binary may need a firewall rule to make outbound connections.\n"
    "Try: Windows Security → Firewall → Allow an app → browse to sing-box.exe or xray.exe\n"
    "Or run PowerShell as Admin: New-NetFirewallRule -DisplayName 'v2portal engine' "
    "-Direction Outbound -Program '<path-to-engine>' -Action Allow"
)


def _check_stderr_for_errors(stderr_lines: list[str], engine: str = "") -> str | None:
    """Scan captured engine stderr for known failure patterns.

    Returns a human-readable warning string, or ``None`` when no error
    pattern is found.
    """
    if not stderr_lines:
        return None
    lower_lines = [line.lower() for line in stderr_lines]
    for line in lower_lines:
        for pattern in _ENGINE_ERROR_PATTERNS:
            if pattern in line:
                # Collect the most relevant error lines (last 3).
                detail = " | ".join(stderr_lines[-3:])
                hint = ""
                if os.name == "nt":
                    hint = f"\n\n{_FIREWALL_HINT_WINDOWS}"
                return f"engine reports errors: {detail}{hint}"
    return None


@dataclass
class ServerState:
    """Runtime state for a running server process."""

    server_id: str
    pid: int | None = None
    config_path: str | None = None
    started_at: str | None = None
    error: str | None = None

    def is_running(self) -> bool:
        if self.pid is None:
            return False
        if os.name == "nt":
            return self._is_running_win32(self.pid)
        try:
            os.kill(self.pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    @staticmethod
    def _is_running_win32(pid: int) -> bool:
        """Check process existence on Windows via OpenProcess."""
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid,
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False


class ServerManager:
    """Manage multiple inbound proxy server processes."""

    def __init__(self, store: "ConfigStore", runtime_dir: Path | None = None):
        self.store = store
        self.runtime_dir = runtime_dir or store.path.parent / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._states: dict[str, ServerState] = {}
        self.selected_pinned = None  # most recent start's real-endpoint pin
        self.failover_active = None  # (healthy_count, timeout_s) when failover on
        self._load_states()

    def _states_file(self) -> Path:
        return self.runtime_dir / "server-states.json"

    def _load_states(self) -> None:
        path = self._states_file()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            known_ids = {s.id for s in self.store.config.servers}
            for server_id, state_data in data.items():
                if server_id not in known_ids:
                    continue  # server was removed; skip stale state
                self._states[server_id] = ServerState(**state_data)
        except (json.JSONDecodeError, TypeError) as exc:
            _log.warning("failed to load server states from %s: %s", path, exc)

    def _save_states(self) -> None:
        data = {}
        for server_id, state in self._states.items():
            data[server_id] = {
                "server_id": state.server_id,
                "pid": state.pid,
                "config_path": state.config_path,
                "started_at": state.started_at,
                "error": state.error,
            }
        self._states_file().write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8"
        )

    def get_state(self, server_id: str) -> ServerState | None:
        state = self._states.get(server_id)
        if state and not state.is_running():
            state.pid = None
            self._save_states()
        return state

    def list_running(self) -> list[str]:
        """Return IDs of servers that are currently running."""
        running = []
        for server_id in list(self._states):
            state = self._states[server_id]
            if state.is_running():
                running.append(server_id)
            else:
                state.pid = None
        self._save_states()
        return running

    def resolve_outbound_target(self, server: "Server"):
        """Resolve a server's outbound reference into a Target.

        Accepts profile | subscription | group | server | direct via the
        universal resolver; a subscription resolves dynamically as a
        strategy-based balancer over its current profiles; a server resolves
        to a socks/http hop through that server (loop-checked).
        """
        from .outbounds.groups import resolve_outbound

        return resolve_outbound(
            self.store,
            server.outbound_type,
            server.outbound_id,
            default_engine=self.store.config.settings.default_engine,
            from_server_id=server.id,
        )

    def _probe_healthy(self, target, timeout: float = 3.0, workers: int = 16):
        """Probe each balancer member's real TCP endpoint concurrently.

        Returns the healthy profiles ordered by lowest connect delay, or raises
        when no endpoint is reachable. The engine's urltest/leastPing strategy
        measures HTTP latency *through* the proxy, which can report low latency
        even when the underlying endpoint is dead; a raw TCP connect is the
        ground truth here.
        """
        from concurrent.futures import ThreadPoolExecutor

        from .test.latency import probe_endpoint

        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(
                    pool.map(
                        lambda p: probe_endpoint(p, timeout=timeout),
                        list(target.profiles),
                    )
                )
        except Exception as exc:  # noqa: BLE001 - probing is best-effort
            raise ValueError(f"endpoint probe failed: {exc}") from exc
        healthy = sorted(
            (r for r in results if r.tcp_status == "ok"),
            key=lambda r: (r.tcp_ms if r.tcp_ms is not None else float("inf"), r.name),
        )
        if not healthy:
            raise ValueError(
                "no reachable endpoint among balancer members "
                "(all endpoints refused, timed out, or failed lookup)"
            )
        profiles = [self.store.get_profile(r.profile_id) for r in healthy]
        if any(p is None for p in profiles):
            raise ValueError("a probed node is no longer in the config")
        return profiles  # type: ignore[return-value]

    def _pin_to_fastest_endpoint(self, healthy: list, default_engine: str):
        """Reduce a healthy, delay-ordered member list to the single best node."""
        from .outbounds.groups import resolve_outbound

        return resolve_outbound(
            self.store, "profile", healthy[0].id,
            default_engine=default_engine,
        )

    def _failover_target(self, target, healthy: list, timeout: int):
        """Turn a balancer target into a health-checked balancer over the
        healthy nodes, keeping the fastest endpoint first (the engine's
        initial default) and probing every ``timeout`` seconds to fail over
        quickly when the active node stops responding.
        """
        from dataclasses import replace

        if len(healthy) <= 1:
            # Nothing to balance — degrade to a single node.
            return self._pin_to_fastest_endpoint(healthy, target.engine)
        return replace(
            target,
            profiles=list(healthy),
            profile_ids=[p.id for p in healthy],
            health_interval=int(timeout),
        )

    def _generate_server_config(self, server: "Server") -> dict:
        """Generate engine config for a single server."""
        from .engines import get_adapter
        from .outbounds.groups import enrich_target_with_routing

        target = self.resolve_outbound_target(server)
        self.selected_pinned = None
        self.failover_active = None
        if target.type == "balancer":
            # Real endpoint delay is always the selection ground truth: probe
            # members, drop dead endpoints. Then either pin to the single
            # lowest-delay node (no failover) or keep a health-checked balancer
            # over the healthy nodes (failover enabled).
            healthy = self._probe_healthy(target)
            if getattr(server, "failover", False):
                timeout = getattr(server, "failover_timeout", 0) or self.DEFAULT_FAILOVER_TIMEOUT
                if timeout <= 0:
                    raise ValueError("failover timeout must be a positive number of seconds")
                target = self._failover_target(target, healthy, timeout)
                # If there is only one healthy node the failover target degrades
                # to a single pin — record it for the status line.
                if len(healthy) == 1:
                    self.selected_pinned = healthy[0]
                else:
                    self.failover_active = (len(healthy), timeout)
            else:
                target = self._pin_to_fastest_endpoint(
                    healthy, self.store.config.settings.default_engine
                )
                self.selected_pinned = healthy[0]
        target = enrich_target_with_routing(target, self.store.config.routing, self.store)

        # Build settings for this server
        from .models import Settings
        settings = Settings(
            listen=server.listen,
            mixed_port=server.port,
            socks_port=0,
            http_port=0,
            allow_lan=server.listen != "127.0.0.1",
            inbound_auth=server.auth or {"enabled": False, "username": "", "password": ""},
            dns=list(self.store.config.settings.dns),
            log_level=self.store.config.settings.log_level,
            test_url=self.store.config.settings.test_url,
            default_engine=self.store.config.settings.default_engine,
            traffic_api=bool(server.traffic_api_port),
            traffic_api_port=server.traffic_api_port,
        )

        # Override inbound type based on server protocol
        if server.protocol == "socks":
            settings.socks_port = server.port
            settings.mixed_port = 0
        elif server.protocol == "http":
            settings.http_port = server.port
            settings.mixed_port = 0
        else:
            # mixed: keep mixed_port
            pass

        adapter = get_adapter(target.engine)
        return adapter.generate(settings, self.store.config.routing, target), target.engine

    def start(self, server_id: str) -> ServerState:
        """Start a server by its ID."""
        from datetime import datetime, timezone

        server = self.store.get_server(server_id)
        if server is None:
            raise ValueError(f"unknown server id: {server_id}")

        state = self.get_state(server_id)
        if state and state.is_running():
            return state

        # Generate config
        config, target_engine = self._generate_server_config(server)

        # Write runtime config
        config_dir = self.runtime_dir / f"server-{server_id}"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.json"
        config_path.write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8"
        )

        # Resolve engine binary
        from .engines.binary import locate_binary

        binary = locate_binary(
            target_engine,
            self.store.config.engines.get(target_engine, {}),
        )

        # Build run args
        from .engines import get_adapter

        adapter = get_adapter(target_engine)
        argv = adapter.run_args(str(config_path))
        argv.insert(0, str(binary))

        # Start process
        try:
            proc = self._spawn(argv, config_dir, capture_stderr=True)
        except OSError as exc:
            state = ServerState(server_id=server_id, error=str(exc))
            self._states[server_id] = state
            self._save_states()
            return state

        # Brief pause to catch engines that crash immediately (bad config,
        # missing binary, port conflict, etc.).
        for _ in range(10):
            if proc.poll() is not None:
                break
            time.sleep(0.1)

        if proc.poll() is not None:
            stderr_lines = getattr(proc, "_captured_stderr", [])
            detail = " ".join(stderr_lines[-3:]) if stderr_lines else f"exit code {proc.returncode}"
            state = ServerState(
                server_id=server_id,
                error=f"engine exited immediately: {detail}",
            )
        else:
            # Engine is running — give it a moment to attempt the outbound
            # connection, then scan stderr for handshake / dial failures.
            time.sleep(1.0)
            stderr_lines = getattr(proc, "_captured_stderr", [])
            warning = _check_stderr_for_errors(stderr_lines, target_engine)
            state = ServerState(
                server_id=server_id,
                pid=proc.pid,
                config_path=str(config_path),
                started_at=datetime.now(timezone.utc).isoformat(),
            )
            if warning:
                state.error = warning
        self._states[server_id] = state
        self._save_states()
        return state

    def stop(self, server_id: str) -> bool:
        """Stop a running server by its ID."""
        state = self._states.get(server_id)
        if state is None or not state.is_running():
            return False
        try:
            os.kill(state.pid, signal.SIGTERM)
            # Wait briefly for graceful shutdown
            for _ in range(20):
                if not state.is_running():
                    break
                time.sleep(0.1)
            # Force kill if still running
            if state.is_running():
                os.kill(state.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        state.pid = None
        self._save_states()
        return True

    def stop_all(self) -> int:
        """Stop all running servers. Return count stopped."""
        count = 0
        for server_id in list(self._states):
            if self.stop(server_id):
                count += 1
        return count

    def _spawn(self, argv: list[str], cwd: Path, capture_stderr: bool = False):
        """Spawn an engine process.

        When *capture_stderr* is True the child's stderr is captured so
        callers can surface crash messages.  The pipe is drained in a
        daemon thread to prevent the OS buffer from filling up.
        """
        import subprocess
        import threading

        kwargs = {
            "args": argv,
            "cwd": str(cwd),
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.PIPE if capture_stderr else subprocess.DEVNULL,
        }
        if os.name == "nt":
            # CREATE_NO_WINDOW prevents a console flash; the process is
            # detached from the CLI so Ctrl+C doesn't kill it.
            kwargs["creationflags"] = (
                subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            )
        else:
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(**kwargs)
        if capture_stderr and proc.stderr is not None:
            lines: list[str] = []
            def _drain():
                for raw in iter(proc.stderr.readline, b""):
                    text = raw.decode("utf-8", errors="replace").rstrip("\n")
                    if text:
                        lines.append(text)
            threading.Thread(target=_drain, daemon=True).start()
            proc._captured_stderr = lines  # type: ignore[attr-defined]
        return proc
