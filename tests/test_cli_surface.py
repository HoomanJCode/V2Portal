"""CLI surface parity checks (Phase 06).

Every resource exposes the same action set (list / add / edit / remove or
resource-specific equivalents), help exits 0, and target-selector flags are
gone from the new universal-reference commands.
"""

from __future__ import annotations

import argparse

import pytest

from v2raycli import app

RESOURCES = {
    "profile": {"list", "add", "edit", "remove"},
    "subscription": {"list", "add", "edit", "remove", "update", "rename"},
    "group": {"list", "add", "edit", "remove", "add-member", "remove-member", "tree"},
    "server": {"list", "add", "edit", "remove", "start", "stop", "restart"},
    "routing": {"list", "add", "remove", "mode", "enable", "disable", "move"},
}


def _subparsers(parser: argparse.ArgumentParser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return {}


@pytest.mark.parametrize("resource,actions", RESOURCES.items())
def test_resource_actions_exist(resource, actions):
    commands = _subparsers(app.build_parser())
    assert resource in commands
    nested = _subparsers(commands[resource])
    for action in actions:
        assert action in nested, f"{resource} is missing action {action}"


@pytest.mark.parametrize(
    "argv",
    [
        ["profile", "list"],
        ["group", "add"],
        ["group", "edit"],
        ["subscription", "edit"],
        ["subscription", "rename"],
        ["server", "add"],
        ["server", "edit"],
        ["connect", "001"],
        ["routing", "add"],
    ],
)
def test_help_exits_zero(argv):
    with pytest.raises(SystemExit) as excinfo:
        app.build_parser().parse_args(argv + ["--help"])
    assert excinfo.value.code in (0, None)


def _help_text(argv) -> str:
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), pytest.raises(SystemExit):
        app.build_parser().parse_args(argv + ["--help"])
    return buf.getvalue()


def test_no_selector_flags_in_group_add_help():
    out = _help_text(["group", "add", "balancer"])
    assert "--subscription" not in out
    assert "--profile" not in out
    assert "--group" not in out


def test_no_selector_flags_in_server_add_help():
    out = _help_text(["server", "add"])
    # Positional REF (auto-detected) is documented; legacy flags are hidden.
    assert "--profile" not in out
    assert "--group" not in out
    assert "REF" in out


def test_connect_help_documents_ref():
    out = _help_text(["connect"])
    assert "profile, subscription, group, or server" in out