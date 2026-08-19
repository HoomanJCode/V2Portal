"""Live connection status screen."""

from __future__ import annotations

from prompt_toolkit import PromptSession

from . import widgets


def run(store, controller, selection) -> None:
    status = controller.connect(selection)
    if status.state != "connected":
        widgets.show_message("Connection failed", status.error or "unknown error")
        return

    _render(status)
    session = PromptSession()
    while True:
        command = session.prompt("s=switch  d=disconnect  t=test  q=back > ").strip().lower()
        if command == "q":
            break
        if command == "d":
            controller.disconnect()
            break
        if command == "s":
            controller.disconnect()
            break
        if command == "t":
            from .test_screen import run as run_test

            run_test(store)
        _render(status)


def _render(status) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    table = Table(title="Connected", show_header=False)
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Target", status.target_name)
    table.add_row("Engine", status.engine)
    table.add_row("PID", str(status.pid or ""))
    inbound = status.inbound
    if inbound:
        table.add_row("Listen", f"{inbound.get('listen')}:{inbound.get('mixed_port')}")
        for url in inbound.get("urls", []):
            table.add_row("URL", url)
        if inbound.get("auth"):
            table.add_row("Auth", f"{inbound['auth']['username']}/***")
        for lan in inbound.get("lan", []):
            table.add_row("LAN", lan)
    console.print(table)
