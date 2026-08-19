"""Prompt-toolkit dialog wrappers used by the TUI screens.

Small Termux windows do not reliably have enough room for prompt-toolkit's
full-screen dialogs.  In that case these helpers use numbered text prompts so
all TUI flows remain usable without requiring a larger terminal.
"""

from __future__ import annotations

import shutil

from prompt_toolkit import PromptSession
from prompt_toolkit.shortcuts import (
    checkboxlist_dialog,
    confirm as _confirm,
    input_dialog,
    message_dialog,
    radiolist_dialog,
)


_MIN_DIALOG_COLUMNS = 60
_MIN_DIALOG_LINES = 12


def _use_simple_ui() -> bool:
    """Return whether the terminal is too small for full-screen dialogs."""
    try:
        size = shutil.get_terminal_size(fallback=(80, 24))
    except OSError:
        return True
    return size.columns < _MIN_DIALOG_COLUMNS or size.lines < _MIN_DIALOG_LINES


def _prompt(text: str, default: str = "", *, password: bool = False) -> str:
    try:
        return PromptSession().prompt(text, default=default, is_password=password)
    except (EOFError, KeyboardInterrupt):
        return default


def _simple_menu(title: str, values, text: str = ""):
    print(f"\n{title}")
    if text:
        print(text)
    for index, (_, label) in enumerate(values, 1):
        print(f"  {index}) {label}")
    raw = _prompt("Select: ").strip()
    try:
        index = int(raw)
    except ValueError:
        return None
    return values[index - 1][0] if 1 <= index <= len(values) else None


def _simple_multi_select(title: str, values, text: str = "") -> list:
    print(f"\n{title}")
    if text:
        print(text)
    for index, (_, label) in enumerate(values, 1):
        print(f"  {index}) {label}")
    raw = _prompt("Select (comma separated, blank for none): ")
    selected = []
    for token in raw.split(","):
        try:
            index = int(token.strip())
        except ValueError:
            continue
        if 1 <= index <= len(values) and values[index - 1][0] not in selected:
            selected.append(values[index - 1][0])
    return selected


def menu(title: str, values, text: str = ""):
    """Single-select from ``values=[(value, label)]``; returns value or None."""
    values = list(values)
    if _use_simple_ui():
        return _simple_menu(title, values, text)
    return radiolist_dialog(title=title, text=text, values=values).run()


def multi_select(title: str, values, text: str = ""):
    """Multi-select from ``values=[(value, label)]``; returns list or None."""
    values = list(values)
    if _use_simple_ui():
        return _simple_multi_select(title, values, text)
    return checkboxlist_dialog(title=title, text=text, values=values).run()


def confirm(question: str) -> bool:
    if _use_simple_ui():
        return _prompt(f"{question} [y/N]: ").strip().lower() in {"y", "yes"}
    return _confirm(question)


def input_text(prompt: str, default: str = "") -> str:
    if _use_simple_ui():
        return _prompt(f"{prompt}: ", default=default)
    value = input_dialog(title="Input", text=prompt).run()
    return value if value is not None else default


def input_int(prompt: str, default=None):
    if _use_simple_ui():
        raw = _prompt(f"{prompt}: ", default="" if default is None else str(default))
    else:
        raw = input_dialog(title="Input", text=prompt).run()
        if raw is None or raw.strip() == "":
            return default
    if raw.strip() == "":
        return default
    return int(raw.strip())


def input_secret(prompt: str) -> str:
    return _prompt(f"{prompt}: ", password=True)


def show_message(title: str, text: str) -> None:
    if _use_simple_ui():
        print(f"\n{title}\n{text}")
        return
    message_dialog(title=title, text=text).run()


def pick_profile(profiles, groups, include_vpn: bool = True):
    """Return a ``("profile"|"group", id)`` selection, or None."""
    values = []
    for group in groups:
        values.append((("group", group.id), f"[GROUP] {group.name}"))
    for profile in profiles:
        if not include_vpn and profile.kind in ("openvpn", "openconnect"):
            continue
        values.append((("profile", profile.id), f"{profile.kind:>10}  {profile.name}"))
    return menu("Select config", values)
