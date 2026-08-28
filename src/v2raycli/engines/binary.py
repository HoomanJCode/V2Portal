"""Engine binary location, download, and version detection."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from .. import config
from ..errors import V2RayCLIError
from .base import get_adapter


class BinaryError(V2RayCLIError):
    pass


@dataclass(frozen=True)
class UpdateInfo:
    engine: str
    path: Path
    version: str
    previous_version: str | None = None


def platform_name() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def is_android() -> bool:
    """Detect Termux/Android (bionic libc) where sing-box needs android builds."""
    return os.path.exists("/system/build.prop") or bool(os.environ.get("TERMUX_VERSION"))


def effective_platform(engine: str, platform: str) -> str:
    """Map linux->android for sing-box on Termux/Android.

    xray's linux-arm64 build runs on bionic, so it stays on ``linux``.
    """
    if engine == "sing-box" and platform == "linux" and is_android():
        return "android"
    return platform


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

    ``version`` is a release tag (e.g. ``v1.13.19``). sing-box asset names use
    the tag without the leading ``v``; xray assets are version-less.
    """
    if engine == "xray":
        plat = {"windows": "windows", "linux": "linux", "darwin": "macos"}.get(platform, platform)
        a = {"amd64": "64", "arm64": "arm64-v8a", "armv7": "armv7a"}.get(arch, arch)
        return f"Xray-{plat}-{a}.zip", "zip"
    bare = (version or "").lstrip("v")
    if platform == "windows":
        return f"sing-box-{bare}-{platform}-{arch}.zip", "zip"
    return f"sing-box-{bare}-{platform}-{arch}.tar.gz", "tar.gz"


def _latest_tag(repo: str, proxy: str | None = None) -> str:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        client_options = {"follow_redirects": True, "timeout": 30.0}
        if proxy:
            client_options["proxy"] = proxy
        with httpx.Client(**client_options) as client:
            resp = client.get(
                url,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "v2raycli"},
            )
            resp.raise_for_status()
            payload = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        msg = str(exc).lower()
        if "timeout" in msg or "handshake" in msg or "connect" in msg:
            hint = (
                f"cannot reach GitHub ({exc}). "
                "Check your internet connection or use a proxy:\n"
                "  v2raycli settings engine update sing-box --proxy socks5://HOST:PORT"
            )
            raise BinaryError(hint) from exc
        raise BinaryError(f"could not resolve latest release: {exc}") from exc
    tag = payload.get("tag_name") if isinstance(payload, dict) else None
    if not isinstance(tag, str) or not tag.strip():
        raise BinaryError("latest release response is missing tag_name")
    return tag.strip()


def _extract(archive: Path, dest: Path, kind: str, binary_name: str) -> None:
    def matches(name: str) -> bool:
        return name == binary_name or name.endswith("/" + binary_name)

    try:
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
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        raise BinaryError(f"invalid {kind} archive {archive}: {exc}") from exc
    raise BinaryError(f"binary {binary_name} not found in {archive}")


def download_binary(
    engine: str,
    version: str,
    platform: str,
    arch: str,
    bin_dir: Path | None = None,
    proxy: str | None = None,
) -> Path:
    adapter = get_adapter(engine)
    bin_dir = bin_dir or config.BIN_DIR
    bin_dir.mkdir(parents=True, exist_ok=True)
    platform = effective_platform(engine, platform)

    repo = "XTLS/Xray-core" if engine == "xray" else "SagerNet/sing-box"
    tag = version or "latest"
    if tag == "latest":
        tag = _latest_tag(repo, proxy=proxy)
    if not isinstance(tag, str) or not tag.strip() or any(char in tag for char in ("/", "\\")):
        raise BinaryError("release version must be a safe text tag")
    for label, value in (("platform", platform), ("architecture", arch)):
        if not isinstance(value, str) or not value.strip() or any(
            char in value for char in ("/", "\\")
        ):
            raise BinaryError(f"release {label} must be safe text")
    asset, kind = release_asset(engine, tag, platform, arch)
    url = f"https://github.com/{repo}/releases/download/{tag}/{asset}"
    archive_path = bin_dir / asset

    try:
        client_options = {"follow_redirects": True, "timeout": 60.0}
        if proxy:
            client_options["proxy"] = proxy
        with httpx.Client(**client_options) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(archive_path, "wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
    except (httpx.HTTPError, OSError) as exc:
        archive_path.unlink(missing_ok=True)
        raise BinaryError(f"download failed: {exc}") from exc

    binary_name = adapter.binary_filename(platform, arch)
    try:
        _extract(archive_path, bin_dir, kind, binary_name)
    except BinaryError:
        archive_path.unlink(missing_ok=True)
        (bin_dir / binary_name).unlink(missing_ok=True)
        raise
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

    if not isinstance(options, dict):
        raise BinaryError("engine options must be an object")
    path = options.get("binary_path", "auto")
    if path is not None and not isinstance(path, (str, os.PathLike)):
        raise BinaryError("binary_path must be text")
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


def update_binary(
    engine: str,
    options: dict,
    bin_dir: Path | None = None,
    *,
    running: bool = False,
    platform: str | None = None,
    arch: str | None = None,
    proxy: str | None = None,
) -> UpdateInfo:
    """Download, verify, and atomically replace an auto-managed engine binary."""
    if not isinstance(options, dict):
        raise BinaryError("engine options must be an object")
    if running:
        raise BinaryError(f"cannot update {engine} while it is running")
    binary_path = options.get("binary_path", "auto")
    if binary_path not in (None, "", "auto"):
        raise BinaryError(f"custom binary path is protected: {binary_path}")

    platform = platform or platform_name()
    arch = arch or arch_name()
    effective = effective_platform(engine, platform)
    adapter = get_adapter(engine)
    target_dir = bin_dir or config.BIN_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / adapter.binary_filename(effective, arch)
    if target.exists() and not target.is_file():
        raise BinaryError(f"cached binary path is not a file: {target}")

    previous_version: str | None = None
    if target.is_file():
        try:
            previous_version = get_version(engine, target)
        except BinaryError:
            previous_version = None

    rollback = target.with_name(target.name + ".previous")
    try:
        with tempfile.TemporaryDirectory(prefix=f"{engine}-update-", dir=str(target_dir)) as staging:
            download_options = {"bin_dir": Path(staging)}
            if proxy:
                download_options["proxy"] = proxy
            staged = download_binary(
                engine,
                options.get("version", "latest"),
                platform,
                arch,
                **download_options,
            )
            staged_version = get_version(engine, staged)
            if not staged_version:
                raise BinaryError(f"downloaded {engine} binary has no detectable version")

            had_previous = target.is_file()
            if rollback.exists():
                rollback.unlink()
            if had_previous:
                os.replace(target, rollback)
            try:
                os.replace(staged, target)
                target.chmod(0o755)
                verified_version = get_version(engine, target)
                if not verified_version:
                    raise BinaryError(f"replaced {engine} binary has no detectable version")
            except Exception as exc:
                target.unlink(missing_ok=True)
                if had_previous and rollback.exists():
                    os.replace(rollback, target)
                if isinstance(exc, BinaryError):
                    raise
                raise BinaryError(f"could not replace {engine} binary: {exc}") from exc
            rollback.unlink(missing_ok=True)
            return UpdateInfo(engine, target, verified_version, previous_version)
    except BinaryError:
        raise
    except (OSError, ValueError) as exc:
        raise BinaryError(f"engine update failed: {exc}") from exc


def get_version(engine: str, path: Path) -> str:
    """Run ``<binary> version`` and extract the version string."""
    if not isinstance(path, (str, os.PathLike)):
        raise BinaryError("binary path must be text")
    try:
        result = subprocess.run([str(path), "version"], capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        raise BinaryError(f"binary not runnable: {path}") from exc
    output = result.stdout or result.stderr or ""
    if result.returncode != 0:
        raise BinaryError(f"binary version command failed: {output.strip() or result.returncode}")
    match = re.search(r"(\d+\.\d+\.\d+)", output)
    return match.group(1) if match else output.strip()
