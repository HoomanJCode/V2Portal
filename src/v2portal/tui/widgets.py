"""Prompt-toolkit wrappers used by the TUI screens.

Every interactive helper is a numbered, rich-styled prompt. Rendering
menus as rich panels keeps the TUI looking consistent on any terminal
size (full-screen dialogs do not fit small Termux windows) and gives
every screen the same modern look.
"""

from __future__ import annotations

from prompt_toolkit import PromptSession

from ..outbounds.vpn import VPN_KINDS, detect_clients


def _console():
    from rich.console import Console

    return Console()


def _prompt(text: str, default: str = "", *, password: bool = False) -> str:
    try:
        return PromptSession().prompt(text, default=default, is_password=password)
    except (EOFError, KeyboardInterrupt):
        return default


def panel(title: str, text: str = "", *, accent: str = "blue") -> None:
    """Print a rich banner for a screen or menu."""
    from rich.panel import Panel

    body = f"[bold]{title}[/bold]"
    if text:
        body += f"\n[dim]{text}[/dim]"
    _console().print(Panel(body, border_style=accent, padding=(0, 1)))


def _render_options(title: str, values: list, text: str = "") -> None:
    panel(title, text)
    for index, (_, label) in enumerate(values, 1):
        _console().print(f"  [cyan]{index})[/cyan] {label}")


def menu(title: str, values, text: str = ""):
    """Single-select from ``values=[(value, label)]``; returns value or None."""
    values = list(values)
    if not values:
        return None
    _render_options(title, values, text)
    for _attempt in range(3):
        raw = _prompt("Select: ").strip()
        try:
            index = int(raw)
        except ValueError:
            if not raw:
                return None
            print("  Invalid selection, try again.")
            continue
        if 1 <= index <= len(values):
            return values[index - 1][0]
        print(f"  Number must be 1-{len(values)}.")
    return None


def multi_select(title: str, values, text: str = ""):
    """Multi-select from ``values=[(value, label)]``; returns list or None."""
    values = list(values)
    if not values:
        return []
    _render_options(title, values, text)
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


def confirm(question: str) -> bool:
    return _prompt(f"{question} [y/N]: ").strip().lower() in {"y", "yes"}


def input_text(prompt_text: str, default: str = "") -> str:
    return _prompt(f"{prompt_text}: ", default=default)


def input_int(prompt_text: str, default=None):
    raw = _prompt(f"{prompt_text}: ", default="" if default is None else str(default))
    if raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        show_message("Invalid number", f"{prompt_text} must be a whole number.")
        return default


def input_secret(prompt_text: str) -> str:
    return _prompt(f"{prompt_text}: ", password=True)


def show_message(title: str, text: str) -> None:
    panel(title, text)


def pick_profile(profiles, groups, subscriptions=(), servers=(), include_vpn: bool = True):
    """Return a (\"profile\"|\"subscription\"|\"group\"|\"server\", id), or None."""
    values = []
    clients = detect_clients()
    for sub in subscriptions:
        values.append((("subscription", sub.id), f"[SUB] {sub.name}"))
    for group in groups:
        values.append((("group", group.id), f"[GROUP] {group.name}"))
    for server in servers:
        values.append((("server", server.id), f"[SERVER] {server.name} :{server.port}"))
    for profile in profiles:
        if not include_vpn and profile.kind in VPN_KINDS:
            continue
        label = f"{profile.kind:>10}  {profile.name}"
        if profile.kind in VPN_KINDS and not clients.get(profile.kind):
            label += "  [client missing]"
        values.append((("profile", profile.id), label))
    return menu("Select config", values)
