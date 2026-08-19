"""Entry point for the v2raycli command."""

from __future__ import annotations

import argparse
import sys
import time

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
    return parser


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
    store.load()
    backup.install_backup_hook(store)

    if args.install_service:
        return _install_service(store, args.install_service, args.config_dir)
    if args.uninstall_service:
        return _uninstall_service()

    if not args.no_auto_update:
        _auto_update(store)

    if args.connect:
        return _connect(store, args.connect)

    if args.test:
        return _test(store, args.test)

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

    if args.headless or not (_interactive() and _tui_available()):
        return _summary(store)

    from .tui.app_screen import run

    return run(store)


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
        controller.disconnect()
    return 0


def _test(store: ConfigStore, scope: str) -> int:
    from .test.latency import render_table, save_results, select_profiles, test_many

    ids = [part.strip() for part in scope.split(",") if part.strip()]
    if scope.strip() == "all":
        profiles = select_profiles(store, "all")
    elif len(ids) == 1 and store.get_subscription(ids[0]) is not None:
        profiles = select_profiles(store, ("subscription", ids[0]))
    else:
        profiles = select_profiles(store, ("profiles", ids))

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
