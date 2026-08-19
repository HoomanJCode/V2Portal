"""Entry point for the v2raycli command."""

from __future__ import annotations

from . import __version__
from . import config
from .storage import ConfigStore


def main(argv: list[str] | None = None) -> int:
    """Load config and print a summary.

    The interactive TUI replaces this placeholder in a later phase.
    """
    config.ensure_dirs()
    store = ConfigStore()
    store.load()
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
