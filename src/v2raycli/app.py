"""Entry point for the v2raycli command."""

from __future__ import annotations

import sys

from . import __version__
from . import config
from .storage import ConfigStore


def main(argv: list[str] | None = None) -> int:
    config.ensure_dirs()
    store = ConfigStore()
    store.load()

    if _interactive() and _tui_available():
        from .tui.app_screen import run

        return run(store)

    return _summary(store)


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
