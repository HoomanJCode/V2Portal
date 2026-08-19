import pytest

from v2raycli.engines.binary import (
    BinaryError,
    effective_platform,
    get_version,
    locate_binary,
    release_asset,
)


def test_release_asset_mapping():
    name, kind = release_asset("xray", "v1.8.0", "linux", "amd64")
    assert name == "Xray-linux-64.zip"
    assert kind == "zip"

    name, kind = release_asset("sing-box", "v1.10.0", "linux", "arm64")
    assert name == "sing-box-1.10.0-linux-arm64.tar.gz"
    assert kind == "tar.gz"


def test_effective_platform_android(monkeypatch):
    monkeypatch.setattr("v2raycli.engines.binary.is_android", lambda: True)
    assert effective_platform("sing-box", "linux") == "android"
    assert effective_platform("xray", "linux") == "linux"


def test_effective_platform_not_android(monkeypatch):
    monkeypatch.setattr("v2raycli.engines.binary.is_android", lambda: False)
    assert effective_platform("sing-box", "linux") == "linux"


def test_locate_absolute_path(tmp_path):
    binary = tmp_path / "xray"
    binary.write_text("#!/bin/sh\n")
    assert locate_binary("xray", {"binary_path": str(binary)}) == binary


def test_locate_absolute_missing(tmp_path):
    with pytest.raises(BinaryError):
        locate_binary("xray", {"binary_path": str(tmp_path / "nope")})


def test_locate_system(monkeypatch, tmp_path):
    fake = tmp_path / "xray"
    fake.write_text("x")
    monkeypatch.setattr("shutil.which", lambda name: str(fake) if name == "xray" else None)
    assert locate_binary("xray", {"binary_path": "system"}) == fake


def test_locate_auto_cached(tmp_path):
    cached = tmp_path / "xray"
    cached.write_text("x")
    assert locate_binary("xray", {"binary_path": "auto"}, bin_dir=tmp_path) == cached


def test_get_version(tmp_path):
    fake = tmp_path / "xray"
    fake.write_text("#!/bin/sh\necho 'Xray 1.8.9 (test)'\n")
    fake.chmod(0o755)
    assert get_version("xray", fake) == "1.8.9"
