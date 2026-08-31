from v2raycli import config


def test_windows_config_dir_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_pdirs_user_config_dir", None)
    monkeypatch.setattr(config.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))

    assert config._user_config_dir("v2portal") == str(
        tmp_path / "AppData" / "Roaming" / "v2portal"
    )


def test_unix_config_dir_fallback_uses_xdg(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_pdirs_user_config_dir", None)
    monkeypatch.setattr(config.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    assert config._user_config_dir("v2portal") == str(
        tmp_path / "config" / "v2portal"
    )
