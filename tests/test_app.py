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
    assert app.main(["--config-dir", str(tmp_path), "status"]) == 0
    out = capsys.readouterr().out
    assert "profiles: 0" in out


def test_main_reports_malformed_config(tmp_path, capsys):
    (tmp_path / "config.json").write_text("{not-json")

    assert app.main(["--config-dir", str(tmp_path), "status"]) == 1
    assert "config load failed" in capsys.readouterr().err


def test_probe_flag_resolves_scope_and_returns_failure(tmp_path, monkeypatch):
    from v2raycli.test import latency

    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    captured = {}

    def fake_probe_many(profiles, concurrency=8, timeout=5.0):
        captured["profiles"] = list(profiles)
        return [latency.EndpointResult(profile_id=profile.id, name=profile.name, tcp_status="refused")]

    monkeypatch.setattr(latency, "probe_many", fake_probe_many)
    monkeypatch.setattr(latency, "render_endpoint_table", lambda results: None)

    assert app._probe(store, profile.id) == 1
    assert captured["profiles"] == [profile]


def test_probe_parser_option():
    args = app.build_parser().parse_args(["test", "endpoint", "all"])

    assert args.test_type == "endpoint"
    assert args.scope == "all"


def test_ws_test_parser_option():
    args = app.build_parser().parse_args(["test", "websocket", "all"])

    assert args.test_type == "websocket"
    assert args.scope == "all"


def test_test_defaults_to_endpoint():
    # Bare `test` and `test <id>` default to an endpoint probe.
    args = app.build_parser().parse_args(["test"])
    assert args.test_type == "endpoint"
    assert args.scope == "all"

    args = app.build_parser().parse_args(["test", "005"])
    # An unrecognized first token is treated as a scope (endpoint probe);
    # the dispatch determines the effective type, not the parser.
    assert args.test_type == "005"
    assert args.scope == "all"


def test_update_parser_option():
    args = app.build_parser().parse_args(["engine", "update", "both", "--proxy", "socks5://proxy.example:1080"])

    assert args.engine == "both"
    assert args.proxy == "socks5://proxy.example:1080"


def test_update_cli_reports_each_engine(tmp_path, monkeypatch, capsys):
    from v2raycli.engines import binary
    from v2raycli.engines.binary import UpdateInfo

    store = _store(tmp_path)
    calls = []

    def fake_update(engine, options):
        calls.append((engine, options))
        return UpdateInfo(engine, tmp_path / engine, "2.0.0", "1.0.0")

    monkeypatch.setattr(binary, "update_binary", fake_update)

    assert app._update(store, "both") == 0
    assert [engine for engine, _ in calls] == ["sing-box", "xray"]
    assert "sing-box: 1.0.0 -> 2.0.0" in capsys.readouterr().out


def test_update_cli_forwards_ephemeral_proxy(tmp_path, monkeypatch):
    from v2raycli.engines import binary
    from v2raycli.engines.binary import UpdateInfo

    store = _store(tmp_path)
    captured = {}

    def fake_update(engine, options, **kwargs):
        captured["engine"] = engine
        captured["options"] = options
        captured["proxy"] = kwargs.get("proxy")
        return UpdateInfo(engine, tmp_path / engine, "2.0.0")

    monkeypatch.setattr(binary, "update_binary", fake_update)

    assert app._update(store, "sing-box", "http://proxy.example:8080") == 0
    assert captured["proxy"] == "http://proxy.example:8080"


def test_ws_test_skips_non_websocket_profiles(tmp_path, monkeypatch):
    from v2raycli.test import latency

    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    monkeypatch.setattr(
        latency,
        "websocket_test_many",
        lambda profiles, settings, engines=None, concurrency=4, bin_dir=None: [
            latency.WebSocketResult(profile_id=profile.id, name=profile.name, not_testable=True)
        ],
    )
    monkeypatch.setattr(latency, "render_websocket_table", lambda results: None)

    assert app._ws_test(store, profile.id) == 0


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


def test_test_flag_group_and_server_scope(tmp_path, monkeypatch):
    from v2raycli.test import latency
    from v2raycli.models import Group, Server

    store = _store(tmp_path)
    p1 = store.add_profile(Profile(name="a", kind="socks", outbound=SOCKS))
    p2 = store.add_profile(Profile(name="b", kind="socks", outbound=SOCKS))
    group = store.add_group(
        Group(name="g", type="balancer", strategy="latency", profile_ids=[p1.id, p2.id])
    )
    server = store.add_server(Server(name="srv", outbound_type="group", outbound_id=group.id))

    tested: list = []
    monkeypatch.setattr(latency, "render_table", lambda results: None)
    monkeypatch.setattr(latency, "save_results", lambda results, path=None: None)

    def fake_test_many(profiles, settings, engines=None, concurrency=8, bin_dir=None):
        tested.extend(p.id for p in profiles)
        return [latency.TestResult(profile_id=p.id, name=p.name, ok=True) for p in profiles]

    monkeypatch.setattr(latency, "test_many", fake_test_many)

    assert app._test(store, group.id) == 0
    assert tested == [p1.id, p2.id]  # group scope resolves to its members

    tested.clear()
    assert app._test(store, server.id) == 0
    assert tested == [p1.id, p2.id]  # server scope resolves its outbound target

    tested.clear()
    assert app._test(store, "999") == 1  # unknown id -> no matching profiles


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


