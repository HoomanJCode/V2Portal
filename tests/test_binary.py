import sys

import pytest

from v2raycli.engines.binary import (
    BinaryError,
    _extract,
    _latest_tag,
    effective_platform,
    get_version,
    locate_binary,
    download_binary,
    release_asset,
    update_binary,
)

from conftest import make_fake_script


def test_release_asset_mapping():
    name, kind = release_asset("xray", "v1.8.0", "linux", "amd64")
    assert name == "Xray-linux-64.zip"
    assert kind == "zip"

    name, kind = release_asset("sing-box", "v1.10.0", "linux", "arm64")
    assert name == "sing-box-1.10.0-linux-arm64.tar.gz"
    assert kind == "tar.gz"

    name, kind = release_asset("sing-box", "v1.13.19", "windows", "amd64")
    assert name == "sing-box-1.13.19-windows-amd64.zip"
    assert kind == "zip"


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


def test_locate_rejects_malformed_options(tmp_path):
    with pytest.raises(BinaryError, match="options must be an object"):
        locate_binary("xray", [])
    with pytest.raises(BinaryError, match="binary_path must be text"):
        locate_binary("xray", {"binary_path": 123})


def test_download_rejects_unsafe_release_tag(tmp_path):
    from v2raycli.engines.binary import download_binary

    with pytest.raises(BinaryError, match="safe text tag"):
        download_binary("xray", "../bad", "linux", "amd64", bin_dir=tmp_path)


def test_latest_tag_requires_release_metadata(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"name": "missing-tag"}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers):
            return FakeResponse()

    monkeypatch.setattr("v2raycli.engines.binary.httpx.Client", FakeClient)
    with pytest.raises(BinaryError, match="missing tag_name"):
        _latest_tag("example/repo")


def test_latest_tag_accepts_explicit_proxy(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"tag_name": "v1.2.3"}

    class Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, headers):
            return Response()

    monkeypatch.setattr("v2raycli.engines.binary.httpx.Client", Client)

    assert _latest_tag("example/repo", proxy="socks5://proxy.example:1080") == "v1.2.3"
    assert captured["proxy"] == "socks5://proxy.example:1080"


def test_download_accepts_explicit_proxy(tmp_path, monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def iter_bytes(self):
            return [b"archive"]

    class Stream:
        def __enter__(self):
            return Response()

        def __exit__(self, *args):
            return False

    class Client:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url):
            return Stream()

    def fake_extract(archive, dest, kind, binary_name):
        (dest / binary_name).write_bytes(b"binary")

    monkeypatch.setattr("v2raycli.engines.binary.httpx.Client", Client)
    monkeypatch.setattr("v2raycli.engines.binary._extract", fake_extract)

    binary = download_binary(
        "xray", "v1.2.3", "linux", "amd64", bin_dir=tmp_path,
        proxy="http://proxy.example:8080",
    )

    assert binary.read_bytes() == b"binary"
    assert captured["proxy"] == "http://proxy.example:8080"


def test_extract_rejects_malformed_archive(tmp_path):
    archive = tmp_path / "bad.zip"
    archive.write_bytes(b"not an archive")

    with pytest.raises(BinaryError, match="invalid zip archive"):
        _extract(archive, tmp_path, "zip", "xray")


def test_locate_absolute_missing(tmp_path):
    with pytest.raises(BinaryError):
        locate_binary("xray", {"binary_path": str(tmp_path / "nope")})


def test_locate_system(monkeypatch, tmp_path):
    fake = tmp_path / "xray"
    fake.write_text("x")
    target_name = "xray.exe" if sys.platform == "win32" else "xray"
    monkeypatch.setattr("shutil.which", lambda name: str(fake) if name == target_name else None)
    assert locate_binary("xray", {"binary_path": "system"}) == fake


def test_locate_auto_cached(tmp_path):
    binary_name = "xray.exe" if sys.platform == "win32" else "xray"
    cached = tmp_path / binary_name
    cached.write_text("x")
    assert locate_binary("xray", {"binary_path": "auto"}, bin_dir=tmp_path) == cached


def test_get_version_rejects_missing_binary(tmp_path):
    with pytest.raises(BinaryError, match="not runnable"):
        get_version("xray", tmp_path / "missing")


def test_update_rejects_custom_and_running_engines(tmp_path):
    with pytest.raises(BinaryError, match="custom binary path is protected"):
        update_binary("xray", {"binary_path": str(tmp_path / "custom")}, bin_dir=tmp_path)
    with pytest.raises(BinaryError, match="while it is running"):
        update_binary("xray", {"binary_path": "auto"}, bin_dir=tmp_path, running=True)


def test_update_forwards_ephemeral_proxy(tmp_path, monkeypatch):
    from v2raycli.engines import binary

    captured = {}

    def fake_download(engine, version, platform, arch, bin_dir=None, proxy=None):
        captured["proxy"] = proxy
        path = bin_dir / "xray"
        path.write_bytes(b"new")
        return path

    monkeypatch.setattr(binary, "download_binary", fake_download)
    monkeypatch.setattr(binary, "get_version", lambda engine, path: "2.0.0")

    update_binary(
        "xray",
        {"binary_path": "auto"},
        bin_dir=tmp_path,
        proxy="socks5://proxy.example:1080",
    )

    assert captured["proxy"] == "socks5://proxy.example:1080"


def test_update_stages_verifies_and_replaces_auto_binary(tmp_path, monkeypatch):
    from v2raycli.engines import binary

    binary_name = "xray.exe" if sys.platform == "win32" else "xray"

    def fake_download(engine, version, platform, arch, bin_dir=None):
        path = bin_dir / binary_name
        path.write_bytes(b"new")
        return path

    monkeypatch.setattr(binary, "download_binary", fake_download)
    monkeypatch.setattr(binary, "get_version", lambda engine, path: "2.0.0")

    info = update_binary("xray", {"binary_path": "auto", "version": "latest"}, bin_dir=tmp_path)

    assert info.version == "2.0.0"
    assert info.previous_version is None
    assert (tmp_path / binary_name).read_bytes() == b"new"
    assert not (tmp_path / f"{binary_name}.previous").exists()


def test_update_rolls_back_when_replaced_binary_fails_verification(tmp_path, monkeypatch):
    from v2raycli.engines import binary

    binary_name = "xray.exe" if sys.platform == "win32" else "xray"
    target = tmp_path / binary_name
    target.write_bytes(b"old")

    def fake_download(engine, version, platform, arch, bin_dir=None):
        path = bin_dir / binary_name
        path.write_bytes(b"new")
        return path

    def fake_version(engine, path):
        if path == target and path.read_bytes() == b"new":
            raise BinaryError("bad replacement")
        return "1.0.0"

    monkeypatch.setattr(binary, "download_binary", fake_download)
    monkeypatch.setattr(binary, "get_version", fake_version)

    with pytest.raises(BinaryError, match="bad replacement"):
        update_binary("xray", {"binary_path": "auto"}, bin_dir=tmp_path)

    assert target.read_bytes() == b"old"
    assert not (tmp_path / f"{binary_name}.previous").exists()


def test_get_version(tmp_path):
    path = make_fake_script(tmp_path, "xray", "echo 'Xray 1.8.9 (test)'")
    assert get_version("xray", path) == "1.8.9"
