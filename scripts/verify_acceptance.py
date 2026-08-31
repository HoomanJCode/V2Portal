#!/usr/bin/env python3
"""Run a credential-free acceptance smoke flow.

This command exercises the real subscription parser, storage, split-routing,
connection-controller lifecycle, scope resolution, and test dispatch. Engine
processes and network requests are mocked in-process, so it does not download
binaries, contact remote nodes, or alter the user's config.

    python scripts/verify_acceptance.py

Exit code is non-zero if any orchestration check fails.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from v2raycli import app, connection
from v2raycli.models import Profile, RoutingConfig
from v2raycli.outbounds.vpn import add_openconnect, add_openvpn
from v2raycli.routing.rules import add_rule
from v2raycli.storage import ConfigStore
from v2raycli.subs.parser import import_subscription
from v2raycli.test import latency


MIXED_PAYLOAD = [
    {
        "remarks": "smoke-vless",
        "outbounds": [
            {
                "protocol": "vless",
                "settings": {
                    "vnext": [
                        {
                            "address": "vless.example.invalid",
                            "port": 443,
                            "users": [{"id": "00000000-0000-0000-0000-000000000001"}],
                        }
                    ]
                },
            }
        ],
    },
    {
        "remarks": "smoke-socks",
        "protocol": "socks",
        "settings": {"servers": [{"address": "socks.example.invalid", "port": 1080}]},
    },
    {"remarks": "direct-only", "outbounds": [{"protocol": "freedom"}]},
]


class Checks:
    def __init__(self, quiet: bool = False) -> None:
        self.quiet = quiet
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.results.append((name, ok, detail))
        if not self.quiet:
            print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))

    def summary(self) -> bool:
        failed = [result for result in self.results if not result[1]]
        if not self.quiet:
            print("\n" + ("ALL CHECKS PASSED" if not failed else f"{len(failed)} CHECK(S) FAILED"))
        return not failed

    def as_dict(self) -> dict:
        return {
            "ok": not any(not ok for _, ok, _ in self.results),
            "checks": [
                {"name": name, "ok": ok, "detail": detail}
                for name, ok, detail in self.results
            ],
        }


class FakeProc:
    instances: list["FakeProc"] = []

    def __init__(self) -> None:
        self.running = False
        self.starts: list[tuple[list[str], dict | None]] = []
        self.stops = 0
        self.instances.append(self)

    @property
    def pid(self) -> int:
        return 4242

    def start(self, argv: list[str], env=None) -> None:
        self.starts.append((argv, env))
        self.running = True

    def is_running(self) -> bool:
        return self.running

    def logs(self) -> list[str]:
        return []

    def stop(self, grace_seconds: float = 2.0) -> None:
        self.stops += 1
        self.running = False


def run_smoke(checks: Checks | None = None) -> bool:
    checks = checks or Checks()
    FakeProc.instances.clear()

    with tempfile.TemporaryDirectory(prefix="v2portal-acceptance-") as directory:
        root = Path(directory)
        store = ConfigStore(root / "config.json")
        store.load()

        try:
            subscription, profiles, errors = import_subscription(
                "smoke", "paste://" + json.dumps(MIXED_PAYLOAD)
            )
            checks.check("subscription import", len(profiles) == 2, f"profiles={len(profiles)}")
            checks.check("unsupported node isolation", len(errors) == 1, f"errors={len(errors)}")
            store.add_subscription(subscription)
            for profile in profiles:
                store.add_profile(profile)
        except Exception as exc:  # pragma: no cover - defensive command boundary
            checks.check("subscription import", False, f"{type(exc).__name__}: {exc}")
            return checks.summary()

        selected = profiles[0]
        backup = store.add_profile(
            Profile(
                name="smoke-backup",
                kind="socks",
                outbound={"settings": {"servers": [{"address": "backup.example.invalid", "port": 1080}]}},
            )
        )
        store.config.routing = RoutingConfig(
            mode="split",
            rules=[add_rule("proxy", {"domains": ["example.com"]}, selected.id)],
        )
        checks.check("split routing setup", store.config.routing.mode == "split")

        with (
            patch.object(connection, "Proc", FakeProc),
            patch.object(connection, "locate_binary", return_value=Path("/fake/sing-box")),
            patch.object(connection, "validate_config", return_value=None),
            patch.object(connection.time, "sleep", return_value=None),
        ):
            controller = connection.ConnectionController(store, runtime_dir=root)
            first = controller.connect(selected)
            checks.check("connection dispatch", first.state == "connected", first.error or "")
            switched = controller.switch(backup)
            checks.check("connection switching", switched.target_name == backup.name, switched.error or "")
            controller.disconnect()
            checks.check("disconnect cleanup", controller.status.state == "idle")

            vpn_config = root / "smoke.ovpn"
            vpn_config.write_text("client\n", encoding="utf-8")
            vpn_profile = add_openvpn(
                "smoke-openvpn",
                config_path=str(vpn_config),
                args=["--verb", "3"],
            )
            vpn_argv = controller.vpn_argv(
                "openvpn", "/fake/openvpn", vpn_profile.vpn, vpn_profile
            )
            checks.check(
                "OpenVPN profile argv",
                vpn_argv == [
                    "/fake/openvpn",
                    "--verb",
                    "3",
                    "--config",
                    str(vpn_config),
                ],
            )

            openconnect_profile = add_openconnect(
                "smoke-openconnect",
                "vpn.example.invalid",
                args=["--user", "smoke"],
            )
            openconnect_argv = controller.vpn_argv(
                "openconnect",
                "/fake/openconnect",
                openconnect_profile.vpn,
                openconnect_profile,
            )
            checks.check(
                "OpenConnect profile argv",
                openconnect_argv == [
                    "/fake/openconnect",
                    "--user",
                    "smoke",
                    "vpn.example.invalid",
                ],
            )

        with (
            patch.object(
                latency,
                "test_many",
                side_effect=lambda selected_profiles, settings, engines=None: [
                    latency.TestResult(
                        profile_id=profile.id,
                        name=profile.name,
                        kind=profile.kind,
                        ok=True,
                        latency_ms=1.0,
                    )
                    for profile in selected_profiles
                ],
            ),
            patch.object(latency, "save_results"),
            patch.object(latency, "render_table"),
        ):
            checks.check("test scope dispatch", app._test(store, "all") == 0)

        checks.check("mock process cleanup", bool(FakeProc.instances) and all(proc.stops >= 1 for proc in FakeProc.instances))

    return checks.summary()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a credential-free v2portal acceptance smoke flow.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    checks = Checks(quiet=args.json)
    ok = run_smoke(checks)
    if args.json:
        print(json.dumps(checks.as_dict(), ensure_ascii=False, sort_keys=True))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
