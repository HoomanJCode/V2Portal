"""Main TUI loop: dispatch to connect/manage/test/routing/settings."""

from __future__ import annotations

from ..connection import ConnectionController
from . import widgets
from .connection_screen import run as run_connection
from .manage import run as run_manage
from .routing_screen import run as run_routing
from .settings_screen import run as run_settings
from .test_screen import run as run_test


def run(store) -> int:
    controller = ConnectionController(store)
    while True:
        action = widgets.menu(
            "v2raycli",
            [
                ("connect", "Connect (select config)"),
                ("manage", "Manage (add / update / remove)"),
                ("test", "Test outbounds"),
                ("routing", "Routing rules"),
                ("settings", "Settings"),
                ("quit", "Quit"),
            ],
        )
        if action is None or action == "quit":
            controller.disconnect()
            return 0
        if action == "connect":
            _connect(store, controller)
        elif action == "manage":
            run_manage(store)
        elif action == "test":
            run_test(store)
        elif action == "routing":
            run_routing(store)
        elif action == "settings":
            run_settings(store)
        store.save()


def _connect(store, controller) -> None:
    profiles = store.list_profiles()
    groups = store.list_groups()
    if not profiles and not groups:
        widgets.show_message("No configs", "Add a subscription or proxy first.")
        run_manage(store)
        return
    selection = widgets.pick_profile(profiles, groups)
    if selection is None:
        return
    kind, key = selection
    chosen = store.get_profile(key) if kind == "profile" else store.get_group(key)
    if chosen is not None:
        run_connection(store, controller, chosen)
