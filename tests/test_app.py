from v2raycli import config
from v2raycli.app import main


def test_main_runs_and_exits_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)

    assert main() == 0
    out = capsys.readouterr().out
    assert "v2raycli v" in out
    assert "profiles: 0" in out
