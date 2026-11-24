from scripts.verify_engines import Checks, acquire_binaries, build_parser


def test_verify_engines_parser_accepts_ephemeral_proxy():
    args = build_parser().parse_args(
        ["--proxy", "socks5://proxy.example:1080", "--skip-download"]
    )

    assert args.proxy == "socks5://proxy.example:1080"
    assert args.skip_download is True


def test_acquire_binaries_reports_missing_engine_without_raising(tmp_path, monkeypatch):
    checks = Checks()

    def fail_download(*args, **kwargs):
        raise RuntimeError("network unavailable")

    monkeypatch.setattr("scripts.verify_engines.download_binary", fail_download)

    binaries = acquire_binaries(checks, tmp_path, proxy="socks5://proxy.example:1080")

    assert binaries == {}
    assert [name for name, ok, _ in checks.results] == ["sing-box binary", "xray binary"]
    assert all(not ok for _, ok, _ in checks.results)


def test_acquire_binaries_reuses_existing_files_without_download(tmp_path, monkeypatch):
    checks = Checks()
    (tmp_path / "sing-box").write_bytes(b"sing-box")
    (tmp_path / "xray").write_bytes(b"xray")

    def fail_download(*args, **kwargs):
        raise AssertionError("download should be skipped")

    monkeypatch.setattr("scripts.verify_engines.download_binary", fail_download)

    binaries = acquire_binaries(checks, tmp_path, skip_download=True)

    assert binaries == {"sing-box": tmp_path / "sing-box", "xray": tmp_path / "xray"}
    assert all(ok for _, ok, _ in checks.results)


def test_acquire_binaries_skip_download_reports_missing_files(tmp_path, monkeypatch):
    checks = Checks()

    def fail_download(*args, **kwargs):
        raise AssertionError("skip_download must not download")

    monkeypatch.setattr("scripts.verify_engines.download_binary", fail_download)

    binaries = acquire_binaries(checks, tmp_path, skip_download=True)

    assert binaries == {}
    assert all(not ok for _, ok, _ in checks.results)
    assert all("FileNotFoundError" in detail for _, _, detail in checks.results)


def test_acquire_binaries_uses_platform_binary_names(tmp_path, monkeypatch):
    checks = Checks()
    singbox = tmp_path / "sing-box.exe"
    xray = tmp_path / "xray.exe"
    singbox.write_bytes(b"sing-box")
    xray.write_bytes(b"xray")
    monkeypatch.setattr("scripts.verify_engines.platform_name", lambda: "windows")
    monkeypatch.setattr("scripts.verify_engines.arch_name", lambda: "amd64")
    monkeypatch.setattr(
        "scripts.verify_engines.download_binary",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("download should be skipped")),
    )

    binaries = acquire_binaries(checks, tmp_path, skip_download=True)

    assert binaries == {"sing-box": singbox, "xray": xray}
    assert all(ok for _, ok, _ in checks.results)
