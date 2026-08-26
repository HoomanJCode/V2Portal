"""Groups screen: render the nested hierarchy tree and create groups."""

from __future__ import annotations

from ..outbounds.groups import group_tree_lines
from . import widgets
from .manage import _create_balancer, _create_chain


def _render_tree(store) -> None:
    lines = group_tree_lines(store)
    if not lines:
        widgets.show_message("No groups", "Add a group, subscription, or server first.")
        return
    from rich.console import Console
    from rich.panel import Panel

    Console().print(
        Panel("\n".join(lines), title="Groups", border_style="green", padding=(0, 1))
    )


def run(store) -> None:
    while True:
        _render_tree(store)
        action = widgets.menu(
            "Groups",
            [
                ("balancer", "Create balancer"),
                ("chain", "Create chain"),
                ("manage", "Manage groups (edit / remove / members)"),
                ("back", "Back"),
            ],
        )
        if action is None or action == "back":
            return
        if action == "balancer":
            _create_balancer(store)
        elif action == "chain":
            _create_chain(store)
        elif action == "manage":
            from .manage import _groups

            _groups(store)
