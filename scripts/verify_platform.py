#!/usr/bin/env python3
"""Print read-only platform diagnostics for acceptance testing.

This command does not load or modify the user's config, download binaries,
or start engines. It reports the environment facts needed before running the
full live walkthrough on Linux, Windows, or Termux.

    python scripts/verify_platform.py
    python scripts/verify_platform.py --json
"""

from __future__ import annotations

import argparse
import json

from v2portal.diagnostics import platform_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print read-only v2portal platform diagnostics.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    report = platform_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for key, value in report.items():
            if isinstance(value, dict):
                value = ", ".join(
                    f"{name}={path or 'missing'}" for name, path in value.items()
                )
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
