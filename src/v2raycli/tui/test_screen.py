"""Outbound testing screen."""

from __future__ import annotations

from ..test.latency import (
    load_results,
    render_table,
    save_results,
    select_profiles,
    test_many,
)
from . import widgets


def run(store) -> None:
    scope = widgets.menu(
        "Test scope",
        [
            ("all", "All outbounds"),
            ("sub", "One subscription"),
            ("profiles", "Selected profiles"),
            ("last", "View last results"),
            ("back", "Back"),
        ],
    )
    if scope is None or scope == "back":
        return
    if scope == "last":
        results = load_results()
        if not results:
            widgets.show_message("No cached results", "Run an outbound test first.")
            return
        render_table(results)
        return

    if scope == "all":
        profiles = select_profiles(store, "all")
    elif scope == "sub":
        subs = store.list_subscriptions()
        choice = widgets.menu("Subscription", [(s.id, s.name) for s in subs])
        profiles = select_profiles(store, ("subscription", choice)) if choice else []
    else:
        members = widgets.multi_select(
            "Profiles", [(p.id, f"{p.kind:>10}  {p.name}") for p in store.list_profiles()]
        )
        profiles = select_profiles(store, ("profiles", members)) if members else []

    if not profiles:
        widgets.show_message("Nothing to test", "No matching profiles.")
        return

    results = test_many(profiles, store.config.settings, engines=store.config.engines)
    save_results(results)
    render_table(results)
    widgets.show_message("Done", f"Tested {len(results)} outbounds.")
