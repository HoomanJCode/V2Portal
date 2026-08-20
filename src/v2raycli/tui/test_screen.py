"""Outbound testing screen."""

from __future__ import annotations

from ..test.latency import (
    load_results,
    probe_many,
    render_endpoint_table,
    render_table,
    render_websocket_table,
    save_results,
    select_profiles,
    test_many,
    websocket_test_many,
)
from . import widgets


def _select_profiles(store):
    scope = widgets.menu(
        "Test scope",
        [
            ("all", "All outbounds"),
            ("sub", "One subscription"),
            ("profiles", "Selected profiles"),
            ("back", "Back"),
        ],
    )
    if scope is None or scope == "back":
        return []
    if scope == "all":
        return select_profiles(store, "all")
    if scope == "sub":
        subs = store.list_subscriptions()
        choice = widgets.menu("Subscription", [(s.id, s.name) for s in subs])
        return select_profiles(store, ("subscription", choice)) if choice else []
    members = widgets.multi_select(
        "Profiles", [(p.id, f"{p.kind:>10}  {p.name}") for p in store.list_profiles()]
    )
    return select_profiles(store, ("profiles", members)) if members else []


def run(store) -> None:
    test_type = widgets.menu(
        "Test type",
        [
            ("delay", "Full proxy request delay"),
            ("probe", "ICMP/TCP endpoint reachability"),
            ("ws", "WebSocket handshake and payload"),
            ("last", "View last delay results"),
            ("back", "Back"),
        ],
    )
    if test_type is None or test_type == "back":
        return
    if test_type == "last":
        results = load_results()
        if not results:
            widgets.show_message("No cached results", "Run a full proxy delay test first.")
            return
        render_table(results)
        return

    profiles = _select_profiles(store)
    if not profiles:
        widgets.show_message("Nothing to test", "No matching profiles.")
        return

    if test_type == "probe":
        results = probe_many(profiles)
        render_endpoint_table(results)
        widgets.show_message("Done", f"Probed {len(results)} endpoints.")
        return
    if test_type == "ws":
        results = websocket_test_many(
            profiles, store.config.settings, engines=store.config.engines
        )
        render_websocket_table(results)
        widgets.show_message("Done", f"Tested {len(results)} WebSocket profiles.")
        return

    results = test_many(profiles, store.config.settings, engines=store.config.engines)
    save_results(results)
    render_table(results)
    widgets.show_message("Done", f"Tested {len(results)} outbounds.")
