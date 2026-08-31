from types import SimpleNamespace

import pytest

pytest.importorskip("prompt_toolkit")

from v2portal.engines.binary import BinaryError, UpdateInfo
from v2portal.storage import ConfigStore
from v2portal.tui import settings_screen


def test_settings_can_toggle_lan_sharing(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    actions = iter(["lan", "back"])

    monkeypatch.setattr(settings_screen.widgets, "menu", lambda *args, **kwargs: next(actions))
    monkeypatch.setattr(settings_screen.widgets, "confirm", lambda question: False)

    settings_screen.run(store)

    assert store.config.settings.allow_lan is False


def test_settings_update_requires_confirmation_and_reports_version(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    messages = []

    monkeypatch.setattr(settings_screen.widgets, "menu", lambda *args, **kwargs: "xray")
    monkeypatch.setattr(settings_screen.widgets, "confirm", lambda question: True)
    monkeypatch.setattr(
        settings_screen,
        "update_binary",
        lambda engine, options, running=False: UpdateInfo(
            engine, tmp_path / engine, "2.0.0", "1.0.0"
        ),
    )
    monkeypatch.setattr(
        settings_screen.widgets,
        "show_message",
        lambda title, text: messages.append((title, text)),
    )

    settings_screen.run_updates(store)

    assert messages == [("Engine updates", "xray: 1.0.0 -> 2.0.0")]


def test_settings_update_blocks_connected_engine(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    running_flags = []

    monkeypatch.setattr(settings_screen.widgets, "menu", lambda *args, **kwargs: "sing-box")
    monkeypatch.setattr(settings_screen.widgets, "confirm", lambda question: True)

    def fake_update(engine, options, running=False):
        running_flags.append(running)
        raise BinaryError("cannot update sing-box while it is running")

    monkeypatch.setattr(settings_screen, "update_binary", fake_update)
    messages = []
    monkeypatch.setattr(settings_screen.widgets, "show_message", lambda title, text: messages.append(text))

    settings_screen.run_updates(
        store,
        SimpleNamespace(status=SimpleNamespace(state="connected", engine="sing-box")),
    )

    assert running_flags == [True]
    assert "while it is running" in messages[0]
