from types import SimpleNamespace

import pytest

pytest.importorskip("prompt_toolkit")

from v2raycli.tui import widgets


class _FakeSession:
    answers = iter(())

    def prompt(self, text, **_kwargs):
        print(text)
        return next(self.answers)


def test_menu_uses_numbered_prompts(monkeypatch, capsys):
    _FakeSession.answers = iter(["2", "1, 3", "yes", "42", "secret"])
    monkeypatch.setattr(widgets, "PromptSession", _FakeSession)

    values = [("one", "One"), ("two", "Two"), ("three", "Three")]
    assert widgets.menu("Menu", values) == "two"
    assert widgets.multi_select("Profiles", values) == ["one", "three"]
    assert widgets.confirm("Continue?") is True
    assert widgets.input_int("Port") == 42
    assert widgets.input_secret("Password") == "secret"

    output = capsys.readouterr().out
    assert "1) One" in output
    assert "Select (comma separated" in output
    assert "2) Two" in output


def test_menu_blank_and_invalid_input(monkeypatch, capsys):
    _FakeSession.answers = iter([""])
    monkeypatch.setattr(widgets, "PromptSession", _FakeSession)
    assert widgets.menu("Menu", [("a", "A")]) is None

    _FakeSession.answers = iter(["99", "x", ""])
    assert widgets.menu("Menu", [("a", "A"), ("b", "B")]) is None
    output = capsys.readouterr().out
    assert "Number must be 1-2" in output


def test_multi_select_blank_returns_empty(monkeypatch):
    _FakeSession.answers = iter([""])
    monkeypatch.setattr(widgets, "PromptSession", _FakeSession)
    assert widgets.multi_select("Profiles", [("a", "A")]) == []


def test_invalid_integer_returns_default(monkeypatch, capsys):
    _FakeSession.answers = iter(["not-a-number"])
    monkeypatch.setattr(widgets, "PromptSession", _FakeSession)

    assert widgets.input_int("Port") is None
    output = capsys.readouterr().out
    assert "Invalid number" in output


def test_text_and_message_fallback(monkeypatch, capsys):
    _FakeSession.answers = iter(["", "hello"])
    monkeypatch.setattr(widgets, "PromptSession", _FakeSession)

    assert widgets.input_text("Name", "default") == ""
    widgets.show_message("Notice", "Terminal-safe message")

    output = capsys.readouterr().out
    assert "Notice" in output
    assert "Terminal-safe message" in output


def test_picker_marks_missing_client(monkeypatch):
    profile = SimpleNamespace(id="vpn-id", kind="openvpn", name="VPN")
    captured = []
    monkeypatch.setattr(
        widgets, "detect_clients", lambda: {"openvpn": None, "openconnect": "/bin/openconnect"}
    )
    monkeypatch.setattr(
        widgets, "menu", lambda title, values: captured.extend(values) or None
    )

    assert widgets.pick_profile([profile], []) is None
    assert captured[0][1].endswith("[client missing]")


def test_picker_lists_servers(monkeypatch):
    profile = SimpleNamespace(id="p", kind="vmess", name="Node")
    server = SimpleNamespace(id="s", kind=None, name="local", port=1081)
    captured = []
    monkeypatch.setattr(widgets, "detect_clients", lambda: {})
    monkeypatch.setattr(
        widgets, "menu", lambda title, values: captured.extend(values) or None
    )

    assert widgets.pick_profile([profile], [], (), [server]) is None
    labels = [label for _, label in captured]
    assert any(label.startswith("[SERVER] local :1081") for label in labels)
