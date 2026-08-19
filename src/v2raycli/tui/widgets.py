"""Prompt-toolkit dialog wrappers used by the TUI screens."""

from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.shortcuts import (
    checkboxlist_dialog,
    confirm as _confirm,
    input_dialog,
    message_dialog,
    radiolist_dialog,
)


def menu(title: str, values, text: str = ""):
    """Single-select from ``values=[(value, label)]``; returns value or None."""
    return radiolist_dialog(title=title, text=text, values=list(values)).run()


def multi_select(title: str, values, text: str = ""):
    """Multi-select from ``values=[(value, label)]``; returns list or None."""
    return checkboxlist_dialog(title=title, text=text, values=list(values)).run()


def confirm(question: str) -> bool:
    return _confirm(question)


def input_text(prompt: str, default: str = "") -> str:
    value = input_dialog(title="Input", text=prompt).run()
    return value if value is not None else default


def input_int(prompt: str, default=None):
    raw = input_dialog(title="Input", text=prompt).run()
    if raw is None or raw.strip() == "":
        return default
    return int(raw.strip())


def input_secret(prompt: str) -> str:
    return PromptSession().prompt(f"{prompt}: ", is_password=True)


def show_message(title: str, text: str) -> None:
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
    return radiolist_dialog(title="Select config", text="", values=values).run()
