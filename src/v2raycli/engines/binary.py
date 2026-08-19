"""Engine binary location, download, and version detection."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import httpx

from .. import config
from .base import get_adapter


class BinaryError(Exception):
    pass


def platform_name() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def arch_name() -> str:
    import platform

    machine = platform.machine().lower()
    return {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
        "armv7l": "armv7",
        "armv8l": "arm64",
    }.get(machine, machine)


def release_asset(engine: str, version: str, platform: str, arch: str) -> tuple[str, str]:
    """Return (asset filename, archive kind) for a GitHub release asset.

    Best-effort naming; verify against the release listing for pinned versions.
    """
    if engine == "xray":
        plat = {"windows": "windows", "linux": "linux", "darwin": "macos"}.get(platform, platform)
        a = {"amd64": "64", "arm64": "arm64-v8a", "armv7": "armv7a"}.get(arch, arch)
        return f"Xray-{plat}-{a}.zip", "zip"
    return f"sing-box-{version}-{platform}-{arch}.tar.gz", "tar.gz"


def _extract(archive: Path, dest: Path, kind: str, binary_name: str) -> None:
    def matches(name: str) -> bool:
        return name == binary_name or name.endswith("/" + binary_name)

    if kind == "zip":
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                if matches(member):
                    with zf.open(member) as src, open(dest / binary_name, "wb") as dst:
                        dst.write(src.read())
                    return
    else:
        with tarfile.open(archive, "r:gz") as tf:
            for member in tf.getmembers():
                if matches(member.name):
                    fh = tf.extractfile(member)
                    if fh:
                        with open(dest / binary_name, "wb") as dst:
                            dst.write(fh.read())
                        return
    raise BinaryError(f"binary {binary_name} not found in {archive}")


def download_binary(
    engine: str, version: str, platform: str, arch: str, bin_dir: Path | None = None
) -> Path:
    adapter = get_adapter(engine)
    bin_dir = bin_dir or config.BIN_DIR
    bin_dir.mkdir(parents=True, exist_ok=True)

    asset, kind = release_asset(engine, version, platform, arch)
    repo = "XTLS/Xray-core" if engine == "xray" else "SagerNet/sing-box"
    url = f"https://github.com/{repo}/releases/download/{version}/{asset}"
    archive_path = bin_dir / asset

    try:
        with httpx.Client(follow_redirects=True, timeout=60.0) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(archive_path, "wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
    except httpx.HTTPError as exc:
        raise BinaryError(f"download failed: {exc}") from exc

    binary_name = adapter.binary_filename(platform, arch)
    _extract(archive_path, bin_dir, kind, binary_name)
    archive_path.unlink(missing_ok=True)

    binary = bin_dir / binary_name
    binary.chmod(0o755)
    return binary


def locate_binary(
    engine: str,
    options: dict,
    bin_dir: Path | None = None,
    platform: str | None = None,
    arch: str | None = None,
) -> Path:
    """Resolve the engine binary path from options (auto | system | /path)."""
    adapter = get_adapter(engine)
    platform = platform or platform_name()
    arch = arch or arch_name()
    binary_name = adapter.binary_filename(platform, arch)

    path = options.get("binary_path", "auto")
    if path and path not in ("auto", "system"):
        candidate = Path(path)
        if not candidate.exists():
            raise BinaryError(f"binary not found: {candidate}")
        return candidate
    if path == "system":
        found = shutil.which(binary_name)
        if not found:
            raise BinaryError(f"{binary_name} not found on PATH")
        return Path(found)

    bin_dir = bin_dir or config.BIN_DIR
    cached = bin_dir / binary_name
    if cached.exists():
        return cached
    return download_binary(engine, options.get("version", "latest"), platform, arch, bin_dir)


def get_version(engine: str, path: Path) -> str:
    """Run ``<binary> version`` and extract the version string."""
    try:
        result = subprocess.run([str(path), "version"], capture_output=True, text=True, timeout=15)
    except FileNotFoundError as exc:
        raise BinaryError(f"binary not runnable: {path}") from exc
    output = result.stdout or result.stderr
    match = re.search(r"(\d+\.\d+\.\d+)", output)
    return match.group(1) if match else output.strip()
