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

    monkeypatch.setattr("v2raycli.connection.ConnectionController", FakeController)

    assert app._connect(store, profile.id) == 0
    out = capsys.readouterr().out
    assert "connected to t" in out
    assert "socks5://" in out
