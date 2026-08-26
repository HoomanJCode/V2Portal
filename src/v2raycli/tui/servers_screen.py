"""Server dashboard: live status table and start/stop control."""

from __future__ import annotations

from ..servers import ServerManager
from . import widgets


def _outbound_hint(store, server) -> str:
    if server.outbound_type == "direct" or not server.outbound_id:
        return "direct"
    if server.outbound_type == "profile":
        item = store.get_profile(server.outbound_id)
    elif server.outbound_type == "group":
        item = store.get_group(server.outbound_id)
    elif server.outbound_type == "subscription":
        item = store.get_subscription(server.outbound_id)
    elif server.outbound_type == "server":
        item = store.get_server(server.outbound_id)
    else:
        item = None
    return item.name if item is not None else server.outbound_id


def _server_rows(store, mgr) -> list[dict]:
    rows = []
    for server in store.list_servers():
        state = mgr.get_state(server.id)
        running = state.is_running() if state else False
        rows.append({
            "id": server.id,
            "name": server.name,
            "port": server.port,
            "protocol": server.protocol,
            "running": running,
            "enabled": server.enabled,
            "outbound": _outbound_hint(store, server),
        })
    return rows


def _render(store, mgr) -> None:
    from rich.console import Console
    from rich.table import Table

    rows = _server_rows(store, mgr)
    table = Table(title="Servers", border_style="dim")
    table.add_column("ID", style="dim")
    table.add_column("Port", justify="right")
    table.add_column("Protocol")
    table.add_column("Status")
    table.add_column("Outbound")
    table.add_column("Name")
    for row in rows:
        status = "[green]running[/green]" if row["running"] else "[dim]stopped[/dim]"
        if not row["enabled"]:
            status += " [yellow](disabled)[/yellow]"
        table.add_row(
            row["id"], str(row["port"]), row["protocol"],
            status, row["outbound"], row["name"],
        )
    if not rows:
        table.add_row("—", "", "", "", "", "no servers — add one from Manage")
    Console().print(table)


def _pick_server(store, mgr, *, running_only: bool = False):
    servers = store.list_servers()
    if running_only:
        running_ids = set(mgr.list_running())
        servers = [s for s in servers if s.id in running_ids]
    if not servers:
        msg = "No running servers." if running_only else "No servers — add one from Manage."
        widgets.show_message("No servers", msg)
        return None
    return widgets.menu(
        "Pick server",
        [
            (s.id, f"{s.id}  :{s.port}  {s.protocol:<5}  {s.name}")
            for s in servers
        ],
    )


def _start(store, mgr, server_id: str) -> None:
    try:
        state = mgr.start(server_id)
    except ValueError as exc:
        widgets.show_message("Start failed", str(exc))
        return
    if state.error:
        widgets.show_message("Start failed", state.error)
        return
    server = store.get_server(server_id)
    widgets.show_message("Started", f"{server_id} listening on :{server.port}")


def run(store) -> None:
    mgr = ServerManager(store)
    while True:
        _render(store, mgr)
        action = widgets.menu(
            "Servers",
            [
                ("start", "Start a server"),
                ("stop", "Stop a server"),
                ("start_all", "Start all enabled"),
                ("stop_all", "Stop all"),
                ("back", "Back"),
            ],
        )
        if action is None or action == "back":
            return
        if action == "start":
            server_id = _pick_server(store, mgr)
            if server_id:
                _start(store, mgr, server_id)
        elif action == "stop":
            server_id = _pick_server(store, mgr, running_only=True)
            if server_id:
                mgr.stop(server_id)
        elif action == "start_all":
            failed = 0
            for server in [s for s in store.list_servers() if s.enabled]:
                try:
                    state = mgr.start(server.id)
                    if state.error:
                        failed += 1
                except ValueError:
                    failed += 1
            widgets.show_message(
                "Start all", "All enabled servers started." if not failed else f"{failed} failed"
            )
        elif action == "stop_all":
            count = mgr.stop_all()
            widgets.show_message("Stop all", f"Stopped {count} server(s)")
