"""Server management: start, stop, and track multiple inbound proxy servers.

Each server is a separate engine process that listens on a dedicated port
and forwards traffic to a specific profile or group.
"""

from __future__ import annotations

import json
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Server, Settings
    from .storage import ConfigStore


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
        try:
            os.kill(self.pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


class ServerManager:
    """Manage multiple inbound proxy server processes."""

    def __init__(self, store: "ConfigStore", runtime_dir: Path | None = None):
        self.store = store
        self.runtime_dir = runtime_dir or store.path.parent / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._states: dict[str, ServerState] = {}
        self._load_states()

    def _states_file(self) -> Path:
        return self.runtime_dir / "server-states.json"

    def _load_states(self) -> None:
        path = self._states_file()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for server_id, state_data in data.items():
                self._states[server_id] = ServerState(**state_data)
        except (json.JSONDecodeError, TypeError):
            pass

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

    def _generate_server_config(self, server: "Server") -> dict:
        """Generate engine config for a single server."""
        from .engines import get_adapter, resolve_engine
        from .models import Profile, Group
        from .outbounds.groups import enrich_target_with_routing, resolve_target

        # Resolve the outbound
        if server.outbound_type == "profile":
            profile = self.store.get_profile(server.outbound_id)
            if profile is None:
                raise ValueError(f"unknown profile id: {server.outbound_id}")
            target = resolve_target(self.store, profile, self.store.config.settings.default_engine)
        elif server.outbound_type == "group":
            group = self.store.get_group(server.outbound_id)
            if group is None:
                raise ValueError(f"unknown group id: {server.outbound_id}")
            target = resolve_target(self.store, group, self.store.config.settings.default_engine)
        else:
            raise ValueError(f"unknown outbound type: {server.outbound_type}")

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
        return adapter.generate(settings, self.store.config.routing, target)

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
        config = self._generate_server_config(server)

        # Write runtime config
        config_dir = self.runtime_dir / f"server-{server_id}"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.json"
        config_path.write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8"
        )

        # Resolve engine binary
        from .engines.binary import locate_binary

        target_engine = config.get("_target_engine", "sing-box")
        # Try to detect engine from config
        if "dns" in config and "route" in config:
            target_engine = "sing-box"
        elif "routing" in config and "balancers" in config.get("routing", {}):
            target_engine = "xray"

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
            proc = self._spawn(argv, config_dir)
        except OSError as exc:
            state = ServerState(server_id=server_id, error=str(exc))
            self._states[server_id] = state
            self._save_states()
            return state

        state = ServerState(
            server_id=server_id,
            pid=proc.pid,
            config_path=str(config_path),
            started_at=datetime.now(timezone.utc).isoformat(),
        )
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

    def _spawn(self, argv: list[str], cwd: Path):
        """Spawn an engine process."""
        import subprocess
        kwargs = {
            "argv": argv,
            "cwd": str(cwd),
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "start_new_session": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        return subprocess.Popen(**kwargs)
