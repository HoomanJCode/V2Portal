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

    if args.connect:
        return _connect(store, args.connect)

    if args.test:
        return _test(store, args.test)

    if args.headless or not (_interactive() and _tui_available()):
        return _summary(store)

    from .tui.app_screen import run

    return run(store)


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
