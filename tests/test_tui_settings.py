from v2raycli.storage import ConfigStore
from v2raycli.tui import settings_screen


def test_settings_can_toggle_lan_sharing(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    actions = iter(["lan", "back"])

    monkeypatch.setattr(settings_screen.widgets, "menu", lambda *args, **kwargs: next(actions))
    monkeypatch.setattr(settings_screen.widgets, "confirm", lambda question: False)

    settings_screen.run(store)

    assert store.config.settings.allow_lan is False
