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
    try:
        _guide_first_run(store)
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
                return 0
            try:
                if action == "connect":
                    _connect(store, controller)
                elif action == "manage":
                    run_manage(store, controller)
                elif action == "test":
                    run_test(store)
                elif action == "routing":
                    run_routing(store)
                elif action == "settings":
                    run_settings(store, controller)
                store.save()
            except (OSError, ValueError, TypeError) as exc:
                widgets.show_message("Action failed", str(exc))
    except (EOFError, KeyboardInterrupt):
        return 0
    finally:
        controller.disconnect()


def _guide_first_run(store) -> None:
    """Open management immediately so a fresh TTY leads to adding a config."""
    if store.list_profiles() or store.list_groups():
        return
    widgets.show_message("Welcome", "No configs yet. Add a subscription or proxy to get started.")
    try:
        run_manage(store)
    except (OSError, ValueError, TypeError) as exc:
        widgets.show_message("Setup unavailable", str(exc))


def _connect(store, controller) -> None:
    profiles = store.list_profiles()
    groups = store.list_groups()
    subscriptions = store.list_subscriptions()
    if not profiles and not groups and not subscriptions:
        widgets.show_message("No configs", "Add a subscription or proxy first.")
        run_manage(store)
        return
    selection = widgets.pick_profile(profiles, groups, subscriptions)
    if selection is None:
        return
    kind, key = selection
    from ..connector import resolve_ref_entity

    chosen = resolve_ref_entity(store, key)
    if chosen is not None:
        run_connection(store, controller, chosen)
