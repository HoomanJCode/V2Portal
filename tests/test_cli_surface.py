"""CLI surface parity checks (Phase 06).

Every resource exposes the same action set (list / add / edit / remove or
resource-specific equivalents), help exits 0, and target-selector flags are
gone from the new universal-reference commands.
"""

from __future__ import annotations

import argparse
import contextlib
import io

import pytest

from v2portal import app
from v2portal.storage import ConfigStore

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


def _command_paths(parser: argparse.ArgumentParser, prefix=()):
    paths = []
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                path = (*prefix, name)
                paths.append(path)
                paths.extend(_command_paths(child, path))
    return paths


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


@pytest.mark.parametrize(
    "argv",
    [
        ["subscription", "refresh", "--all"],
        ["group", "member", "add", "001", "002"],
        ["group", "member", "remove", "001", "002"],
        ["route", "mode", "split"],
        ["settings", "show"],
        ["settings", "get", "listen"],
        ["settings", "set", "listen", "127.0.0.1"],
        ["config", "validate"],
        ["config", "export", "config.json", "--redact"],
        ["config", "import", "config.json", "--mode", "replace"],
        ["backup", "restore", "backup.json"],
        ["engine", "update", "both"],
        ["service", "install"],
        ["firewall", "list"],
    ],
)
def test_recommended_command_shapes_parse(argv):
    args = app.build_parser().parse_args(argv)
    assert args.command


@pytest.mark.parametrize(
    ("argv", "help_marker", "error_marker"),
    [
        (["profile", "not-an-action"], "profile", "invalid choice"),
        (["profile", "add", "not-a-profile-kind"], "Supported types", "invalid choice"),
        (["routing", "move", "001", "sideways"], "up, down", "invalid choice"),
        (["profile", "add", "socks", "office", "localhost", "not-a-port"], "profile add socks", "invalid int value"),
        (["server", "add", "--port", "not-a-port", "--direct"], "server add", "invalid int value"),
    ],
)
def test_invalid_command_shapes_show_contextual_help_without_traceback(
    argv, help_marker, error_marker, capsys,
):
    with pytest.raises(SystemExit) as excinfo:
        app.build_parser().parse_args(argv)

    output = capsys.readouterr()
    assert excinfo.value.code == 2
    assert help_marker in output.out + output.err
    assert error_marker in output.err
    assert "Traceback" not in output.err


def test_every_command_path_handles_missing_arguments_without_traceback():
    parser = app.build_parser()
    paths = _command_paths(parser)
    assert len(paths) > 100

    for path in paths:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                parser.parse_args(list(path))
            except SystemExit as exc:
                assert exc.code == 2, path


@pytest.mark.parametrize(
    ("argv", "config_dir", "no_auto_update"),
    [
        (["--config-dir", "/tmp/config", "status"], "/tmp/config", False),
        (["status", "--config-dir", "/tmp/config"], "/tmp/config", False),
        (["profile", "list", "--config-dir=/tmp/config", "--no-auto-update"], "/tmp/config", True),
        (["--no-auto-update", "settings", "show", "--config-dir", "/tmp/config"], "/tmp/config", True),
    ],
)
def test_global_options_parse_before_or_after_commands(argv, config_dir, no_auto_update):
    args = app.build_parser().parse_args(argv)
    assert args.config_dir == config_dir
    assert args.no_auto_update is no_auto_update


def test_nested_group_member_arguments_are_normalized_by_handler(tmp_path):
    from v2portal.models import Group, Profile

    store = ConfigStore(tmp_path / "config.json")
    store.load()
    profile = store.add_profile(Profile(name="p", kind="socks", outbound={
        "settings": {"servers": [{"address": "127.0.0.1", "port": 1080}]}
    }))
    group = store.add_group(Group(name="g", type="balancer", profile_ids=[profile.id]))
    store.save()

    args = app.build_parser().parse_args(["group", "member", "remove", group.id, profile.id])
    assert app._group_command(store, args) == 0
    assert profile.id not in group.profile_ids

