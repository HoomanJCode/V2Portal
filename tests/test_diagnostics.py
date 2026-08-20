from v2raycli import diagnostics, runner


def test_platform_report_is_read_only_and_structured(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics, "tui_available", lambda: False)
    monkeypatch.setattr(diagnostics.config, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(diagnostics.config, "BIN_DIR", tmp_path / "bin")
    monkeypatch.setattr(diagnostics.config, "GEO_DIR", tmp_path / "geo")
    monkeypatch.setattr(diagnostics.config, "BACKUP_DIR", tmp_path / "backup")
    monkeypatch.setattr(diagnostics.config, "config_dir", lambda: tmp_path)
    monkeypatch.setattr(diagnostics, "detect_clients", lambda: {"openvpn": None, "openconnect": None})

    report = diagnostics.platform_report()

    assert report["config_dir"] == str(tmp_path)
    assert report["tui_available"] is False
    assert report["vpn_clients"] == {"openvpn": None, "openconnect": None}
    assert report["process_mode"] in {"own-session", "windows-no-window-new-process-group"}
    assert not (tmp_path / "runtime").exists()
    assert not (tmp_path / "bin").exists()


def test_platform_report_maps_windows_process_mode(monkeypatch):
    monkeypatch.setattr(runner.os, "name", "nt")
    monkeypatch.setattr(runner.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(runner.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    monkeypatch.setattr(diagnostics, "tui_available", lambda: True)
    monkeypatch.setattr(diagnostics, "detect_clients", lambda: {})

    assert diagnostics.platform_report()["process_mode"] == (
        "windows-no-window-new-process-group"
    )
