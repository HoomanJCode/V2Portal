"""Engine adapter base class, registry, and runtime config helpers."""

from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from .. import config as cfg

if TYPE_CHECKING:
    from ..models import RoutingConfig, Settings
    from ..outbounds.groups import Target


class EngineAdapter(ABC):
    """Interface for generating and driving one proxy engine."""

    name: str = ""
    supported_kinds: frozenset[str] = frozenset()
    supported_strategies: frozenset[str] = frozenset()

    @abstractmethod
    def generate(self, settings: "Settings", routing: "RoutingConfig", target: "Target") -> dict:
        """Build a full engine config for the given resolved target."""

    @abstractmethod
    def run_args(self, config_path: str) -> list[str]:
        """Arguments after the binary to run the config."""

    @abstractmethod
    def validate_args(self, config_path: str) -> list[str]:
        """Arguments after the binary to validate the config."""

    @abstractmethod
    def binary_filename(self, platform: str, arch: str) -> str:
        """Bare binary name for a platform/arch (e.g. 'xray', 'xray.exe')."""


_ADAPTERS: dict[str, EngineAdapter] = {}


def register(cls):
    """Class decorator that registers an EngineAdapter instance by name."""
    adapter = cls()
    _ADAPTERS[adapter.name] = adapter
    return cls


def get_adapter(name: str) -> EngineAdapter:
    try:
        return _ADAPTERS[name]
    except KeyError:
        raise ValueError(f"unknown engine: {name}") from None


def write_runtime_config(engine: str, config_dict: dict, runtime_dir: Path | None = None) -> Path:
    """Write the generated config to ``<runtime_dir>/<engine>.json``."""
    directory = runtime_dir or cfg.RUNTIME_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{engine}.json"
    path.write_text(json.dumps(config_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def validate_config(
    engine: str, path: Path, binary: Path | str | None = None, env: dict | None = None
) -> None:
    """Validate a generated config with the engine's own check command."""
    adapter = get_adapter(engine)
    cmd = adapter.validate_args(str(path))
    if binary:
        cmd = [str(binary), *cmd]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "validation failed").strip()
        raise RuntimeError(message)
