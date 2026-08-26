"""Live connection status screen."""

from __future__ import annotations

from prompt_toolkit import PromptSession

from . import widgets


def run(store, controller, selection) -> None:
    status = controller.connect(selection)
    if status.state != "connected":
        widgets.show_message("Connection failed", status.error or "unknown error")
        return

    _render(status, _read_traffic(controller))
    session = PromptSession()
    try:
        while True:
            command = session.prompt("s=switch  d=disconnect  r=refresh  t=test  q=back > ").strip().lower()
            if command == "q":
                break
            if command == "d":
                controller.disconnect()
                break
            if command == "s":
                from ..outbounds.groups import resolve_ref_entity

                selection = widgets.pick_profile(
                    store.list_profiles(), store.list_groups(), store.list_subscriptions()
                )
                if selection is None:
                    continue
                _, key = selection
                chosen = resolve_ref_entity(store, key)
                if chosen is None:
                    continue
                status = controller.switch(chosen)
                if status.state != "connected":
                    widgets.show_message("Switch failed", status.error or "unknown error")
                    break
                _render(status, _read_traffic(controller))
                continue
            if command == "t":
                from .test_screen import run as run_test

                run_test(store)
            if command == "r":
                status = controller.status
            _render(status, _read_traffic(controller))
    except (EOFError, KeyboardInterrupt):
        controller.disconnect()


def _read_traffic(controller) -> dict | None:
    """Read best-effort live traffic without coupling the screen to a controller mock."""
    reader = getattr(controller, "traffic", None)
    return reader() if reader is not None else None


def _render(status, traffic: dict | None = None) -> None:
    from rich.console import Console
    from rich.table import Table

    from ..subs.health import human_bytes

    console = Console()
    table = Table(title="Connected", show_header=False)
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Target", status.target_name)
    table.add_row("Engine", status.engine)
    table.add_row("PID", str(status.pid or ""))
    if traffic is not None:
        table.add_row(
            "Traffic",
            f"up {human_bytes(traffic.get('up', 0))} / down {human_bytes(traffic.get('down', 0))}",
        )
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
