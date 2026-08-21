"""Entry point for the v2raycli command."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__
from . import backup, config
from .storage import ConfigStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="v2raycli",
        description="Interactive v2ray CLI client (sing-box + xray-core).",
    )
    parser.add_argument("--version", action="store_true", help="print version and exit")
    parser.add_argument(
        "--config-dir", metavar="PATH", help="use an alternate config directory"
    )
    parser.add_argument(
        "--headless", action="store_true", help="print a summary and exit (no TUI)"
    )
    parser.add_argument(
        "--connect",
        metavar="ID",
        help="connect to a profile/group id and keep running until Ctrl+C",
    )
    parser.add_argument(
        "--test",
        metavar="SCOPE",
        help="latency-test outbounds and exit: 'all', a subscription id, or comma-separated profile ids",
    )
    parser.add_argument(
        "--probe",
        metavar="SCOPE",
        help="probe remote endpoints with ICMP/TCP and exit using the same scope syntax as --test",
    )
    parser.add_argument(
        "--ws-test",
        metavar="SCOPE",
        help="test WS/WSS handshake and ping/pong using the same scope syntax as --test",
    )
    parser.add_argument(
        "--update",
        choices=("sing-box", "xray", "both"),
        metavar="ENGINE",
        help="explicitly update sing-box, xray, or both; custom paths are protected",
    )
    parser.add_argument(
        "--proxy",
        metavar="URL",
        help="ephemeral HTTP/SOCKS proxy for explicit engine updates (not stored)",
    )
    parser.add_argument("--backup", action="store_true", help="create a config backup and exit")
    parser.add_argument("--list-backups", action="store_true", help="list config backups and exit")
    parser.add_argument("--restore", metavar="PATH", help="restore a config backup")
    parser.add_argument("--export", metavar="PATH", help="export the full config to a file")
    parser.add_argument(
        "--redact", action="store_true", help="mask credentials/keys when used with --export"
    )
    parser.add_argument(
        "--import", dest="import_path", metavar="PATH", help="import a full config export"
    )
    parser.add_argument(
        "--replace", action="store_true", help="replace (not merge) when used with --import"
    )
    parser.add_argument(
        "--no-auto-update",
        action="store_true",
        help="skip auto-updating stale subscriptions on startup",
    )
    parser.add_argument(
        "--install-service",
        metavar="ID",
        help="install a service that connects to ID on boot (systemd/Termux)",
    )
    parser.add_argument(
        "--uninstall-service", action="store_true", help="remove the installed service"
    )
    parser.add_argument(
        "--health", action="store_true", help="print subscription expiry/traffic and exit"
    )
    _add_command_parser(parser)
    return parser


def _add_command_parser(parser: argparse.ArgumentParser) -> None:
    """Add the explicit, script-friendly command tree.

    The legacy flags above remain supported so existing automation does not
    break, while new usage reads naturally as ``resource action``.
    """
    commands = parser.add_subparsers(dest="command", title="commands", metavar="COMMAND")

    status = commands.add_parser("status", help="show a concise config summary")
    status.add_argument("--json", action="store_true", help="emit JSON")

    connect = commands.add_parser("connect", help="connect to a profile or group")
    connect.add_argument("id", metavar="ID")

    health = commands.add_parser("health", help="show subscription health")
    health.add_argument("--json", action="store_true", help="emit JSON")

    profile = commands.add_parser("profile", aliases=["profiles"], help="manage proxy profiles")
    profile_commands = profile.add_subparsers(dest="profile_command", metavar="ACTION")
    profile_list = profile_commands.add_parser("list", help="list profiles")
    profile_list.add_argument("--json", action="store_true", help="emit JSON")
    profile_list.add_argument("--subscription", metavar="ID", help="show only profiles from a subscription")
    profile_list.add_argument("--kind", help="show only profiles of this protocol kind")
    profile_add = profile_commands.add_parser("add", help="add a profile")
    profile_add_commands = profile_add.add_subparsers(dest="profile_add_command", metavar="TYPE")
    share = profile_add_commands.add_parser("share", help="add a v2ray share link")
    share.add_argument("name")
    share.add_argument("link")
    raw = profile_add_commands.add_parser("raw", help="add a raw xray outbound JSON object or file")
    raw.add_argument("name")
    raw.add_argument("source", metavar="JSON_OR_PATH")
    for kind in ("socks", "http"):
        plain = profile_add_commands.add_parser(kind, help=f"add a {kind.upper()} proxy")
        plain.add_argument("name")
        plain.add_argument("host")
        plain.add_argument("port", type=int)
        plain.add_argument("--username")
        plain.add_argument("--password")
    wg = profile_add_commands.add_parser("wireguard", help="add a WireGuard profile")
    wg.add_argument("name")
    wg.add_argument("--private-key", required=True)
    wg.add_argument("--address", action="append", required=True)
    wg.add_argument("--peer-public-key", required=True)
    wg.add_argument("--peer-endpoint", required=True)
    wg.add_argument("--allowed-ip", action="append", required=True)
    h2 = profile_add_commands.add_parser("hysteria2", help="add a Hysteria2 profile")
    h2.add_argument("name")
    h2.add_argument("server")
    h2.add_argument("port", type=int)
    h2.add_argument("password")
    h2.add_argument("--sni")
    h2.add_argument("--insecure", action="store_true")
    tuic = profile_add_commands.add_parser("tuic", help="add a TUIC profile")
    tuic.add_argument("name")
    tuic.add_argument("server")
    tuic.add_argument("port", type=int)
    tuic.add_argument("uuid")
    tuic.add_argument("password")
    tuic.add_argument("--sni")
    tuic.add_argument("--alpn")
    openvpn = profile_add_commands.add_parser("openvpn", help="add an OpenVPN profile")
    openvpn.add_argument("name")
    openvpn.add_argument("--config-path")
    openvpn.add_argument("--inline")
    openconnect = profile_add_commands.add_parser("openconnect", help="add an OpenConnect profile")
    openconnect.add_argument("name")
    openconnect.add_argument("server")
    profile_remove = profile_commands.add_parser("remove", help="remove a profile")
    profile_remove.add_argument("id")
    profile_rename = profile_commands.add_parser("rename", help="rename a profile")
    profile_rename.add_argument("id")
    profile_rename.add_argument("name")
    profile_export = profile_commands.add_parser("export", help="export a profile share link")
    profile_export.add_argument("id")

    subscription = commands.add_parser(
        "subscription", aliases=["subscriptions"], help="manage subscriptions"
    )
    subscription_commands = subscription.add_subparsers(dest="subscription_command", metavar="ACTION")
    subscription_list = subscription_commands.add_parser("list", help="list subscriptions")
    subscription_list.add_argument("--json", action="store_true", help="emit JSON")
    subscription_add = subscription_commands.add_parser("add", help="fetch and add a subscription")
    subscription_add.add_argument("name")
    subscription_add.add_argument("url")
    subscription_add.add_argument("--user-agent")
    subscription_add.add_argument("--proxy")
    subscription_update = subscription_commands.add_parser("update", help="refresh a subscription")
    subscription_update.add_argument("id", nargs="?")
    subscription_update.add_argument("--all", action="store_true", dest="update_all")
    subscription_update.add_argument("--proxy")
    subscription_remove = subscription_commands.add_parser("remove", help="remove a subscription and its profiles")
    subscription_remove.add_argument("id")

    group = commands.add_parser("group", aliases=["groups"], help="manage profile groups")
    group_commands = group.add_subparsers(dest="group_command", metavar="ACTION")
    group_list = group_commands.add_parser("list", help="list groups")
    group_list.add_argument("--json", action="store_true", help="emit JSON")
    group_create = group_commands.add_parser("create", help="create a group")
    group_create_commands = group_create.add_subparsers(dest="group_create_command", metavar="TYPE")
    balancer = group_create_commands.add_parser("balancer", help="create a balanced group")
    balancer.add_argument("name")
    balancer.add_argument("profile_ids", nargs="+")
    balancer.add_argument("--strategy", choices=("latency", "random", "roundRobin", "leastLoad"), default="latency")
    balancer.add_argument("--engine", choices=("auto", "sing-box", "xray"), default="auto")
    chain = group_create_commands.add_parser("chain", help="create a proxy chain")
    chain.add_argument("name")
    chain.add_argument("profile_ids", nargs="+")
    chain.add_argument("--engine", choices=("auto", "sing-box", "xray"), default="auto")
    group_remove = group_commands.add_parser("remove", help="remove a group")
    group_remove.add_argument("id")

    test = commands.add_parser("test", help="test proxy outbounds")
    test_commands = test.add_subparsers(dest="test_command", metavar="TYPE")
    latency = test_commands.add_parser("latency", aliases=["request"], help="test real proxy request delay")
    latency.add_argument("scope", nargs="?", default="all")
    endpoint = test_commands.add_parser("endpoint", aliases=["probe"], help="probe endpoint reachability")
    endpoint.add_argument("scope", nargs="?", default="all")
    websocket = test_commands.add_parser("websocket", aliases=["ws"], help="test WebSocket handshake/payload")
    websocket.add_argument("scope", nargs="?", default="all")

    backup_command = commands.add_parser("backup", help="manage config backups")
    backup_commands = backup_command.add_subparsers(dest="backup_command", metavar="ACTION")
    backup_commands.add_parser("create", help="create a backup")
    backup_commands.add_parser("list", help="list backups")
    restore = backup_commands.add_parser("restore", help="restore a backup")
    restore.add_argument("path")

    config_command = commands.add_parser("config", help="inspect or transfer config")
    config_commands = config_command.add_subparsers(dest="config_command", metavar="ACTION")
    config_show = config_commands.add_parser("show", help="print the complete config as JSON")
    config_show.add_argument("--redact", action="store_true")
    config_export = config_commands.add_parser("export", help="export the complete config")
    config_export.add_argument("path")
    config_export.add_argument("--redact", action="store_true")
    config_import = config_commands.add_parser("import", help="import a complete config")
    config_import.add_argument("path")
    config_import.add_argument("--replace", action="store_true")
    config_set = config_commands.add_parser("set", help="set a supported setting")
    config_set.add_argument("key", choices=("settings.listen", "settings.mixed_port", "settings.allow_lan", "settings.default_engine", "settings.test_url", "settings.subscription_proxy"))
    config_set.add_argument("value")

    engine = commands.add_parser("engine", help="manage engine binaries")
    engine_commands = engine.add_subparsers(dest="engine_command", metavar="ACTION")
    engine_update = engine_commands.add_parser("update", help="explicitly update engine binaries")
    engine_update.add_argument("engine", choices=("sing-box", "xray", "both"))
    engine_update.add_argument("--proxy")

    service_command = commands.add_parser("service", help="manage boot services")
    service_commands = service_command.add_subparsers(dest="service_command", metavar="ACTION")
    service_install = service_commands.add_parser("install", help="install a boot service")
    service_install.add_argument("id")
    service_uninstall = service_commands.add_parser("uninstall", help="remove the boot service")

    routing = commands.add_parser("routing", help="manage split-routing")
    routing_commands = routing.add_subparsers(dest="routing_command", metavar="ACTION")
    routing_list = routing_commands.add_parser("list", help="list routing rules")
    routing_list.add_argument("--json", action="store_true")
    routing_mode = routing_commands.add_parser("mode", help="set routing mode")
    routing_mode.add_argument("mode", choices=("all", "split"))
    routing_add = routing_commands.add_parser("add", help="add a routing rule")
    routing_add.add_argument("action", choices=("proxy", "direct", "block"))
    routing_add.add_argument("--target")
    routing_add.add_argument("--domain", action="append", default=[])
    routing_add.add_argument("--ip", action="append", default=[])
    routing_add.add_argument("--geoip", action="append", default=[])
    routing_add.add_argument("--geosite", action="append", default=[])
    routing_remove = routing_commands.add_parser("remove", help="remove a routing rule")
    routing_remove.add_argument("id")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.config_dir:
        config.set_config_dir(args.config_dir)

    if args.version:
        print(f"v2raycli v{__version__}")
        return 0

    config.ensure_dirs()
    backup.set_private_permissions()
    store = ConfigStore()
    try:
        store.load()
    except (OSError, ValueError) as exc:
        print(f"config load failed: {exc}", file=sys.stderr)
        return 1
    backup.install_backup_hook(store)

    if args.install_service:
        return _install_service(store, args.install_service, args.config_dir)
    if args.uninstall_service:
        return _uninstall_service()
    if args.health:
        return _health(store)

    if args.command == "health":
        return _command(store, args)
    if args.command:
        if not args.no_auto_update:
            _auto_update(store)
            _health_check(store)
        return _command(store, args)

    if not args.no_auto_update:
        _auto_update(store)
        _health_check(store)

    if args.connect:
        return _connect(store, args.connect)

    if args.test:
        return _test(store, args.test)

    if args.probe:
        return _probe(store, args.probe)

    if args.ws_test:
        return _ws_test(store, args.ws_test)

    if args.update:
        return _update(store, args.update, args.proxy)

    if args.backup:
        return _backup(store)
    if args.list_backups:
        return _list_backups()
    if args.restore:
        return _restore(store, args.restore)
    if args.export:
        return _export(store, args.export, args.redact)
    if args.import_path:
        return _import(store, args.import_path, args.replace)

    # The CLI is deliberately non-interactive. The TUI modules remain
    # available to downstream users, but stdin is never read implicitly.
    return _summary(store)


def _command(store: ConfigStore, args) -> int:
    """Dispatch the explicit command tree without prompting for input."""
    command = args.command
    try:
        if command == "status":
            return _status(store, args.json)
        if command == "connect":
            return _connect(store, args.id)
        if command in ("profile", "profiles"):
            return _profile_command(store, args)
        if command in ("subscription", "subscriptions"):
            return _subscription_command(store, args)
        if command in ("group", "groups"):
            return _group_command(store, args)
        if command == "test":
            scope = args.scope
            if args.test_command in ("latency", "request"):
                return _test(store, scope)
            if args.test_command in ("endpoint", "probe"):
                return _probe(store, scope)
            if args.test_command in ("websocket", "ws"):
                return _ws_test(store, scope)
            return _command_help(args, "test")
        if command == "backup":
            if args.backup_command == "create":
                return _backup(store)
            if args.backup_command == "list":
                return _list_backups()
            if args.backup_command == "restore":
                return _restore(store, args.path)
            return _command_help(args, "backup")
        if command == "config":
            return _config_command(store, args)
        if command == "engine":
            if args.engine_command != "update":
                return _command_help(args, "engine")
            return _update(store, args.engine, args.proxy)
        if command == "service":
            if args.service_command == "install":
                return _install_service(store, args.id, getattr(args, "config_dir", None))
            if args.service_command == "uninstall":
                return _uninstall_service()
            return _command_help(args, "service")
        if command == "routing":
            return _routing_command(store, args)
        if command == "health":
            return _health_command(store, args.json)
        if command == "status":
            return _status(store, args.json)
        return _command_help(args)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _command_help(args, command: str | None = None) -> int:
    """Return a useful exit code for an incomplete command."""
    parser = build_parser()
    if command:
        # argparse's nested parser objects are intentionally not exposed; the
        # top-level help is still more useful than a traceback in scripts.
        print(f"usage: v2raycli {command} ACTION", file=sys.stderr)
    else:
        parser.print_help()
    return 2


def _status(store: ConfigStore, as_json: bool = False) -> int:
    conf = store.config
    data = {
        "version": __version__,
        "config": str(store.path),
        "profiles": len(conf.profiles),
        "subscriptions": len(conf.subscriptions),
        "groups": len(conf.groups),
        "routing_mode": conf.routing.mode,
    }
    if as_json:
        print(json.dumps(data, ensure_ascii=False))
    else:
        _summary(store)
    return 0


def _profile_command(store: ConfigStore, args) -> int:
    action = args.profile_command
    if action == "list":
        profiles = store.list_profiles()
        if getattr(args, "subscription", None):
            profiles = [p for p in profiles if p.subscription_id == args.subscription]
        if getattr(args, "kind", None):
            profiles = [p for p in profiles if p.kind == args.kind]
        rows = [
            {"id": p.id, "name": p.name, "kind": p.kind, "engine": p.engine, "source": p.source, "subscription_id": p.subscription_id}
            for p in profiles
        ]
        if args.json:
            print(json.dumps(rows, ensure_ascii=False))
        else:
            if rows:
                for row in rows:
                    sub = f"  sub={row['subscription_id']}" if row["subscription_id"] else ""
                    print(f"{row['id']}  {row['kind']:<11} {row['engine']:<8} {row['name']}{sub}")
            else:
                print("no profiles")
        return 0
    if action == "add":
        return _profile_add_command(store, args)
    if action == "remove":
        from .outbounds.manual import remove_profile

        if not remove_profile(store, args.id):
            print(f"unknown profile id: {args.id}", file=sys.stderr)
            return 1
        store.save()
        print(f"removed profile {args.id}")
        return 0
    if action == "rename":
        from .outbounds.manual import edit_profile

        edit_profile(store, args.id, name=args.name)
        store.save()
        print(f"renamed profile {args.id} -> {args.name}")
        return 0
    if action == "export":
        profile = store.get_profile(args.id)
        if profile is None:
            print(f"unknown profile id: {args.id}", file=sys.stderr)
            return 1
        from .subs.share import ShareLinkError, encode_link

        try:
            print(encode_link(profile))
        except ShareLinkError as exc:
            print(f"cannot export profile: {exc}", file=sys.stderr)
            return 1
        return 0
    return _command_help(args, "profile")


def _profile_add_command(store: ConfigStore, args) -> int:
    from .outbounds import manual, vpn
    from .subs.share import ShareLinkError, decode_link

    kind = args.profile_add_command
    if kind == "share":
        try:
            profile = decode_link(args.link)
        except ShareLinkError as exc:
            print(f"invalid share link: {exc}", file=sys.stderr)
            return 1
        profile.name = args.name or profile.name
    elif kind == "raw":
        try:
            source = Path(args.source)
            raw = source.read_text(encoding="utf-8") if source.is_file() else args.source
        except (OSError, ValueError):
            raw = args.source
        profile = manual.add_manual_config(raw, args.name, engine="xray")
    elif kind in ("socks", "http"):
        factory = manual.add_socks_proxy if kind == "socks" else manual.add_http_proxy
        profile = factory(args.name, args.host, args.port, args.username, args.password)
    elif kind == "wireguard":
        peer = {
            "publicKey": args.peer_public_key,
            "endpoint": args.peer_endpoint,
            "allowedIps": args.allowed_ip,
        }
        profile = manual.add_wireguard(args.name, args.private_key, args.address, [peer])
    elif kind == "hysteria2":
        profile = manual.add_hysteria2(
            args.name, args.server, args.port, args.password, sni=args.sni, insecure=args.insecure
        )
    elif kind == "tuic":
        profile = manual.add_tuic(
            args.name, args.server, args.port, args.uuid, args.password, sni=args.sni, alpn=args.alpn
        )
    elif kind == "openvpn":
        profile = vpn.add_openvpn(args.name, config_path=args.config_path, inline=args.inline)
    elif kind == "openconnect":
        profile = vpn.add_openconnect(args.name, args.server)
    else:
        return _command_help(args, "profile add")

    store.add_profile(profile)
    store.save()
    print(profile.id)
    return 0


def _subscription_command(store: ConfigStore, args) -> int:
    action = args.subscription_command
    if action == "list":
        statuses = []
        for sub in store.list_subscriptions():
            statuses.append(
                {"id": sub.id, "name": sub.name, "profiles": len(sub.profile_ids), "url": sub.url}
            )
        if args.json:
            print(json.dumps(statuses, ensure_ascii=False))
        elif statuses:
            for row in statuses:
                print(f"{row['id']}  {row['profiles']:>3} profiles  {row['name']}  {row['url']}")
        else:
            print("no subscriptions")
        return 0
    if action == "add":
        from .subs.parser import import_subscription

        sub, profiles, errors = import_subscription(
            args.name, args.url, user_agent=args.user_agent, proxy=args.proxy
        )
        store.add_subscription(sub)
        for profile in profiles:
            store.add_profile(profile)
        store.save()
        print(f"{sub.id}  imported {len(profiles)} profiles")
        for error in errors:
            print(f"warning: {error}", file=sys.stderr)
        return 0
    if action == "update":
        from .subs.parser import update_subscription

        if args.update_all:
            if args.id:
                print("use either ID or --all, not both", file=sys.stderr)
                return 2
            targets = [sub.id for sub in store.list_subscriptions()]
        elif args.id:
            targets = [args.id]
        else:
            print("subscription update requires ID or --all", file=sys.stderr)
            return 2
        failed = False
        for sub_id in targets:
            try:
                profiles, errors = update_subscription(store, sub_id, proxy=args.proxy)
                print(f"{sub_id}  updated {len(profiles)} profiles")
                for error in errors:
                    print(f"warning: {error}", file=sys.stderr)
            except (OSError, ValueError) as exc:
                failed = True
                print(f"{sub_id}  update failed: {exc}", file=sys.stderr)
        store.save()
        return 1 if failed else 0
    if action == "remove":
        sub = store.get_subscription(args.id)
        if sub is None:
            print(f"unknown subscription id: {args.id}", file=sys.stderr)
            return 1
        for profile in list(store.config.profiles):
            if profile.subscription_id == args.id:
                store.remove_profile(profile.id)
        store.remove_subscription(args.id)
        store.save()
        print(f"removed subscription {args.id}")
        return 0
    return _command_help(args, "subscription")


def _group_command(store: ConfigStore, args) -> int:
    action = args.group_command
    if action == "list":
        rows = [
            {"id": g.id, "name": g.name, "type": g.type, "strategy": g.strategy, "profiles": len(g.profile_ids)}
            for g in store.list_groups()
        ]
        if args.json:
            print(json.dumps(rows, ensure_ascii=False))
        elif rows:
            for row in rows:
                print(f"{row['id']}  {row['type']:<8} {row['strategy']:<10} {row['profiles']:>2} profiles  {row['name']}")
        else:
            print("no groups")
        return 0
    if action == "create":
        from .outbounds.groups import create_balancer_group, create_chain_group

        if args.group_create_command == "balancer":
            group = create_balancer_group(
                args.name, args.strategy, args.profile_ids, store, engine=args.engine
            )
        elif args.group_create_command == "chain":
            group = create_chain_group(args.name, args.profile_ids, store, engine=args.engine)
        else:
            return _command_help(args, "group create")
        store.add_group(group)
        store.save()
        print(group.id)
        return 0
    if action == "remove":
        if not store.remove_group(args.id):
            print(f"unknown group id: {args.id}", file=sys.stderr)
            return 1
        store.save()
        print(f"removed group {args.id}")
        return 0
    return _command_help(args, "group")


def _config_command(store: ConfigStore, args) -> int:
    action = args.config_command
    if action == "show":
        from .exchange import export_full

        print(json.dumps(export_full(store, redact=args.redact), ensure_ascii=False, indent=2))
        return 0
    if action == "export":
        return _export(store, args.path, args.redact)
    if action == "import":
        return _import(store, args.path, args.replace)
    if action == "set":
        value: object
        try:
            value = json.loads(args.value)
        except json.JSONDecodeError:
            value = args.value
        key = args.key.split(".", 1)[1]
        if key == "mixed_port" and (isinstance(value, bool) or not isinstance(value, int)):
            raise ValueError("settings.mixed_port must be an integer")
        if key == "allow_lan" and not isinstance(value, bool):
            raise ValueError("settings.allow_lan must be boolean (use true or false)")
        if key == "default_engine" and value not in ("sing-box", "xray"):
            raise ValueError("settings.default_engine must be sing-box or xray")
        setattr(store.config.settings, key, value)
        store.save()
        print(f"{args.key}={json.dumps(value, ensure_ascii=False)}")
        return 0
    return _command_help(args, "config")


def _routing_command(store: ConfigStore, args) -> int:
    from .routing.rules import add_rule

    action = args.routing_command
    if action == "list":
        rows = [rule.to_dict() for rule in store.config.routing.rules]
        if args.json:
            print(json.dumps(rows, ensure_ascii=False))
        else:
            print(f"mode={store.config.routing.mode}")
            for row in rows:
                target = row["target_id"] or "selected"
                match = row["match"]
                values = ", ".join(
                    f"{key}={','.join(value)}" for key, value in match.items() if value
                )
                print(f"{row['id']}  {row['action']:<6} {target:<36} {values}")
        return 0
    if action == "mode":
        store.config.routing.mode = args.mode
        store.save()
        print(f"routing mode={args.mode}")
        return 0
    if action == "add":
        rule = add_rule(
            args.action,
            {
                "domains": args.domain,
                "ips": args.ip,
                "geoip": args.geoip,
                "geosite": args.geosite,
            },
            target_id=args.target,
        )
        store.add_rule(rule)
        store.config.routing.mode = "split"
        store.save()
        print(rule.id)
        return 0
    if action == "remove":
        if not store.remove_rule(args.id):
            print(f"unknown rule id: {args.id}", file=sys.stderr)
            return 1
        store.save()
        print(f"removed rule {args.id}")
        return 0
    return _command_help(args, "routing")


def _health_command(store: ConfigStore, as_json: bool = False) -> int:
    from .subs.health import check_subscriptions, human_bytes

    statuses = check_subscriptions(store)
    if as_json:
        print(json.dumps([
            {
                "name": status["name"],
                "expired": status["expired"],
                "expiring": status["expiring"],
                "days_left": status["days_left"],
                "traffic_used": status["traffic_used"],
            }
            for status in statuses
        ], ensure_ascii=False))
        return 0
    return _health(store)


def _auto_update(store: ConfigStore) -> None:
    """Auto-update stale subscriptions; never raises, logs to stderr."""
    from .subs.parser import auto_update_subscriptions

    try:
        results = auto_update_subscriptions(store)
    except Exception as exc:  # noqa: BLE001 - never block startup
        print(f"auto-update check failed: {exc}", file=sys.stderr)
        return
    updated = [r for r in results if r["updated"]]
    failed = [r for r in results if not r["updated"]]
    if updated:
        store.save()
        for r in updated:
            print(f"auto-updated subscription: {r['name']}", file=sys.stderr)
    for r in failed:
        print(f"auto-update failed for {r['name']}: {r['error']}", file=sys.stderr)


def _health_check(store: ConfigStore) -> None:
    """Warn on stderr about expired/expiring subscriptions; never raises."""
    from .subs.health import check_subscriptions

    try:
        statuses = check_subscriptions(store)
    except Exception as exc:  # noqa: BLE001 - never block startup
        print(f"health check failed: {exc}", file=sys.stderr)
        return
    for status in statuses:
        if status["expired"]:
            print(f"subscription EXPIRED: {status['name']}", file=sys.stderr)
        elif status["expiring"]:
            print(
                f"subscription expiring in {status['days_left']}d: {status['name']}",
                file=sys.stderr,
            )


def _health(store: ConfigStore) -> int:
    from .subs.health import check_subscriptions, human_bytes

    statuses = check_subscriptions(store)
    if not statuses:
        print("no subscriptions")
        return 0
    for status in statuses:
        state = "EXPIRED" if status["expired"] else ("expiring" if status["expiring"] else "ok")
        expiry = status["expires"].strftime("%Y-%m-%d") if status["expires"] else "-"
        print(
            f"{status['name']:<24} {state:<9} {expiry:<12} {human_bytes(status['traffic_used'])}"
        )
    return 0


def _install_service(store: ConfigStore, selection_id: str, config_dir: str | None) -> int:
    from . import service

    try:
        path = service.install_service(store, selection_id, config_dir)
    except (ValueError, RuntimeError) as exc:
        print(f"install failed: {exc}", file=sys.stderr)
        return 1
    print(f"installed service -> {path}")
    if service.platform() == "linux":
        print("enable with: systemctl --user enable --now v2raycli")
    elif service.platform() == "termux":
        print("enable with: sv-enable v2raycli")
    return 0


def _uninstall_service() -> int:
    from . import service

    removed = service.uninstall_service()
    if removed is None:
        print("no service installed")
        return 0
    print(f"removed service -> {removed}")
    return 0


def _connect(store: ConfigStore, selection_id: str) -> int:
    from .connection import ConnectionController

    selection = store.get_profile(selection_id) or store.get_group(selection_id)
    if selection is None:
        print(f"unknown profile or group id: {selection_id}", file=sys.stderr)
        return 1

    controller = ConnectionController(store)
    status = controller.connect(selection)
    if status.state != "connected":
        print(f"connect failed: {status.error or status.state}", file=sys.stderr)
        return 1

    print(f"connected to {status.target_name} ({status.engine})")
    for url in status.inbound.get("urls", []):
        print(f"  {url}")
    for url in status.inbound.get("lan", []):
        print(f"  LAN: {url}")
    if status.inbound.get("auth"):
        print("  (inbound auth enabled)")
    print("Press Ctrl+C to disconnect.")

    try:
        while controller.proc.is_running():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        final = controller.traffic()
        controller.disconnect()
        if final:
            from .subs.health import human_bytes

            print(f"session traffic: up={human_bytes(final['up'])}, down={human_bytes(final['down'])}")
    return 0


def _resolve_test_scope(store: ConfigStore, scope: str):
    from .test.latency import select_profiles

    ids = [part.strip() for part in scope.split(",") if part.strip()]
    if scope.strip() == "all":
        return select_profiles(store, "all")
    if len(ids) == 1 and store.get_subscription(ids[0]) is not None:
        return select_profiles(store, ("subscription", ids[0]))
    return select_profiles(store, ("profiles", ids))


def _probe(store: ConfigStore, scope: str) -> int:
    from .test.latency import probe_many, render_endpoint_table

    profiles = _resolve_test_scope(store, scope)
    if not profiles:
        print(f"no matching profiles for scope: {scope}", file=sys.stderr)
        return 1
    results = probe_many(profiles)
    render_endpoint_table(results)
    return 0 if all(result.tcp_status in {"ok", "not_testable"} for result in results) else 1


def _ws_test(store: ConfigStore, scope: str) -> int:
    from .test.latency import render_websocket_table, websocket_test_many

    profiles = _resolve_test_scope(store, scope)
    if not profiles:
        print(f"no matching profiles for scope: {scope}", file=sys.stderr)
        return 1
    results = websocket_test_many(profiles, store.config.settings, engines=store.config.engines)
    render_websocket_table(results)
    return 0 if all(
        result.not_testable
        or (result.handshake_status == "ok" and result.payload_status == "ok")
        for result in results
    ) else 1


def _update(store: ConfigStore, selection: str, proxy: str | None = None) -> int:
    from .engines.binary import BinaryError, update_binary

    engines = ["sing-box", "xray"] if selection == "both" else [selection]
    failed = False
    for engine in engines:
        try:
            options = store.config.engines.get(engine, {})
            if proxy:
                info = update_binary(engine, options, proxy=proxy)
            else:
                info = update_binary(engine, options)
        except BinaryError as exc:
            failed = True
            print(f"{engine} update failed: {exc}", file=sys.stderr)
            continue
        previous = info.previous_version or "not installed"
        print(f"{engine}: {previous} -> {info.version} ({info.path})")
    return 1 if failed else 0


def _test(store: ConfigStore, scope: str) -> int:
    from .test.latency import render_table, save_results, test_many

    profiles = _resolve_test_scope(store, scope)

    if not profiles:
        print(f"no matching profiles for scope: {scope}", file=sys.stderr)
        return 1

    results = test_many(profiles, store.config.settings, engines=store.config.engines)
    save_results(results)
    render_table(results)
    return 0 if all(r.ok or r.not_testable for r in results) else 1


def _backup(store: ConfigStore) -> int:
    from . import backup

    path = backup.create_backup("manual", store=store, keep=store.config.settings.backup_keep)
    if path is None:
        print("no config to back up", file=sys.stderr)
        return 1
    print(path)
    return 0


def _list_backups() -> int:
    from . import backup

    infos = backup.list_backups()
    if not infos:
        print("no backups found")
        return 0
    for info in infos:
        print(f"{info.timestamp}  {info.reason:<24}  {info.size:>8}  {info.path}")
    return 0


def _restore(store: ConfigStore, path: str) -> int:
    from . import backup

    try:
        backup.restore_backup(path, store)
    except Exception as exc:
        print(f"restore failed: {exc}", file=sys.stderr)
        return 1
    print(f"restored from {path}")
    return 0


def _export(store: ConfigStore, path: str, redact: bool) -> int:
    from . import exchange

    try:
        exchange.export_full(store, path, redact=redact)
    except Exception as exc:
        print(f"export failed: {exc}", file=sys.stderr)
        return 1
    print(f"exported to {path}")
    return 0


def _import(store: ConfigStore, path: str, replace: bool) -> int:
    from . import exchange

    mode = "replace" if replace else "merge"
    try:
        exchange.import_full(store, path, mode=mode)
    except Exception as exc:
        print(f"import failed: {exc}", file=sys.stderr)
        return 1
    print(f"imported {path} ({mode})")
    return 0


def _interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def _tui_available() -> bool:
    try:
        import prompt_toolkit  # noqa: F401
        import rich  # noqa: F401
    except ImportError:
        return False
    return True


def _summary(store: ConfigStore) -> int:
    conf = store.config
    print(f"v2raycli v{__version__}")
    print(f"config: {store.path}")
    print(
        f"profiles: {len(conf.profiles)}  "
        f"subscriptions: {len(conf.subscriptions)}  "
        f"groups: {len(conf.groups)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
