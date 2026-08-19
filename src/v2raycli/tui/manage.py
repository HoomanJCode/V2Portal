"""Management menus: add/update/remove subscriptions, profiles, and groups."""

from __future__ import annotations

from ..outbounds import manual, vpn
from ..outbounds.groups import create_balancer_group, create_chain_group
from ..subs.parser import import_subscription, update_subscription
from ..subs.share import ShareLinkError, decode_link, encode_link
from . import widgets


def _split(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def run(store) -> None:
    while True:
        action = widgets.menu(
            "Manage",
            [
                ("add", "Add (subscription / link / proxy / VPN)"),
                ("subs", "Subscriptions"),
                ("profiles", "Profiles"),
                ("groups", "Groups"),
                ("transfer", "Backup / Export / Import"),
                ("back", "Back"),
            ],
        )
        if action is None or action == "back":
            return
        if action == "add":
            _add(store)
        elif action == "subs":
            _subscriptions(store)
        elif action == "profiles":
            _profiles(store)
        elif action == "groups":
            _groups(store)
        elif action == "transfer":
            _transfer(store)
        store.save()


# -- add -------------------------------------------------------------------


def _add(store) -> None:
    kind = widgets.menu(
        "Add",
        [
            ("sub", "Subscription URL"),
            ("link", "Paste share link"),
            ("raw", "Paste raw xray/v2ray outbound JSON (xray engine)"),
            ("socks", "SOCKS proxy"),
            ("http", "HTTP proxy"),
            ("wireguard", "WireGuard"),
            ("hysteria2", "Hysteria2"),
            ("tuic", "TUIC"),
            ("openvpn", "OpenVPN (.ovpn)"),
            ("openconnect", "OpenConnect (AnyConnect)"),
        ],
    )
    if kind is None:
        return
    name = widgets.input_text("Name")

    if kind == "sub":
        url = widgets.input_text("Subscription URL")
        try:
            sub, profiles, errors = import_subscription(name, url)
        except Exception as exc:  # FetchError etc.
            widgets.show_message("Import failed", str(exc))
            return
        store.add_subscription(sub)
        for profile in profiles:
            store.add_profile(profile)
        widgets.show_message("Imported", f"Added {len(profiles)} profiles.")
        if errors:
            widgets.show_message("Some links skipped", "\n".join(errors[:10]))
        return

    if kind == "link":
        raw = widgets.input_text("Share link")
        try:
            profile = decode_link(raw)
        except ShareLinkError as exc:
            widgets.show_message("Invalid link", str(exc))
            return
        profile.name = name or profile.name
        store.add_profile(profile)
        return

    if kind == "raw":
        raw = widgets.input_text("Raw outbound JSON")
        try:
            profile = manual.add_manual_config(raw, name, engine="xray")
        except ValueError as exc:
            widgets.show_message("Invalid config", str(exc))
            return
        store.add_profile(profile)
        return

    if kind in ("socks", "http"):
        host = widgets.input_text("Host")
        port = widgets.input_int("Port")
        if port is None:
            return
        user = widgets.input_text("Username (optional)")
        password = widgets.input_secret("Password (optional)") if user else None
        factory = manual.add_socks_proxy if kind == "socks" else manual.add_http_proxy
        store.add_profile(factory(name, host, port, user, password))
        return

    if kind == "wireguard":
        private_key = widgets.input_text("Private key")
        address = _split(widgets.input_text("Addresses (comma separated)"))
        public_key = widgets.input_text("Peer public key")
        endpoint = widgets.input_text("Peer endpoint (host:port)")
        allowed = _split(widgets.input_text("Allowed IPs (comma separated)"))
        peers = [{"publicKey": public_key, "endpoint": endpoint, "allowedIps": allowed}]
        store.add_profile(manual.add_wireguard(name, private_key, address, peers))
        return

    if kind == "hysteria2":
        server = widgets.input_text("Server")
        port = widgets.input_int("Port")
        if port is None:
            return
        password = widgets.input_secret("Password")
        store.add_profile(manual.add_hysteria2(name, server, port, password))
        return

    if kind == "tuic":
        server = widgets.input_text("Server")
        port = widgets.input_int("Port")
        if port is None:
            return
        uuid = widgets.input_text("UUID")
        password = widgets.input_secret("Password")
        store.add_profile(manual.add_tuic(name, server, port, uuid, password))
        return

    if kind == "openvpn":
        path = widgets.input_text(".ovpn config path (empty to paste inline)")
        inline = None if path else widgets.input_text("Paste .ovpn content")
        store.add_profile(vpn.add_openvpn(name, config_path=path or None, inline=inline))
        return

    if kind == "openconnect":
        server = widgets.input_text("Server")
        store.add_profile(vpn.add_openconnect(name, server))


# -- transfer (backup / export / import) ----------------------------------


def _transfer(store) -> None:
    from .. import backup, config, exchange

    action = widgets.menu(
        "Transfer",
        [
            ("backup", "Backup now"),
            ("restore", "Restore from backup"),
            ("export_full", "Export full config"),
            ("export_redacted", "Export full config (redacted)"),
            ("import_full", "Import full config"),
            ("import_links", "Import share-link file"),
            ("export_links", "Export share links"),
            ("back", "Back"),
        ],
    )
    if action is None or action == "back":
        return

    if action == "backup":
        path = backup.create_backup("manual", store=store, keep=store.config.settings.backup_keep)
        widgets.show_message("Backed up", str(path) if path else "No config to back up.")
    elif action == "restore":
        backups = backup.list_backups()
        if not backups:
            widgets.show_message("No backups", "None found.")
            return
        choice = widgets.menu(
            "Restore", [(b.path, f"{b.timestamp}  {b.reason}") for b in backups]
        )
        if choice and widgets.confirm("Restore this backup? Current config is backed up first."):
            try:
                backup.restore_backup(choice, store)
            except Exception as exc:
                widgets.show_message("Restore failed", str(exc))
                return
            widgets.show_message("Restored", "Config restored.")
    elif action == "export_full":
        path = widgets.input_text("Export path", str(config.RUNTIME_DIR / "export.json"))
        exchange.export_full(store, path)
        widgets.show_message("Exported", path)
    elif action == "export_redacted":
        path = widgets.input_text("Export path", str(config.RUNTIME_DIR / "export-redacted.json"))
        exchange.export_full(store, path, redact=True)
        widgets.show_message("Exported", path)
    elif action == "import_full":
        path = widgets.input_text("Import file path")
        mode = widgets.menu("Mode", [("merge", "Merge"), ("replace", "Replace")])
        if not mode:
            return
        try:
            exchange.import_full(store, path, mode=mode)
        except Exception as exc:
            widgets.show_message("Import failed", str(exc))
            return
        widgets.show_message("Imported", "Config imported.")
    elif action == "import_links":
        path = widgets.input_text("Share-link file path")
        added = exchange.import_share_links(store, path)
        widgets.show_message("Imported", f"Added {len(added)} profiles.")
    elif action == "export_links":
        members = widgets.multi_select(
            "Profiles", [(p.id, f"{p.kind:>10}  {p.name}") for p in store.list_profiles()]
        )
        if not members:
            return
        profiles = [p for p in store.list_profiles() if p.id in members]
        path = widgets.input_text("Export path", str(config.RUNTIME_DIR / "links.txt"))
        links = exchange.export_share_links(profiles, path)
        widgets.show_message("Exported", f"Wrote {len(links)} links.")


# -- subscriptions ---------------------------------------------------------


def _subscriptions(store) -> None:
    subs = store.list_subscriptions()
    if not subs:
        widgets.show_message("No subscriptions", "Add one via Manage -> Add.")
        return
    action = widgets.menu(
        "Subscriptions",
        [
            ("update", "Update one"),
            ("update_all", "Update all"),
            ("remove", "Remove"),
            ("back", "Back"),
        ],
    )
    if action == "update":
        choice = widgets.menu("Pick", [(s.id, s.name) for s in subs])
        if choice:
            _do_update(store, choice)
    elif action == "update_all":
        for sub in list(subs):
            _do_update(store, sub.id)
    elif action == "remove":
        choice = widgets.menu("Pick", [(s.id, s.name) for s in subs])
        if choice and widgets.confirm("Remove subscription and its profiles?"):
            for profile in list(store.config.profiles):
                if profile.subscription_id == choice:
                    manual.remove_profile(store, profile.id)
            store.remove_subscription(choice)


def _do_update(store, sub_id: str) -> None:
    try:
        profiles, errors = update_subscription(store, sub_id)
    except Exception as exc:
        widgets.show_message("Update failed", str(exc))
        return
    widgets.show_message("Updated", f"{len(profiles)} profiles.")
    if errors:
        widgets.show_message("Some links skipped", "\n".join(errors[:10]))


# -- profiles --------------------------------------------------------------


def _profiles(store) -> None:
    profiles = store.list_profiles()
    if not profiles:
        widgets.show_message("No profiles", "Add one first.")
        return
    choice = widgets.menu("Profiles", [(p.id, f"{p.kind:>10}  {p.name}") for p in profiles])
    if choice is None:
        return
    profile = store.get_profile(choice)
    action = widgets.menu(
        f"Profile: {profile.name}",
        [("rename", "Rename"), ("export", "Export share link"), ("remove", "Remove"), ("back", "Back")],
    )
    if action == "rename":
        profile.name = widgets.input_text("New name", profile.name)
    elif action == "export":
        try:
            widgets.show_message("Share link", encode_link(profile))
        except ShareLinkError as exc:
            widgets.show_message("Cannot export", str(exc))
    elif action == "remove":
        if widgets.confirm(f"Remove {profile.name}?"):
            manual.remove_profile(store, profile.id)


# -- groups ----------------------------------------------------------------


def _groups(store) -> None:
    action = widgets.menu(
        "Groups",
        [("balancer", "Create balancer"), ("chain", "Create chain"), ("remove", "Remove"), ("back", "Back")],
    )
    if action == "balancer":
        _create_balancer(store)
    elif action == "chain":
        _create_chain(store)
    elif action == "remove":
        groups = store.list_groups()
        choice = widgets.menu("Remove group", [(g.id, g.name) for g in groups])
        if choice:
            store.remove_group(choice)


def _create_balancer(store) -> None:
    name = widgets.input_text("Name")
    strategy = widgets.menu(
        "Strategy",
        [("latency", "latency"), ("random", "random"), ("roundRobin", "roundRobin"), ("leastLoad", "leastLoad")],
    )
    if not strategy:
        return
    members = widgets.multi_select(
        "Members", [(p.id, f"{p.kind:>10}  {p.name}") for p in store.list_profiles()]
    )
    if not members or len(members) < 2:
        widgets.show_message("Need 2+", "Select at least two profiles.")
        return
    try:
        store.add_group(create_balancer_group(name, strategy, members, store))
    except ValueError as exc:
        widgets.show_message("Invalid", str(exc))


def _create_chain(store) -> None:
    name = widgets.input_text("Name")
    members = widgets.multi_select(
        "Hops (in order)", [(p.id, f"{p.kind:>10}  {p.name}") for p in store.list_profiles()]
    )
    if not members or len(members) < 2:
        widgets.show_message("Need 2+", "Select at least two profiles.")
        return
    try:
        store.add_group(create_chain_group(name, members, store))
    except ValueError as exc:
        widgets.show_message("Invalid", str(exc))
