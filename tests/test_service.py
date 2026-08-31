from v2portal import service
from v2portal.models import Profile
from v2portal.storage import ConfigStore

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
    unit = service.build_systemd_unit("/tmp/cfg")
    assert "ExecStart=" in unit
    assert "server start --all" in unit
    assert "--config-dir /tmp/cfg" in unit
    assert "WantedBy=default.target" in unit


def test_build_systemd_unit_no_config_dir():
    unit = service.build_systemd_unit()
    assert "--config-dir" not in unit


def test_build_termux_run_script():
    script = service.build_termux_run_script()
    assert script.startswith("#!/data/data/com.termux/files/usr/bin/sh")
    assert "exec " in script
    assert "server start --all" in script


def test_install_service_linux(tmp_path, monkeypatch):
    _store(tmp_path)
    unit_dir = tmp_path / "systemd"
    monkeypatch.setattr(service, "platform", lambda: "linux")
    monkeypatch.setattr(service, "systemd_unit_dir", lambda: unit_dir)

    path = service.install_service()
    assert path == unit_dir / "v2portal.service"
    assert "server start --all" in path.read_text(encoding="utf-8")


def test_install_service_termux(tmp_path, monkeypatch):
    _store(tmp_path)
    sv_dir = tmp_path / "sv"
    monkeypatch.setattr(service, "platform", lambda: "termux")
    monkeypatch.setattr(service, "termux_service_dir", lambda: sv_dir / "v2portal")

    path = service.install_service()
    assert path == sv_dir / "v2portal" / "run"
    assert path.exists()
    assert "server start --all" in path.read_text(encoding="utf-8")


def test_install_service_unsupported(tmp_path, monkeypatch):
    _store(tmp_path)
    monkeypatch.setattr(service, "platform", lambda: "darwin")
    try:
        service.install_service()
    except RuntimeError as exc:
        assert "darwin" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_uninstall_service_removes(tmp_path, monkeypatch):
    unit_dir = tmp_path / "systemd"
    unit = unit_dir / "v2portal.service"
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
