from v2raycli import app, config
from v2raycli.models import Profile, Subscription
from v2raycli.storage import ConfigStore

SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}


def _store(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    return store


def test_main_runs_and_exits_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backup")
    monkeypatch.setattr(config, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(config, "BIN_DIR", tmp_path / "bin")
    monkeypatch.setattr(config, "GEO_DIR", tmp_path / "geo")
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)

    assert app.main([]) == 0
    out = capsys.readouterr().out
    assert "v2raycli v" in out
    assert "profiles: 0" in out


def test_version_flag(capsys):
    assert app.main(["--version"]) == 0
    assert "v2raycli v" in capsys.readouterr().out


def test_config_dir_flag(tmp_path):
    rc = app.main(["--config-dir", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / "config.json").exists()


def test_headless_summary(tmp_path, capsys):
    assert app.main(["--headless", "--config-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "profiles: 0" in out


def test_main_reports_malformed_config(tmp_path, capsys):
    (tmp_path / "config.json").write_text("{not-json")

    assert app.main(["--headless", "--config-dir", str(tmp_path)]) == 1
    assert "config load failed" in capsys.readouterr().err


def test_connect_unknown_id(tmp_path, capsys):
    store = _store(tmp_path)
    assert app._connect(store, "nope") == 1
    assert "unknown" in capsys.readouterr().err


def test_test_flag_all(tmp_path, monkeypatch):
    from v2raycli.test import latency

    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))

    monkeypatch.setattr(latency, "render_table", lambda results: None)
    monkeypatch.setattr(latency, "save_results", lambda results, path=None: None)
    monkeypatch.setattr(
        latency,
        "test_many",
        lambda profiles, settings, engines=None, concurrency=8, bin_dir=None: [
            latency.TestResult(profile_id=p.id, name=p.name, ok=True, latency_ms=10.0) for p in profiles
        ],
    )

    assert app._test(store, "all") == 0


def test_test_flag_no_match(tmp_path):
    store = _store(tmp_path)
    assert app._test(store, "all") == 1


def test_test_flag_scope_resolution(tmp_path, monkeypatch, capsys):
    from v2raycli.test import latency

    store = _store(tmp_path)
    sub = store.add_subscription(Subscription(name="sub"))
    p1 = store.add_profile(Profile(name="a", kind="socks", outbound=SOCKS, subscription_id=sub.id))
    p2 = store.add_profile(Profile(name="b", kind="socks", outbound=SOCKS))

    tested: list = []
    monkeypatch.setattr(latency, "render_table", lambda results: None)
    monkeypatch.setattr(latency, "save_results", lambda results, path=None: None)

    def fake_test_many(profiles, settings, engines=None, concurrency=8, bin_dir=None):
        tested.extend(p.id for p in profiles)
        return [latency.TestResult(profile_id=p.id, name=p.name, ok=True) for p in profiles]

    monkeypatch.setattr(latency, "test_many", fake_test_many)

    assert app._test(store, sub.id) == 0
    assert tested == [p1.id]  # subscription scope resolves to its node only

    tested.clear()
    assert app._test(store, p2.id) == 0
    assert tested == [p2.id]


def test_backup_flag(tmp_path, monkeypatch, capsys):
    from v2raycli import backup

    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backup")
    store = _store(tmp_path)
    store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))

    assert app._backup(store) == 0
    assert (tmp_path / "backup").is_dir()
    assert len(backup.list_backups()) == 1
    assert "backup-" in capsys.readouterr().out


def test_list_backups_flag(tmp_path, monkeypatch, capsys):
    from v2raycli import backup

    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backup")
    store = _store(tmp_path)
    store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    backup.create_backup("one", store=store)
    backup.create_backup("two", store=store)

    assert app._list_backups() == 0
    out = capsys.readouterr().out
    assert "one" in out and "two" in out


def test_restore_flag(tmp_path, monkeypatch, capsys):
    from v2raycli import backup

    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backup")
    store = _store(tmp_path)
    store.add_profile(Profile(name="original", kind="socks", outbound=SOCKS))
    store.save()
    snap = backup.create_backup("snap", store=store)

    store.config.profiles[0].name = "changed"
    store.save()

    assert app._restore(store, str(snap)) == 0
    assert store.config.profiles[0].name == "original"
    assert "restored" in capsys.readouterr().out


def test_export_flag(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    target = tmp_path / "export.json"

    assert app._export(store, str(target), False) == 0
    assert "schema_version" in target.read_text(encoding="utf-8")
    assert "exported" in capsys.readouterr().out


def test_export_redact_flag(tmp_path, monkeypatch):
    store = _store(tmp_path)
    auth = {
        "settings": {
            "servers": [
                {"address": "1.2.3.4", "port": 1080, "username": "u", "password": "secret"}
            ]
        }
    }
    store.add_profile(Profile(name="s", kind="socks", outbound=auth))
    target = tmp_path / "export.json"

    assert app._export(store, str(target), True) == 0
    content = target.read_text(encoding="utf-8")
    assert "REDACTED" in content
    assert "secret" not in content


def test_import_flag_merge(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backup")
    source = _store(tmp_path)
    source.add_profile(Profile(name="shared", kind="socks", outbound=SOCKS))
    exported = tmp_path / "export.json"
    app._export(source, str(exported), False)

    dest = _store(tmp_path / "other")
    assert app._import(dest, str(exported), False) == 0
    assert [p.name for p in dest.config.profiles] == ["shared"]


def test_import_flag_replace(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backup")
    source = _store(tmp_path)
    source.add_profile(Profile(name="shared", kind="socks", outbound=SOCKS))
    exported = tmp_path / "export.json"
    app._export(source, str(exported), False)

    dest = _store(tmp_path / "other")
    dest.add_profile(Profile(name="local-only", kind="socks", outbound=SOCKS))
    assert app._import(dest, str(exported), True) == 0
    assert [p.name for p in dest.config.profiles] == ["shared"]


def test_install_service_flag(tmp_path, monkeypatch, capsys):
    from v2raycli import service

    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    monkeypatch.setattr(service, "platform", lambda: "linux")
    monkeypatch.setattr(service, "install_service", lambda s, i, c: tmp_path / "unit")

    assert app._install_service(store, profile.id, None) == 0
    assert "installed" in capsys.readouterr().out


def test_install_service_flag_unknown_id(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    assert app._install_service(store, "nope", None) == 1
    assert "unknown" in capsys.readouterr().err


def test_uninstall_service_flag(tmp_path, monkeypatch, capsys):
    from v2raycli import service

    monkeypatch.setattr(service, "uninstall_service", lambda: None)
    assert app._uninstall_service() == 0
    assert "no service" in capsys.readouterr().out


def test_connect_runs_and_disconnects(tmp_path, monkeypatch, capsys):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="t", kind="socks", outbound=SOCKS))

    class FakeProc:
        def is_running(self):
            return False

    class FakeStatus:
        state = "connected"
        target_name = "t"
        engine = "sing-box"
        inbound = {"urls": ["socks5://0.0.0.0:1080"], "lan": []}

    class FakeController:
        proc = FakeProc()

        def __init__(self, store):
            self.store = store
            self.disconnected = False

        def connect(self, selection):
            return FakeStatus()

        def disconnect(self):
            self.disconnected = True

        def traffic(self):
            return None

    monkeypatch.setattr("v2raycli.connection.ConnectionController", FakeController)

    assert app._connect(store, profile.id) == 0
    out = capsys.readouterr().out
    assert "connected to t" in out
    assert "socks5://" in out
