from v2raycli import service
from v2raycli.models import Profile
from v2raycli.storage import ConfigStore

SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}


def _store(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    return store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))


def test_platform_detection(monkeypatch):
    monkeypatch.delenv("PREFIX", raising=False)
    monkeypatch.delenv("TERMUX_VERSION", raising=False)
    monkeypatch.setattr(service.sys, "platform", "linux")
    assert service.platform() == "linux"

    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    monkeypatch.setenv("TERMUX_VERSION", "0.118")
    assert service.platform() == "termux"

    monkeypatch.delenv("PREFIX", raising=False)
    monkeypatch.delenv("TERMUX_VERSION", raising=False)
    monkeypatch.setattr(service.sys, "platform", "win32")
    assert service.platform() == "windows"


def test_build_systemd_unit():
    unit = service.build_systemd_unit("abc123", "/tmp/cfg")
    assert "ExecStart=" in unit
    assert "--connect abc123" in unit
    assert "--config-dir /tmp/cfg" in unit
    assert "WantedBy=default.target" in unit


def test_build_systemd_unit_no_config_dir():
    unit = service.build_systemd_unit("abc123")
    assert "--config-dir" not in unit


def test_build_termux_run_script():
    script = service.build_termux_run_script("abc123")
    assert script.startswith("#!/data/data/com.termux/files/usr/bin/sh")
    assert "exec " in script
    assert "--connect abc123" in script


def test_install_service_unknown_id(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    try:
        service.install_service(store, "nope")
    except ValueError as exc:
        assert "unknown" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_install_service_linux(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    unit_dir = tmp_path / "systemd"
    monkeypatch.setattr(service, "platform", lambda: "linux")
    monkeypatch.setattr(service, "systemd_unit_dir", lambda: unit_dir)

    path = service.install_service(store, profile.id)
    assert path == unit_dir / "v2raycli.service"
    assert "--connect" in path.read_text(encoding="utf-8")


def test_install_service_termux(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    sv_dir = tmp_path / "sv"
    monkeypatch.setattr(service, "platform", lambda: "termux")
    monkeypatch.setattr(service, "termux_service_dir", lambda: sv_dir / "v2raycli")

    path = service.install_service(store, profile.id)
    assert path == sv_dir / "v2raycli" / "run"
    assert path.exists()


def test_install_service_unsupported(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    monkeypatch.setattr(service, "platform", lambda: "darwin")
    try:
        service.install_service(store, profile.id)
    except RuntimeError as exc:
        assert "darwin" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_uninstall_service_removes(tmp_path, monkeypatch):
    unit_dir = tmp_path / "systemd"
    unit = unit_dir / "v2raycli.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("x")
    monkeypatch.setattr(service, "platform", lambda: "linux")
    monkeypatch.setattr(service, "systemd_unit_dir", lambda: unit_dir)

    assert service.uninstall_service() == unit
    assert not unit.exists()


def test_uninstall_service_nothing(tmp_path, monkeypatch):
    unit_dir = tmp_path / "systemd"
    monkeypatch.setattr(service, "platform", lambda: "linux")
    monkeypatch.setattr(service, "systemd_unit_dir", lambda: unit_dir)
    assert service.uninstall_service() is None
