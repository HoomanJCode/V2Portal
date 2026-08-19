from os import terminal_size
from types import SimpleNamespace

from v2raycli.tui import widgets


class _FakeSession:
    answers = iter(())

    def prompt(self, _text, **_kwargs):
        return next(self.answers)


def test_small_terminal_uses_numbered_prompts(monkeypatch, capsys):
    monkeypatch.setattr(widgets.shutil, "get_terminal_size", lambda fallback: terminal_size((40, 10)))
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


def test_invalid_integer_returns_default(monkeypatch, capsys):
    monkeypatch.setattr(widgets.shutil, "get_terminal_size", lambda fallback: terminal_size((40, 10)))
    _FakeSession.answers = iter(["not-a-number"])
    monkeypatch.setattr(widgets, "PromptSession", _FakeSession)

    assert widgets.input_int("Port") is None
    output = capsys.readouterr().out
    assert "Invalid number" in output


def test_small_terminal_text_and_message_fallback(monkeypatch, capsys):
    monkeypatch.setattr(widgets.shutil, "get_terminal_size", lambda fallback: terminal_size((50, 20)))
    _FakeSession.answers = iter(["", "hello"])
    monkeypatch.setattr(widgets, "PromptSession", _FakeSession)

    assert widgets.input_text("Name", "default") == ""
    widgets.show_message("Notice", "Terminal-safe message")

    output = capsys.readouterr().out
    assert "Notice" in output
    assert "Terminal-safe message" in output


def test_terminal_size_error_uses_simple_ui(monkeypatch):
    def fail(_fallback):
        raise OSError("no terminal")

    monkeypatch.setattr(widgets.shutil, "get_terminal_size", fail)
    assert widgets._use_simple_ui() is True


def test_vpn_picker_marks_missing_client(monkeypatch):
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
