"""Connect by any reference (profile | subscription | group | server).

One code path is shared by the CLI ``connect`` command, the TUI connect
screen, and the boot service. Type auto-detection relies on the globally
unique ID space; resolution goes through the universal resolver so
subscriptions refresh dynamically, nested groups expand, and a server
reference becomes a socks/http hop through that server's local inbound.
"""

from __future__ import annotations

from .outbounds.groups import classify_id


def resolve_ref_entity(store, ref: str):
    """Return the Profile / Subscription / Group / Server for ``ref``.

    Raises ValueError for unknown ids.
    """
    if not isinstance(ref, str) or not ref:
        raise ValueError("ref must be a non-empty id string")
    kind = classify_id(store, ref)
    if kind == "profile":
        return store.get_profile(ref)
    if kind == "subscription":
        return store.get_subscription(ref)
    if kind == "group":
        return store.get_group(ref)
    if kind == "server":
        return store.get_server(ref)
    raise ValueError(
        f"unknown id: {ref} (not a profile, subscription, group, or server)"
    )


def connect_ref(store, ref: str, controller) -> object:
    """Resolve *ref* to its entity and connect through *controller*.

    Returns the ConnectionStatus produced by the controller.
    """
    entity = resolve_ref_entity(store, ref)
    return controller.connect(entity)