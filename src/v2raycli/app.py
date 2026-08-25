"""Entry point for the v2raycli command."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import __version__
from . import backup, config
from .errors import V2RayCLIError
from .storage import ConfigStore


class _SubcommandParser(argparse.ArgumentParser):
    """ArgumentParser that shows context-appropriate help on invalid commands.

    When the user enters an invalid subcommand (e.g. ``v2raycli profile foo``)
    argparse prints an unfriendly "invalid choice" error.  This subclass
    overrides ``error()`` to display the help for the parent command instead,
    making it clear what actions are available.
    """

    def error(self, message: str) -> None:  # type: ignore[override]
        ns, _ = self.parse_known_args([])
        command = getattr(ns, "command", None)
        if command is None:
            self.print_help()
        else:
            subcmd_attr = f"{command}_command"
            subcmd = getattr(ns, subcmd_attr, None)
            if subcmd is not None:
                # nested group (e.g. profile add foo, routing move ID bad)
                self._print_subcommand_help(command, subcmd)
            else:
                self._print_subcommand_help(command)
        raise SystemExit(2)

    def _print_subcommand_help(self, command: str, action: str | None = None) -> None:
        """Walk the parser tree to print the help for *command [action]*."""
        current = self
        for name in (command, *([action] if action else [])):
            for sub_action in current._actions:  # type: ignore[attr-defined]
                if (
                    isinstance(sub_action, argparse._SubParsersAction)
                    and name in sub_action._name_parser_map
                ):
                    current = sub_action._name_parser_map[name]
                    break
            else:
                break
        current.print_help()



def build_parser() -> _SubcommandParser:
    parser = _SubcommandParser(
        prog="v2raycli",
        description=(
            "v2raycli — manage proxy profiles and run inbound servers (sing-box + xray-core).\n\n"
            "Use 'v2raycli COMMAND --help' for detailed usage of any command.\n\n"
            "Examples:\n"
            "  v2raycli profile list\n"
            "  v2raycli server add --port 1080 --profile PROFILE_ID\n"
            "  v2raycli server start SERVER_ID\n"
            "  v2raycli subscription add myprovider https://example.com/sub\n"
            "  v2raycli test latency all"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="store_true", help="print version and exit")
    parser.add_argument(
        "--config-dir", metavar="PATH",
        help="use an alternate config directory (default: platform config dir)",
    )
    parser.add_argument(
        "--no-auto-update",
        action="store_true",
        help="skip auto-updating stale subscriptions on startup",
    )
    parser.add_argument(
        "--proxy",
        metavar="URL",
        help="ephemeral HTTP/SOCKS proxy for engine updates (not stored)",
    )
    _add_command_parser(parser)
    return parser


def _add_command_parser(parser: argparse.ArgumentParser) -> None:
    """Add the explicit, script-friendly command tree.

    The legacy flags above remain supported so existing automation does not
    break, while new usage reads naturally as ``resource action``.
    """
    commands = parser.add_subparsers(dest="command", title="commands", metavar="COMMAND")

    # -- status ---------------------------------------------------------------
    status = commands.add_parser(
        "status",
        help="show config summary (profiles, subscriptions, groups, routing mode)",
        description=(
            "Print a one-line summary of the loaded config, or emit JSON.\n\n"
            "Examples:\n"
            "  v2raycli status\n"
            "  v2raycli status --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    status.add_argument("--json", action="store_true", help="emit summary as JSON")

    # -- health ---------------------------------------------------------------
    health = commands.add_parser(
        "health",
        help="show subscription expiry dates and traffic usage",
        description=(
            "Print expiry status and traffic used for every enabled subscription.\n\n"
            "Examples:\n"
            "  v2raycli health\n"
            "  v2raycli health --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    health.add_argument("--json", action="store_true", help="emit health data as JSON")

    # -- profile --------------------------------------------------------------
    profile = commands.add_parser(
        "profile", aliases=["profiles"],
        help="manage proxy profiles",
        description=(
            "A profile is a single proxy configuration (SOCKS5, HTTP, VLESS, VMess,\n"
            "Trojan, Shadowsocks, WireGuard, Hysteria2, TUIC, OpenVPN, OpenConnect).\n"
            "Profiles are what you connect to. They can be added manually or\n"
            "imported from a subscription.\n\n"
            "Examples:\n"
            "  v2raycli profile list\n"
            "  v2raycli profile list --subscription SUB_ID\n"
            "  v2raycli profile list --kind socks\n"
            "  v2raycli profile add socks office 127.0.0.1 1080\n"
            "  v2raycli profile add share us 'vless://...'"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    profile_commands = profile.add_subparsers(dest="profile_command", metavar="ACTION")

    profile_list = profile_commands.add_parser(
        "list",
        help="list profiles with ID, kind, engine, and name",
        description=(
            "List all saved profiles. Use --subscription or --kind to filter.\n\n"
            "Examples:\n"
            "  v2raycli profile list\n"
            "  v2raycli profile list --subscription abc-123\n"
            "  v2raycli profile list --kind socks --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    profile_list.add_argument("--json", action="store_true", help="emit profiles as JSON array")
    profile_list.add_argument("--subscription", metavar="ID",
                             help="show only profiles imported from this subscription")
    profile_list.add_argument("--kind",
                             help="show only profiles of this protocol kind (socks, http, vless, ...)")

    profile_add = profile_commands.add_parser(
        "add",
        help="add a new profile (pick a type below)",
        description=(
            "Add a profile by type. Each type has its own required arguments.\n\n"
            "Supported types: share, raw, socks, http, wireguard, hysteria2,\n"
            "tuic, openvpn, openconnect.\n\n"
            "Examples:\n"
            "  v2raycli profile add socks office 127.0.0.1 1080\n"
            "  v2raycli profile add socks office 127.0.0.1 1080 --username u --password p\n"
            "  v2raycli profile add share us 'vless://...'\n"
            "  v2raycli profile add http proxy 10.0.0.1 8080"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    profile_add_commands = profile_add.add_subparsers(dest="profile_add_command", metavar="TYPE")

    share = profile_add_commands.add_parser(
        "share",
        help="add a v2ray share link (vmess://, vless://, trojan://, ss://, ...)",
        description=(
            "Decode a share link and add the resulting profile.\n"
            "Supported schemes: vmess, vless, trojan, ss, hysteria2, tuic,\n"
            "wireguard, socks, http.\n\n"
            "Example:\n"
            "  v2raycli profile add share my-node 'vless://uuid@host:443?...'"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    share.add_argument("name", help="display name for this profile")
    share.add_argument("link", help="the full share link string")

    raw = profile_add_commands.add_parser(
        "raw",
        help="add a raw xray/v2ray outbound JSON object (uses xray engine)",
        description=(
            "Paste a raw xray outbound JSON object or provide a file path\n"
            "containing one. The JSON must have a 'protocol' field.\n\n"
            "Example:\n"
            "  v2raycli profile add raw my-outbound '{\"protocol\":\"vmess\",\"settings\":{...}}'"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    raw.add_argument("name", help="display name for this profile")
    raw.add_argument("source", metavar="JSON_OR_PATH",
                     help="raw JSON string or path to a file containing the outbound JSON")

    for kind in ("socks", "http"):
        plain = profile_add_commands.add_parser(
            kind,
            help=f"add a {kind.upper()} proxy (host + port, optional auth)",
            description=(
                f"Add a {kind.upper()} proxy profile.\n\n"
                "Example:\n"
                f"  v2raycli profile add {kind} my-proxy 127.0.0.1 1080"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        plain.add_argument("name", help="display name for this profile")
        plain.add_argument("host", help="proxy server address")
        plain.add_argument("port", type=int, help="proxy server port")
        plain.add_argument("--username", help="authenticate with this username (optional)")
        plain.add_argument("--password", help="authenticate with this password (optional)")

    wg = profile_add_commands.add_parser(
        "wireguard",
        help="add a WireGuard profile",
        description=(
            "Add a WireGuard endpoint. Requires private key, address CIDR,\n"
            "and at least one peer with public key, endpoint, and allowed IPs.\n\n"
            "Example:\n"
            "  v2raycli profile add wireguard wg0 \\\n"
            "    --private-key 'key' --address 10.0.0.2/32 \\\n"
            "    --peer-public-key 'peer-key' --peer-endpoint 1.2.3.4:51820 \\\n"
            "    --allowed-ip 0.0.0.0/0"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    wg.add_argument("name", help="display name for this profile")
    wg.add_argument("--private-key", required=True, help="WireGuard private key")
    wg.add_argument("--address", action="append", required=True,
                    help="interface CIDR (repeatable, e.g. --address 10.0.0.2/32)")
    wg.add_argument("--peer-public-key", required=True, help="peer public key")
    wg.add_argument("--peer-endpoint", required=True, help="peer endpoint as host:port")
    wg.add_argument("--allowed-ip", action="append", required=True,
                    help="peer allowed CIDR (repeatable, e.g. --allowed-ip 0.0.0.0/0)")

    h2 = profile_add_commands.add_parser(
        "hysteria2",
        help="add a Hysteria2 profile",
        description=(
            "Add a Hysteria2 proxy profile. Requires server, port, and password.\n\n"
            "Example:\n"
            "  v2raycli profile add hysteria2 h2 1.2.3.4 443 mypassword"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    h2.add_argument("name", help="display name for this profile")
    h2.add_argument("server", help="server address")
    h2.add_argument("port", type=int, help="server port")
    h2.add_argument("password", help="authentication password")
    h2.add_argument("--sni", help="TLS server name (defaults to server address)")
    h2.add_argument("--insecure", action="store_true",
                    help="allow insecure TLS connections")

    tuic = profile_add_commands.add_parser(
        "tuic",
        help="add a TUIC profile",
        description=(
            "Add a TUIC proxy profile. Requires server, port, UUID, and password.\n\n"
            "Example:\n"
            "  v2raycli profile add tuic tuic 1.2.3.4 443 uuid-here password-here"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    tuic.add_argument("name", help="display name for this profile")
    tuic.add_argument("server", help="server address")
    tuic.add_argument("port", type=int, help="server port")
    tuic.add_argument("uuid", help="UUID for authentication")
    tuic.add_argument("password", help="authentication password")
    tuic.add_argument("--sni", help="TLS server name (defaults to server address)")
    tuic.add_argument("--alpn", help="ALPN protocols, comma-separated")

    openvpn = profile_add_commands.add_parser(
        "openvpn",
        help="add an OpenVPN profile",
        description=(
            "Add an OpenVPN profile. Provide --config-path to an .ovpn file\n"
            "or --inline with the config content. VPN profiles cannot be\n"
            "chained or balanced with proxy profiles.\n\n"
            "Examples:\n"
            "  v2raycli profile add openvpn vpn --config-path /etc/openvpn/client.ovpn\n"
            "  v2raycli profile add openvpn vpn --inline 'client\\n...'"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    openvpn.add_argument("name", help="display name for this profile")
    openvpn.add_argument("--config-path", help="path to an .ovpn config file")
    openvpn.add_argument("--inline", help="paste the .ovpn config content inline")

    openconnect = profile_add_commands.add_parser(
        "openconnect",
        help="add an OpenConnect / Cisco AnyConnect profile",
        description=(
            "Add an OpenConnect profile. Requires a server address.\n"
            "Uses the system openconnect client.\n\n"
            "Example:\n"
            "  v2raycli profile add openconnect ac vpn.example.com"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    openconnect.add_argument("name", help="display name for this profile")
    openconnect.add_argument("server", help="VPN server address")

    profile_remove = profile_commands.add_parser(
        "remove",
        help="delete a profile by ID",
        description=(
            "Remove a profile and prune it from all subscriptions and groups.\n\n"
            "Example:\n"
            "  v2raycli profile remove abc-123"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    profile_remove.add_argument("id", help="profile ID to remove")

    profile_rename = profile_commands.add_parser(
        "rename",
        help="give a profile a new display name",
        description=(
            "Rename an existing profile.\n\n"
            "Example:\n"
            "  v2raycli profile rename abc-123 'US Node 01'"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    profile_rename.add_argument("id", help="profile ID to rename")
    profile_rename.add_argument("name", help="new display name")

    profile_edit = profile_commands.add_parser(
        "edit",
        help="edit an existing profile's fields",
        description=(
            "Change fields on an existing profile. You can update the name,\n"
            "host/address, port, and authentication for socks/http types.\n\n"
            "Examples:\n"
            "  v2raycli profile edit abc-123 --name 'New Name'\n"
            "  v2raycli profile edit abc-123 --host 10.0.0.2 --port 1081\n"
            "  v2raycli profile edit abc-123 --username u --password p"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    profile_edit.add_argument("id", help="profile ID to edit")
    profile_edit.add_argument("--name", default=None, help="new display name")
    profile_edit.add_argument("--host", default=None, help="new host/address")
    profile_edit.add_argument("--port", type=int, default=None, help="new port")
    profile_edit.add_argument("--username", default=None, help="new auth username")
    profile_edit.add_argument("--password", default=None, help="new auth password")

    profile_export = profile_commands.add_parser(
        "export",
        help="print a share link for a profile",
        description=(
            "Export a profile as a share link (vmess://, vless://, etc.).\n"
            "Only encodable kinds can be exported.\n\n"
            "Example:\n"
            "  v2raycli profile export abc-123"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    profile_export.add_argument("id", help="profile ID to export")

    # -- subscription ---------------------------------------------------------
    subscription = commands.add_parser(
        "subscription", aliases=["subscriptions", "sub"],
        help="manage proxy subscriptions",
        description=(
            "A subscription is a URL that returns a list of proxy nodes.\n"
            "When you add or update one, v2raycli fetches the URL, decodes\n"
            "share links, and stores them as profiles. Stale nodes are pruned.\n\n"
            "Examples:\n"
            "  v2raycli subscription list\n"
            "  v2raycli subscription add myprovider https://example.com/sub\n"
            "  v2raycli subscription update abc-123\n"
            "  v2raycli subscription update --all"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subscription_commands = subscription.add_subparsers(dest="subscription_command", metavar="ACTION")

    subscription_list = subscription_commands.add_parser(
        "list",
        help="list subscriptions with ID, name, profile count, and URL",
        description=(
            "List all saved subscriptions.\n\n"
            "Example:\n"
            "  v2raycli subscription list --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subscription_list.add_argument("--json", action="store_true", help="emit subscriptions as JSON")

    subscription_add = subscription_commands.add_parser(
        "add",
        help="fetch a subscription URL and import its profiles",
        description=(
            "Fetch a subscription URL, decode all share links, and store\n"
            "them as profiles linked to this subscription.\n\n"
            "Accepted URL schemes: https://, http://, file://, paste://\n\n"
            "Examples:\n"
            "  v2raycli subscription add myprovider https://example.com/sub\n"
            "  v2raycli subscription add local paste://vmess://...\n"
            "  v2raycli subscription add proxied https://example.com/sub --proxy socks5://127.0.0.1:1080"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subscription_add.add_argument("name", help="display name for this subscription")
    subscription_add.add_argument("url", help="subscription URL (https, http, file, or paste)")
    subscription_add.add_argument("--user-agent", help="custom User-Agent header for HTTP requests")
    subscription_add.add_argument("--proxy",
                                 help="HTTP/SOCKS proxy for this request (e.g. socks5://127.0.0.1:1080)")

    subscription_update = subscription_commands.add_parser(
        "update",
        help="re-fetch a subscription and reconcile its profiles",
        description=(
            "Re-fetch a subscription URL and update its profiles.\n"
            "Unchanged nodes keep their names; nodes that disappeared\n"
            "upstream are deleted.\n\n"
            "Examples:\n"
            "  v2raycli subscription update abc-123\n"
            "  v2raycli subscription update --all"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subscription_update.add_argument("id", nargs="?",
                                     help="subscription ID to update (or use --all)")
    subscription_update.add_argument("--all", action="store_true", dest="update_all",
                                     help="update all enabled subscriptions")
    subscription_update.add_argument("--proxy",
                                     help="HTTP/SOCKS proxy for the request")

    subscription_remove = subscription_commands.add_parser(
        "remove",
        help="delete a subscription and all its linked profiles",
        description=(
            "Remove a subscription and unlink/remove all profiles that\n"
            "were imported from it.\n\n"
            "Example:\n"
            "  v2raycli subscription remove abc-123"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subscription_remove.add_argument("id", help="subscription ID to remove")

    # -- group ----------------------------------------------------------------
    group = commands.add_parser(
        "group", aliases=["groups"],
        help="manage profile groups (balancers, chains, singles)",
        description=(
        "A group lets you connect to multiple profiles at once.\n\n"
        "  balancer  — pick the fastest/random/round-robin from a set\n"
        "  chain     — route traffic through proxies in order\n"
        "  single    — wrap one profile as a named group\n\n"
        "VPN profiles (OpenVPN, OpenConnect) cannot join groups.\n\n"
        "Examples:\n"
        "  v2raycli group list\n"
        "  v2raycli group create balancer fast ID_A ID_B --strategy latency\n"
        "  v2raycli group create chain tunnel ID_A ID_B\n"
        "  v2raycli group add-member GROUP_ID PROFILE_ID\n"
        "  v2raycli group add-sub GROUP_ID SUB_ID"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group_commands = group.add_subparsers(dest="group_command", metavar="ACTION")

    group_list = group_commands.add_parser(
        "list",
        help="list groups with ID, type, strategy, and member count",
        description=(
            "List all saved groups.\n\n"
            "Example:\n"
            "  v2raycli group list --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group_list.add_argument("--json", action="store_true", help="emit groups as JSON")

    group_create = group_commands.add_parser(
        "create",
        help="create a group (pick balancer or chain)",
        description=(
            "Create a group. Use 'balancer' or 'chain' as the next argument.\n\n"
            "Examples:\n"
            "  v2raycli group create balancer fast ID_A ID_B\n"
            "  v2raycli group create chain tunnel ID_A ID_B"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group_create_commands = group_create.add_subparsers(dest="group_create_command", metavar="TYPE")

    balancer = group_create_commands.add_parser(
        "balancer",
        help="create a balanced group (strategy: latency|random|roundRobin|leastLoad)",
        description=(
            "Create a balancer group. Requires a name and 2+ profile IDs or\n"
            "subscription IDs. IDs are detected automatically — pass profile\n"
            "and subscription IDs together and they are sorted by type.\n"
            "Subscription profiles are resolved dynamically.\n\n"
            "  latency      — pick the lowest-latency profile (sing-box urltest)\n"
            "  random       — pick a random profile\n"
            "  roundRobin   — rotate through profiles in order\n"
            "  leastLoad    — pick the least-loaded (forces xray engine)\n\n"
            "Examples:\n"
            "  v2raycli group create balancer fast ID_A ID_B --strategy latency\n"
            "  v2raycli group create balancer pool ID_A SUB_ID\n"
            "  v2raycli group create balancer fromsub SUB_A SUB_B"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    balancer.add_argument("name", help="display name for this group")
    balancer.add_argument("profile_ids", nargs="*", default=[],
                         help="profile or subscription IDs (auto-detected) to include in this balancer")
    balancer.add_argument("--subscription", action="append", default=[], dest="subscription_ids",
                         help="subscription ID whose profiles are included (repeatable; optional — positional IDs are auto-detected)")
    balancer.add_argument("--strategy",
                         choices=("latency", "random", "roundRobin", "leastLoad"),
                         default="latency",
                         help="balancing strategy (default: latency)")
    balancer.add_argument("--engine",
                         choices=("auto", "sing-box", "xray"),
                         default="auto",
                         help="force a specific engine (default: auto)")

    chain = group_create_commands.add_parser(
        "chain",
        help="create a proxy chain (traffic flows through each hop in order)",
        description=(
            "Create a chain group. Requires a name and 2+ profile IDs\n"
            "or subscription IDs. IDs are detected automatically — pass profile\n"
            "and subscription IDs together and they are sorted by type.\n"
            "Subscription profiles are resolved dynamically.\n"
            "Traffic flows through the first proxy, then the second, and so on.\n\n"
            "Examples:\n"
            "  v2raycli group create chain tunnel ID_A ID_B\n"
            "  v2raycli group create chain tunnel ID_A SUB_ID"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    chain.add_argument("name", help="display name for this group")
    chain.add_argument("profile_ids", nargs="*", default=[],
                      help="ordered profile or subscription IDs (auto-detected) forming the chain")
    chain.add_argument("--subscription", action="append", default=[], dest="subscription_ids",
                      help="subscription ID whose profiles are included (repeatable; optional — positional IDs are auto-detected)")
    chain.add_argument("--engine",
                      choices=("auto", "sing-box", "xray"),
                      default="auto",
                      help="force a specific engine (default: auto)")

    group_remove = group_commands.add_parser(
        "remove",
        help="delete a group by ID",
        description=(
            "Remove a group. Profiles are not deleted.\n\n"
            "Example:\n"
            "  v2raycli group remove abc-123"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group_remove.add_argument("id", help="group ID to remove")

    group_add_member = group_commands.add_parser(
        "add-member",
        help="add a profile to a group",
        description=(
            "Add profiles and/or subscriptions to an existing group.\n"
            "IDs are detected automatically (profile or subscription).\n\n"
            "Examples:\n"
            "  v2raycli group add-member GROUP_ID PROFILE_ID\n"
            "  v2raycli group add-member GROUP_ID PROFILE_A SUB_ID PROFILE_B"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group_add_member.add_argument("id", help="group ID to modify")
    group_add_member.add_argument("profile_ids", nargs="+",
                                  help="profile or subscription ID(s) to add (auto-detected)")

    group_remove_member = group_commands.add_parser(
        "remove-member",
        help="remove a profile from a group",
        description=(
            "Remove profiles and/or subscriptions from an existing group.\n"
            "IDs are detected automatically (profile or subscription).\n\n"
            "Examples:\n"
            "  v2raycli group remove-member GROUP_ID PROFILE_ID\n"
            "  v2raycli group remove-member GROUP_ID PROFILE_A SUB_ID PROFILE_B"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group_remove_member.add_argument("id", help="group ID to modify")
    group_remove_member.add_argument("profile_ids", nargs="+",
                                  help="profile or subscription ID(s) to remove (auto-detected)")

    group_add_sub = group_commands.add_parser(
        "add-sub",
        help="add a subscription to a group",
        description=(
            "Add a subscription to a group. Its profiles are resolved\n"
            "dynamically and update when the subscription is refreshed.\n"
            "Note: 'group add-member' already auto-detects subscription IDs,\n"
            "so this command is only kept for convenience.\n\n"
            "Examples:\n"
            "  v2raycli group add-sub GROUP_ID SUB_ID\n"
            "  v2raycli group add-sub GROUP_ID SUB_A SUB_B"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group_add_sub.add_argument("id", help="group ID to modify")
    group_add_sub.add_argument("subscription_ids", nargs="+", help="subscription ID(s) to add")

    group_remove_sub = group_commands.add_parser(
        "remove-sub",
        help="remove a subscription from a group",
        description=(
            "Remove a subscription from a group.\n\n"
            "Examples:\n"
            "  v2raycli group remove-sub GROUP_ID SUB_ID"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group_remove_sub.add_argument("id", help="group ID to modify")
    group_remove_sub.add_argument("subscription_ids", nargs="+", help="subscription ID(s) to remove")

    # -- test -----------------------------------------------------------------
    test = commands.add_parser(
        "test",
        help="test proxy outbounds (latency, reachability, websocket)",
        description=(
            "Test profiles to measure latency, check endpoint reachability,\n"
            "or validate WebSocket handshakes. Scope can be 'all', a\n"
            "subscription ID, a group ID, or comma-separated profile IDs.\n\n"
            "Examples:\n"
            "  v2raycli test latency all\n"
            "  v2raycli test latency SUB_ID\n"
            "  v2raycli test latency GROUP_ID\n"
            "  v2raycli test endpoint all\n"
            "  v2raycli test websocket ID_A,ID_B"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    test_commands = test.add_subparsers(dest="test_command", metavar="TYPE")

    latency = test_commands.add_parser(
        "latency", aliases=["request"],
        help="measure real proxy request delay (connects through the engine)",
        description=(
            "Connect through the engine and measure response time for each\n"
            "profile. Scope: 'all', 'routing', a subscription ID, or profile IDs.\n\n"
            "Examples:\n"
            "  v2raycli test latency all\n"
            "  v2raycli test latency routing\n"
            "  v2raycli test latency SUB_ID\n"
            "  v2raycli test request ID_A,ID_B"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    latency.add_argument("scope", nargs="?", default="all",
                        help="'all', 'routing', a subscription ID, or comma-separated profile IDs (default: all)")

    endpoint = test_commands.add_parser(
        "endpoint", aliases=["probe"],
        help="probe endpoint reachability with ICMP/TCP (no engine needed)",
        description=(
            "Check if remote endpoints are reachable via ICMP ping or\n"
            "TCP connect. Reports ok / refused / timeout / not_testable.\n\n"
            "Examples:\n"
            "  v2raycli test endpoint all\n"
            "  v2raycli test probe SUB_ID"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    endpoint.add_argument("scope", nargs="?", default="all",
                         help="'all', a subscription ID, or comma-separated profile IDs (default: all)")

    websocket = test_commands.add_parser(
        "websocket", aliases=["ws"],
        help="validate WebSocket/WSS handshake and ping/pong",
        description=(
            "Start the engine, connect to WebSocket-based profiles, and\n"
            "verify the WS/WSS upgrade, handshake, and ping/pong exchange.\n\n"
            "Examples:\n"
            "  v2raycli test websocket all\n"
            "  v2raycli test ws SUB_ID"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    websocket.add_argument("scope", nargs="?", default="all",
                          help="'all', a subscription ID, or comma-separated profile IDs (default: all)")

    # -- backup ----------------------------------------------------------------
    backup_command = commands.add_parser(
        "backup",
        help="manage config backups (create, list, restore)",
        description=(
            "Automatic backups are created before destructive operations.\n"
            "Use these commands to create, browse, or restore backups.\n\n"
            "Examples:\n"
            "  v2raycli backup create\n"
            "  v2raycli backup list\n"
            "  v2raycli backup restore /path/to/backup.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    backup_commands = backup_command.add_subparsers(dest="backup_command", metavar="ACTION")

    backup_commands.add_parser(
        "create",
        help="snapshot the current config to a timestamped backup file",
        description=(
            "Create a manual backup of the current config.\n"
            "Old backups beyond 'backup_keep' (default 10) are pruned.\n\n"
            "Example:\n"
            "  v2raycli backup create"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    backup_commands.add_parser(
        "list",
        help="list available backups (newest first)",
        description=(
            "List all backup files with timestamp, reason, and size.\n\n"
            "Example:\n"
            "  v2raycli backup list"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    restore = backup_commands.add_parser(
        "restore",
        help="replace the current config with a backup file",
        description=(
            "Restore the config from a backup file. The current config\n"
            "is backed up first as a safety measure.\n\n"
            "Example:\n"
            "  v2raycli backup restore /path/to/backup.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    restore.add_argument("path", help="path to the backup file to restore")

    # -- config ----------------------------------------------------------------
    config_command = commands.add_parser(
        "config",
        help="inspect or transfer the complete config",
        description=(
            "Show, export, import, or change individual settings.\n\n"
            "Examples:\n"
            "  v2raycli config show\n"
            "  v2raycli config show --redact\n"
            "  v2raycli config set settings.mixed_port 1081\n"
            "  v2raycli config set settings.allow_lan true\n"
            "  v2raycli config export /tmp/config.json\n"
            "  v2raycli config import /tmp/config.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_commands = config_command.add_subparsers(dest="config_command", metavar="ACTION")

    config_show = config_commands.add_parser(
        "show",
        help="print the complete config as formatted JSON",
        description=(
            "Dumps the full config.json content. Use --redact to mask\n"
            "credentials and keys (safe for sharing).\n\n"
            "Examples:\n"
            "  v2raycli config show\n"
            "  v2raycli config show --redact"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_show.add_argument("--redact", action="store_true",
                            help="mask passwords, keys, and secrets with 'REDACTED'")

    config_export = config_commands.add_parser(
        "export",
        help="write the complete config to a file",
        description=(
            "Export the full config to a JSON file. Use --redact to\n"
            "mask credentials.\n\n"
            "Example:\n"
            "  v2raycli config export /tmp/config.json --redact"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_export.add_argument("path", help="output file path")
    config_export.add_argument("--redact", action="store_true",
                             help="mask credentials and keys")

    config_import = config_commands.add_parser(
        "import",
        help="import a complete config (merge by default, or replace)",
        description=(
            "Import a previously exported config. By default new items\n"
            "are merged with the existing config. Use --replace to swap\n"
            "the entire config.\n\n"
            "Examples:\n"
            "  v2raycli config import /tmp/config.json\n"
            "  v2raycli config import /tmp/config.json --replace"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_import.add_argument("path", help="path to the exported config file")
    config_import.add_argument("--replace", action="store_true",
                             help="replace the entire config (not merge)")

    config_set = config_commands.add_parser(
        "set",
        help="change a single setting",
        description=(
            "Set a specific config value. The key must be a dotted path\n"
            "like 'settings.mixed_port'. Boolean values use true/false.\n\n"
            "Available keys:\n"
            "  settings.listen              listen address (default: 0.0.0.0)\n"
            "  settings.mixed_port          mixed SOCKS5+HTTP port (default: 1080)\n"
            "  settings.socks_port          dedicated SOCKS-only port (0 = disabled)\n"
            "  settings.http_port           dedicated HTTP-only port (0 = disabled)\n"
            "  settings.allow_lan            allow LAN sharing (true/false)\n"
            "  settings.default_engine       default engine: sing-box or xray\n"
            "  settings.test_url             URL used for latency tests\n"
            "  settings.subscription_proxy   proxy for subscription fetches\n\n"
            "Examples:\n"
            "  v2raycli config set settings.mixed_port 1081\n"
            "  v2raycli config set settings.socks_port 1081\n"
            "  v2raycli config set settings.http_port 1082\n"
            "  v2raycli config set settings.allow_lan false\n"
            "  v2raycli config set settings.default_engine xray"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    config_set.add_argument("key",
                           choices=("settings.listen", "settings.mixed_port",
                                    "settings.socks_port", "settings.http_port",
                                    "settings.allow_lan", "settings.default_engine",
                                    "settings.test_url", "settings.subscription_proxy"),
                           help="dotted setting key to change")
    config_set.add_argument("value", help="new value (use true/false for booleans, numbers for ports)")

    # -- engine ----------------------------------------------------------------
    engine = commands.add_parser(
        "engine",
        help="manage sing-box / xray engine binaries",
        description=(
            "Download or update the proxy engine binaries. Only binaries\n"
            "with binary_path='auto' are replaceable; custom paths are\n"
            "never overwritten. Updates are staged, verified, and rolled\n"
            "back if verification fails.\n\n"
            "Examples:\n"
            "  v2raycli engine update sing-box\n"
            "  v2raycli engine update xray\n"
            "  v2raycli engine update both\n"
            "  v2raycli engine update both --proxy socks5://127.0.0.1:10808"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    engine_commands = engine.add_subparsers(dest="engine_command", metavar="ACTION")

    engine_update = engine_commands.add_parser(
        "update",
        help="download and replace engine binaries",
        description=(
            "Explicitly update the sing-box, xray, or both engine\n"
            "binaries. Downloads are verified and atomic.\n\n"
            "Examples:\n"
            "  v2raycli engine update sing-box\n"
            "  v2raycli engine update both --proxy socks5://127.0.0.1:10808"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    engine_update.add_argument("engine", choices=("sing-box", "xray", "both"),
                             help="which engine to update")
    engine_update.add_argument("--proxy",
                             help="HTTP/SOCKS proxy for the download (not stored)")

    # -- completion -----------------------------------------------------------
    completion_cmd = commands.add_parser(
        "completion",
        help="generate shell completion script",
        description=(
            "Print a shell completion script. Supports bash and zsh.\n\n"
            "Examples:\n"
            "  source <(v2raycli completion bash)     # bash\n"
            "  source <(v2raycli completion zsh)      # zsh"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    completion_cmd.add_argument(
        "shell", choices=("bash", "zsh"), nargs="?",
        help="target shell for the completion script",
    )
    completion_cmd.add_argument(
        "--complete", nargs=1, dest="complete_line",
        help=argparse.SUPPRESS,
    )

    # -- service ---------------------------------------------------------------
    service_command = commands.add_parser(
        "service",
        help="install or uninstall a boot service (Linux systemd / Termux)",
        description=(
            "Keep a chosen profile connected across reboots by installing\n"
            "a system service. Supported platforms: Linux (systemd user unit),\n"
            "Termux (termux-services).\n\n"
            "Examples:\n"
            "  v2raycli service install PROFILE_ID\n"
            "  v2raycli service uninstall"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    service_commands = service_command.add_subparsers(dest="service_command", metavar="ACTION")

    service_install = service_commands.add_parser(
        "install",
        help="create a boot service that connects to a profile",
        description=(
            "Write a systemd user unit (Linux) or termux-services script\n"
            "(Termux) that launches 'v2raycli connect ID' on boot.\n\n"
            "After install, enable with:\n"
            "  systemctl --user enable --now v2raycli    (Linux)\n"
            "  sv-enable v2raycli                        (Termux)\n\n"
            "Example:\n"
            "  v2raycli service install abc-123"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    service_install.add_argument("id", help="profile or group ID to connect on boot")

    service_uninstall = service_commands.add_parser(
        "uninstall",
        help="remove the installed boot service",
        description=(
            "Remove the systemd unit or termux-services script.\n\n"
            "Example:\n"
            "  v2raycli service uninstall"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # -- routing ---------------------------------------------------------------
    routing = commands.add_parser(
        "routing",
        help="manage split-routing rules (proxy / direct / block)",
        description=(
            "Control which traffic goes through the proxy, goes direct,\n"
            "or is blocked. In 'all' mode everything is proxied. In 'split'\n"
            "mode the first matching rule wins.\n\n"
            "Rule matchers:\n"
            "  --domain example.com           exact domain match\n"
            "  --domain keyword:ads           substring match\n"
            "  --domain regex:^x\\.            regex match\n"
            "  --domain geosite:category-ads  sing-box/xray geo-site list\n"
            "  --ip 10.0.0.0/8                CIDR match\n"
            "  --ip geoip:cn                  sing-box/xray geo-IP list\n\n"
            "Examples:\n"
            "  v2raycli routing list\n"
            "  v2raycli routing mode split\n"
            "  v2raycli routing add block --domain keyword:ads\n"
            "  v2raycli routing add direct --ip 192.168.0.0/16\n"
            "  v2raycli routing add proxy --domain example.com --target PROFILE_ID\n"
            "  v2raycli routing remove RULE_ID"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    routing_commands = routing.add_subparsers(dest="routing_command", metavar="ACTION")

    routing_list = routing_commands.add_parser(
        "list",
        help="list routing mode and all rules",
        description=(
            "Show the current routing mode and ordered rule list.\n\n"
            "Examples:\n"
            "  v2raycli routing list\n"
            "  v2raycli routing list --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    routing_list.add_argument("--json", action="store_true",
                             help="emit routing rules as JSON")

    routing_mode = routing_commands.add_parser(
        "mode",
        help="switch between 'all' (everything proxied) and 'split' (rule-based)",
        description=(
            "Set the routing mode. 'all' sends everything through the\n"
            "connected proxy. 'split' applies the rule list in order.\n\n"
            "Examples:\n"
            "  v2raycli routing mode all\n"
            "  v2raycli routing mode split"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    routing_mode.add_argument("mode", choices=("all", "split"),
                             help="routing mode: 'all' or 'split'")

    routing_add = routing_commands.add_parser(
        "add",
        help="add a routing rule (proxy / direct / block)",
        description=(
            "Add an ordered routing rule. The first matching rule wins.\n"
            "Use --domain, --ip, --geoip, and --geosite to build the\n"
            "match criteria. Add at least one matcher.\n\n"
            "Actions:\n"
            "  proxy   — route matching traffic through the connected proxy\n"
            "  direct  — let matching traffic bypass the proxy\n"
            "  block   — drop matching traffic\n\n"
            "Examples:\n"
            "  v2raycli routing add block --domain keyword:ads\n"
            "  v2raycli routing add direct --ip 192.168.0.0/16\n"
            "  v2raycli routing add proxy --domain example.com --target PROFILE_ID\n"
            "  v2raycli routing add block --geosite category-ads-all"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    routing_add.add_argument("action", choices=("proxy", "direct", "block"),
                            help="what to do with matching traffic")
    routing_add.add_argument("--target",
                            help="profile/group ID (required for proxy action)")
    routing_add.add_argument("--domain", action="append", default=[],
                            help="domain to match (repeatable; prefix with keyword: or regex:)")
    routing_add.add_argument("--ip", action="append", default=[],
                            help="IP/CIDR to match (repeatable; prefix with geoip:)")
    routing_add.add_argument("--geoip", action="append", default=[],
                            help="geoip list name (repeatable, e.g. --geoip cn private)")
    routing_add.add_argument("--geosite", action="append", default=[],
                            help="geosite list name (repeatable, e.g. --geosite category-ads-all)")

    routing_remove = routing_commands.add_parser(
        "remove",
        help="delete a routing rule by ID",
        description=(
            "Remove a routing rule. Rules are shown with their IDs\n"
            "in 'routing list'.\n\n"
            "Example:\n"
            "  v2raycli routing remove RULE_ID"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    routing_remove.add_argument("id", help="routing rule ID to remove")

    routing_move = routing_commands.add_parser(
        "move",
        help="reorder a routing rule (up or down in priority)",
        description=(
            "Move a routing rule up (higher priority) or down (lower priority).\n"
            "Rules are applied in order; the first match wins.\n\n"
            "Example:\n"
            "  v2raycli routing move RULE_ID up\n"
            "  v2raycli routing move RULE_ID down"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    routing_move.add_argument("id", help="routing rule ID to move")
    routing_move.add_argument("direction", choices=("up", "down"),
                             help="move the rule up (higher priority) or down")

    routing_enable = routing_commands.add_parser(
        "enable",
        help="enable a routing rule",
        description=(
            "Re-enable a disabled routing rule.\n\n"
            "Example:\n"
            "  v2raycli routing enable RULE_ID"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    routing_enable.add_argument("id", help="routing rule ID to enable")

    routing_disable = routing_commands.add_parser(
        "disable",
        help="disable a routing rule without deleting it",
        description=(
            "Disable a routing rule so it is skipped during routing.\n"
            "The rule is kept in the config and can be re-enabled later.\n\n"
            "Example:\n"
            "  v2raycli routing disable RULE_ID"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    routing_disable.add_argument("id", help="routing rule ID to disable")

    # -- server ---------------------------------------------------------------
    server_cmd = commands.add_parser(
        "server", aliases=["sv"],
        help="manage inbound proxy servers (multiple ports, each with its own outbound)",
        description=(
            "A server is a persistent inbound proxy that listens on a dedicated port\n"
            "and forwards traffic to a specific profile or group. Multiple servers\n"
            "can run simultaneously, each on its own port.\n\n"
            "Examples:\n"
            "  v2raycli server add --port 1080 --profile abc --name 'US proxy'\n"
            "  v2raycli server add --port 1081 --group def --protocol http\n"
            "  v2raycli server list\n"
            "  v2raycli server start\n"
            "  v2raycli server start SERVER_ID\n"
            "  v2raycli server stop\n"
            "  v2raycli server stop SERVER_ID\n"
            "  v2raycli server restart\n"
            "  v2raycli server restart SERVER_ID"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    server_commands = server_cmd.add_subparsers(dest="server_command", metavar="ACTION")

    server_list = server_commands.add_parser(
        "list",
        help="list configured servers with port, protocol, and outbound",
        description=(
            "List all saved servers with their ports and outbound targets.\n\n"
            "Examples:\n"
            "  v2raycli server list\n"
            "  v2raycli server list --running\n"
            "  v2raycli server list --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    server_list.add_argument("--json", action="store_true", help="emit servers as JSON")
    server_list.add_argument("--running", action="store_true", help="show only running servers")

    server_add = server_commands.add_parser(
        "add",
        help="add a new server (port + outbound)",
        description=(
            "Create a persistent server that binds a port to an outbound.\n"
            "The server is saved in config and can be started later.\n\n"
            "Protocol options:\n"
            "  mixed  — SOCKS5 + HTTP on one port (default)\n"
            "  socks  — SOCKS5 only\n"
            "  http   — HTTP only\n\n"
            "Examples:\n"
            "  v2raycli server add --port 1080 --profile abc --name 'US proxy'\n"
            "  v2raycli server add --port 1081 --group def --protocol http\n"
            "  v2raycli server add --port 1082 --profile abc --protocol socks"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    server_add.add_argument("--port", type=int, required=True, help="port to listen on")
    server_outbound = server_add.add_mutually_exclusive_group()
    server_outbound.add_argument("--profile", help="profile ID to forward to")
    server_outbound.add_argument("--group", help="group ID to forward to")
    server_add.add_argument("--name", default="", help="display name for this server")
    server_add.add_argument("--protocol", choices=("mixed", "socks", "http"), default="mixed",
                           help="inbound protocol (default: mixed)")
    server_add.add_argument("--listen", default="0.0.0.0", help="listen address (default: 0.0.0.0)")

    server_start = server_commands.add_parser(
        "start",
        help="start a server, or all servers when no ID is given",
        description=(
            "Start a server's engine process. The server must be added first.\n"
            "Without arguments starts all enabled servers.\n\n"
            "Use --temp to start a one-shot server without saving it to config.\n"
            "The temporary server runs until you press Ctrl+C.\n\n"
            "Examples:\n"
            "  v2raycli server start\n"
            "  v2raycli server start SERVER_ID\n"
            "  v2raycli server start --all\n"
            "  v2raycli server start --temp --profile PROFILE_ID\n"
            "  v2raycli server start --temp --proxy socks5://192.168.1.2:10804\n"
            "  v2raycli server start --temp --proxy http://10.0.0.1:8080 --port 8180"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    server_start.add_argument("id", nargs="?", help="server ID to start (or use --all)")
    server_start.add_argument("--all", action="store_true", dest="start_all",
                             help="start all enabled servers")
    server_start.add_argument("--temp", action="store_true", dest="temp",
                             help="start a temporary server (not saved; runs until Ctrl+C)")
    server_start.add_argument("--port", type=int, default=1080,
                             help="port for temporary server (default: 1080)")
    server_start.add_argument("--protocol", choices=("mixed", "socks", "http"), default="mixed",
                             help="inbound protocol for temporary server (default: mixed)")
    server_start.add_argument("--profile",
                             help="profile ID for temporary server")
    server_start.add_argument("--group",
                             help="group ID for temporary server")
    server_start.add_argument("--proxy",
                             help="upstream proxy URL for temporary server (e.g. socks5://host:port)")
    server_start.add_argument("--listen", default="0.0.0.0",
                             help="listen address for temporary server (default: 0.0.0.0)")

    server_stop = server_commands.add_parser(
        "stop",
        help="stop a running server, or all servers when no ID is given",
        description=(
            "Stop a running server's engine process.\n"
            "Without arguments stops all running servers.\n\n"
            "Examples:\n"
            "  v2raycli server stop\n"
            "  v2raycli server stop SERVER_ID\n"
            "  v2raycli server stop --all"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    server_stop.add_argument("id", nargs="?", help="server ID to stop (or use --all)")
    server_stop.add_argument("--all", action="store_true", dest="stop_all",
                            help="stop all running servers")

    server_restart = server_commands.add_parser(
        "restart",
        help="restart a server (or --all)",
        description=(
            "Restart a server. Equivalent to stop + start.\n\n"
            "Examples:\n"
            "  v2raycli server restart SERVER_ID\n"
            "  v2raycli server restart --all"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    server_restart.add_argument("id", nargs="?", help="server ID to restart (or use --all)")
    server_restart.add_argument("--all", action="store_true", dest="restart_all",
                               help="restart all enabled servers")

    server_edit = server_commands.add_parser(
        "edit",
        help="edit a server's settings",
        description=(
            "Change fields on an existing server. You can update the name,\n"
            "port, protocol, listen address, or outbound (profile/group).\n\n"
            "If the server is running, it is restarted automatically.\n\n"
            "Examples:\n"
            "  v2raycli server edit abc --name 'US proxy'\n"
            "  v2raycli server edit abc --port 8180\n"
            "  v2raycli server edit abc --profile NEW_PROFILE_ID\n"
            "  v2raycli server edit abc --group NEW_GROUP_ID\n"
            "  v2raycli server edit abc --protocol http"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    server_edit.add_argument("id", help="server ID to edit")
    server_edit.add_argument("--name", default=None, help="new display name")
    server_edit.add_argument("--port", type=int, default=None, help="new port")
    server_edit.add_argument("--protocol", choices=("mixed", "socks", "http"), default=None,
                            help="new inbound protocol")
    server_edit.add_argument("--listen", default=None, help="new listen address")
    server_outbound_edit = server_edit.add_mutually_exclusive_group()
    server_outbound_edit.add_argument("--profile", default=None,
                                      help="switch outbound to this profile ID")
    server_outbound_edit.add_argument("--group", default=None,
                                      help="switch outbound to this group ID")
    server_outbound_edit.add_argument("--direct", action="store_true", default=False,
                                      help="switch outbound to direct (no proxy)")

    server_remove = server_commands.add_parser(
        "remove",
        help="remove a server from config",
        description=(
            "Remove a server. Stops it first if running.\n\n"
            "Example:\n"
            "  v2raycli server remove SERVER_ID"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    server_remove.add_argument("id", help="server ID to remove")


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

    if args.command == "health":
        return _command(store, args)
    if args.command:
        if not args.no_auto_update:
            _auto_update(store)
        # Only show health warnings on status/health, not every command.
        if args.command in ("status", "health") and not args.no_auto_update:
            _health_check(store)
        return _command(store, args)

    if not args.no_auto_update:
        _auto_update(store)
        _health_check(store)

    return _summary(store)


def _command(store: ConfigStore, args) -> int:
    """Dispatch the explicit command tree without prompting for input."""
    command = args.command
    try:
        if command == "status":
            return _status(store, args.json)
        if command in ("profile", "profiles"):
            return _profile_command(store, args)
        if command in ("subscription", "subscriptions", "sub"):
            return _subscription_command(store, args)
        if command in ("group", "groups"):
            return _group_command(store, args)
        if command == "test":
            if not args.test_command:
                return _command_help(args, "test")
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
        if command == "completion":
            return _completion_command(args)
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
        if command in ("server", "sv"):
            return _server_command(store, args)
        if command == "health":
            return _health_command(store, args.json)
        return _command_help(args)
    except (OSError, ValueError, TypeError, KeyError, V2RayCLIError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _not_found(entity: str, bad_id: str, store: ConfigStore) -> None:
    """Print an error and list available IDs for *entity*."""
    print(f"unknown {entity} id: {bad_id}", file=sys.stderr)
    if entity == "profile":
        for p in store.list_profiles():
            print(f"  {p.id}  {p.name}", file=sys.stderr)
    elif entity == "server":
        for s in store.list_servers():
            print(f"  {s.id}  :{s.port}  {s.name}", file=sys.stderr)
    elif entity == "group":
        for g in store.list_groups():
            print(f"  {g.id}  {g.name}", file=sys.stderr)
    elif entity == "subscription":
        for s in store.list_subscriptions():
            print(f"  {s.id}  {s.name}", file=sys.stderr)
    elif entity == "rule":
        for r in store.config.routing.rules:
            print(f"  {r.id}  {r.action}  {r.match}", file=sys.stderr)


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
    if action is None:
        action = "list"
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
        if getattr(args, 'json', False):
            print(json.dumps(rows, ensure_ascii=False))
        elif rows:
            if sys.stdout.isatty():
                from rich.console import Console
                from rich.table import Table

                table = Table(title="Profiles", border_style="dim")
                table.add_column("ID", style="dim")
                table.add_column("Kind")
                table.add_column("Engine")
                table.add_column("Name")
                table.add_column("Source")
                for row in rows:
                    sub = row["subscription_id"] or ""
                    src = f"sub:{sub}" if sub else row["source"]
                    table.add_row(row["id"], row["kind"], row["engine"], row["name"], src)
                Console().print(table)
            else:
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
            _not_found("profile", args.id, store)
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
    if action == "edit":
        from .outbounds.manual import edit_profile

        profile = store.get_profile(args.id)
        if profile is None:
            _not_found("profile", args.id, store)
            return 1
        updates = {}
        if args.name is not None:
            updates["name"] = args.name
        if args.host is not None:
            if "outbound" in profile.to_dict() and isinstance(profile.outbound, dict):
                profile.outbound["server"] = args.host
            else:
                updates["name"] = profile.name  # only name is editable
        if args.port is not None:
            if "outbound" in profile.to_dict() and isinstance(profile.outbound, dict):
                profile.outbound["server_port"] = args.port
        if args.username is not None or args.password is not None:
            if profile.kind in ("socks", "http") and isinstance(profile.outbound, dict):
                users = profile.outbound.get("users", [])
                if not users:
                    users = [{}]
                    profile.outbound["users"] = users
                if args.username is not None:
                    users[0]["user"] = args.username
                if args.password is not None:
                    users[0]["pass"] = args.password
        edit_profile(store, args.id, **updates)
        store.save()
        print(f"updated profile {args.id}")
        return 0
    if action == "export":
        profile = store.get_profile(args.id)
        if profile is None:
            _not_found("profile", args.id, store)
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
    if action is None:
        action = "list"
    if action == "list":
        statuses = []
        for sub in store.list_subscriptions():
            statuses.append(
                {"id": sub.id, "name": sub.name, "profiles": len(sub.profile_ids), "url": sub.url}
            )
        if getattr(args, 'json', False):
            print(json.dumps(statuses, ensure_ascii=False))
        elif statuses:
            if sys.stdout.isatty():
                from rich.console import Console
                from rich.table import Table

                table = Table(title="Subscriptions", border_style="dim")
                table.add_column("ID", style="dim")
                table.add_column("Name")
                table.add_column("Profiles", justify="right")
                table.add_column("URL")
                for row in statuses:
                    table.add_row(row["id"], row["name"], str(row["profiles"]), row["url"])
                Console().print(table)
            else:
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
            except (OSError, ValueError, V2RayCLIError) as exc:
                failed = True
                print(f"{sub_id}  update failed: {exc}", file=sys.stderr)
        store.save()
        return 1 if failed else 0
    if action == "remove":
        sub = store.get_subscription(args.id)
        if sub is None:
            _not_found("subscription", args.id, store)
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
    if action is None:
        action = "list"
    if action == "list":
        rows = []
        for g in store.list_groups():
            sub_label = f"+{len(g.subscription_ids)}sub" if g.subscription_ids else ""
            rows.append({
                "id": g.id, "name": g.name, "type": g.type, "strategy": g.strategy,
                "profiles": len(g.profile_ids),
                "subscription_ids": g.subscription_ids,
                "sub_label": sub_label,
            })
        if getattr(args, 'json', False):
            print(json.dumps(rows, ensure_ascii=False))
        elif rows:
            if sys.stdout.isatty():
                from rich.console import Console
                from rich.table import Table

                table = Table(title="Groups", border_style="dim")
                table.add_column("ID", style="dim")
                table.add_column("Type")
                table.add_column("Strategy")
                table.add_column("Members", justify="right")
                table.add_column("Name")
                for row in rows:
                    subs = row["sub_label"]
                    tag = f"{row['profiles']}p" + (f" +{subs}" if subs else "")
                    table.add_row(row["id"], row["type"], row["strategy"], tag, row["name"])
                Console().print(table)
            else:
                for row in rows:
                    subs = row["sub_label"]
                    tag = f"{row['profiles']:>2}p" + (f" {subs}" if subs else "")
                    print(f"{row['id']}  {row['type']:<8} {row['strategy']:<10} {tag:<10} {row['name']}")
        else:
            print("no groups")
        return 0
    if action == "create":
        from .outbounds.groups import (
            classify_ids,
            create_balancer_group,
            create_chain_group,
        )

        # Auto-detect profile vs subscription IDs; --subscription flags are
        # still accepted and merged in for backward compatibility.
        profile_ids, sub_ids = classify_ids(store, args.profile_ids)
        for sid in getattr(args, "subscription_ids", []) or []:
            if sid not in sub_ids:
                sub_ids.append(sid)
        if args.group_create_command == "balancer":
            group = create_balancer_group(
                args.name, args.strategy, profile_ids, store,
                engine=args.engine, subscription_ids=sub_ids,
            )
        elif args.group_create_command == "chain":
            group = create_chain_group(
                args.name, profile_ids, store,
                engine=args.engine, subscription_ids=sub_ids,
            )
        else:
            return _command_help(args, "group create")
        store.add_group(group)
        store.save()
        print(group.id)
        return 0
    if action == "remove":
        if not store.remove_group(args.id):
            _not_found("group", args.id, store)
            return 1
        store.save()
        print(f"removed group {args.id}")
        return 0
    if action == "add-member":
        from .outbounds.groups import add_member, classify_id

        group = store.get_group(args.id)
        if group is None:
            _not_found("group", args.id, store)
            return 1
        added_p, added_s = 0, 0
        for pid in args.profile_ids:
            kind = classify_id(store, pid)
            if kind == "subscription":
                if pid not in group.subscription_ids:
                    group.subscription_ids.append(pid)
                    added_s += 1
            elif kind == "profile":
                if pid not in group.profile_ids:
                    add_member(group, pid)
                    added_p += 1
            else:
                raise ValueError(f"unknown id: {pid} (not a profile or subscription)")
        store.save()
        print(f"added {added_p} profile(s), {added_s} subscription(s) to {args.id}")
        return 0
    if action == "remove-member":
        from .outbounds.groups import classify_id, remove_member

        group = store.get_group(args.id)
        if group is None:
            _not_found("group", args.id, store)
            return 1
        removed_p, removed_s = 0, 0
        for pid in args.profile_ids:
            kind = classify_id(store, pid)
            if kind == "subscription":
                if pid in group.subscription_ids:
                    group.subscription_ids.remove(pid)
                    removed_s += 1
            elif kind == "profile":
                before = len(group.profile_ids)
                remove_member(group, pid)
                if len(group.profile_ids) < before:
                    removed_p += 1
        store.save()
        print(f"removed {removed_p} profile(s), {removed_s} subscription(s) from {args.id}")
        return 0
    if action == "add-sub":
        group = store.get_group(args.id)
        if group is None:
            _not_found("group", args.id, store)
            return 1
        added = 0
        for sub_id in args.subscription_ids:
            if store.get_subscription(sub_id) is None:
                _not_found("subscription", sub_id, store)
                return 1
            if sub_id not in group.subscription_ids:
                group.subscription_ids.append(sub_id)
                added += 1
        store.save()
        print(f"added {added} subscription(s) to {args.id}")
        return 0
    if action == "remove-sub":
        group = store.get_group(args.id)
        if group is None:
            _not_found("group", args.id, store)
            return 1
        removed = 0
        for sub_id in args.subscription_ids:
            if sub_id in group.subscription_ids:
                group.subscription_ids.remove(sub_id)
                removed += 1
        store.save()
        print(f"removed {removed} subscription(s) from {args.id}")
        return 0
    return _command_help(args, "group")


def _config_command(store: ConfigStore, args) -> int:
    action = args.config_command
    if action is None:
        action = "show"
    if action == "show":
        from .exchange import export_full

        print(json.dumps(export_full(store, redact=getattr(args, 'redact', False)), ensure_ascii=False, indent=2))
        return 0
    if action == "export":
        return _export(store, args.path, getattr(args, 'redact', False))
    if action == "import":
        return _import(store, args.path, args.replace)
    if action == "set":
        value: object
        try:
            value = json.loads(args.value)
        except json.JSONDecodeError:
            value = args.value
        key = args.key.split(".", 1)[1]
        if key in ("mixed_port", "socks_port", "http_port") and (isinstance(value, bool) or not isinstance(value, int)):
            raise ValueError(f"settings.{key} must be an integer")
        if key in ("mixed_port", "socks_port", "http_port") and isinstance(value, int) and not (0 <= value <= 65534):
            raise ValueError(f"settings.{key} must be between 0 and 65534 (0 = disabled; xray reserves mixed_port+1 for HTTP)")
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
    if action is None:
        action = "list"
    if action == "list":
        rows = [rule.to_dict() for rule in store.config.routing.rules]
        if getattr(args, 'json', False):
            print(json.dumps(rows, ensure_ascii=False))
        elif sys.stdout.isatty():
            from rich.console import Console
            from rich.table import Table

            mode_style = "[green]split[/green]" if store.config.routing.mode == "split" else "[dim]all[/dim]"
            table = Table(title=f"Routing — mode={mode_style}", border_style="dim")
            table.add_column("ID", style="dim")
            table.add_column("Action")
            table.add_column("Target")
            table.add_column("Match")
            for row in rows:
                target = row["target_id"] or "selected"
                match = row["match"]
                values = ", ".join(
                    f"{key}={','.join(value)}" for key, value in match.items() if value
                )
                action_style = {"proxy": "green", "direct": "yellow", "block": "red"}.get(row["action"], "")
                action = f"[{action_style}]{row['action']}[/{action_style}]" if action_style else row["action"]
                if not row.get("enabled", True):
                    action = f"[dim]{action} [disabled][/dim]"
                table.add_row(row["id"], action, target, values)
            Console().print(table)
        else:
            print(f"mode={store.config.routing.mode}")
            for row in rows:
                target = row["target_id"] or "selected"
                match = row["match"]
                values = ", ".join(
                    f"{key}={','.join(value)}" for key, value in match.items() if value
                )
                state = "" if row.get("enabled", True) else " [disabled]"
                print(f"{row['id']}  {row['action']:<6} {target:<36} {values}{state}")
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
            _not_found("rule", args.id, store)
            return 1
        store.save()
        print(f"removed rule {args.id}")
        return 0
    if action == "move":
        rules = store.config.routing.rules
        index = next((i for i, r in enumerate(rules) if r.id == args.id), None)
        if index is None:
            _not_found("rule", args.id, store)
            return 1
        swap = index - 1 if args.direction == "up" else index + 1
        if swap < 0 or swap >= len(rules):
            print(f"rule is already at the {args.direction} edge", file=sys.stderr)
            return 1
        rules[index], rules[swap] = rules[swap], rules[index]
        store.save()
        print(f"moved rule {args.id} {args.direction}")
        return 0
    if action in ("enable", "disable"):
        rule = next((r for r in store.config.routing.rules if r.id == args.id), None)
        if rule is None:
            _not_found("rule", args.id, store)
            return 1
        rule.enabled = action == "enable"
        store.save()
        state = "enabled" if rule.enabled else "disabled"
        print(f"{state} rule {args.id}")
        return 0
    return _command_help(args, "routing")


def _outbound_label(row: dict) -> str:
    """Render a server's outbound target including its ID.

    Examples: 'profile/002 (US proxy)', 'group/001 (mygroup)', 'direct (device)'.
    """
    if row["outbound_type"] == "direct":
        return "direct (device)"
    label = f"{row['outbound_type']}/{row['outbound_id']}"
    name = row.get("outbound_name") or ""
    if name and name != row["outbound_id"]:
        label += f" ({name})"
    return label


def _server_command(store: ConfigStore, args) -> int:
    from .models import Server

    action = args.server_command
    if action is None:
        action = "list"
    if action == "list":
        from .servers import ServerManager

        mgr = ServerManager(store)
        servers = store.list_servers()
        if getattr(args, 'running', False):
            running_ids = set(mgr.list_running())
            servers = [s for s in servers if s.id in running_ids]
        rows = []
        for s in servers:
            state = mgr.get_state(s.id)
            target_name = ""
            if s.outbound_type == "profile":
                p = store.get_profile(s.outbound_id)
                target_name = p.name if p else s.outbound_id
            elif s.outbound_type == "group":
                g = store.get_group(s.outbound_id)
                target_name = g.name if g else s.outbound_id
            elif s.outbound_type == "direct":
                target_name = "direct (device)"
            rows.append({
                "id": s.id, "name": s.name, "port": s.port,
                "protocol": s.protocol, "outbound_type": s.outbound_type,
                "outbound_id": s.outbound_id, "outbound_name": target_name,
                "enabled": s.enabled,
                "running": state.is_running() if state else False,
            })
        if getattr(args, 'json', False):
            print(json.dumps(rows, ensure_ascii=False))
        elif rows:
            if sys.stdout.isatty():
                from rich.console import Console
                from rich.table import Table

                table = Table(title="Servers", border_style="dim")
                table.add_column("ID", style="dim")
                table.add_column("Port", justify="right")
                table.add_column("Protocol")
                table.add_column("Status")
                table.add_column("Outbound")
                table.add_column("Name")
                for row in rows:
                    status = "[green]running[/green]" if row["running"] else "[dim]stopped[/dim]"
                    table.add_row(row["id"], str(row["port"]), row["protocol"], status, _outbound_label(row), row["name"])
                Console().print(table)
            else:
                for row in rows:
                    status = "running" if row["running"] else "stopped"
                    print(f"{row['id']}  :{row['port']:<5} {row['protocol']:<6} {status:<8} {_outbound_label(row)}")
        else:
            print("no servers")
        return 0

    if action == "add":
        server = Server(
            name=args.name,
            port=args.port,
            protocol=args.protocol,
            listen=args.listen,
        )
        if args.profile:
            profile = store.get_profile(args.profile)
            if profile is None:
                _not_found("profile", args.profile, store)
                return 1
            server.outbound_id = args.profile
            server.outbound_type = "profile"
        elif args.group:
            group = store.get_group(args.group)
            if group is None:
                _not_found("group", args.group, store)
                return 1
            server.outbound_id = args.group
            server.outbound_type = "group"
        else:
            server.outbound_type = "direct"
        store.add_server(server)
        store.save()
        print(server.id)
        return 0

    if action == "start":
        if getattr(args, "temp", False):
            return _temp_server_start(store, args)
        from .servers import ServerManager

        mgr = ServerManager(store)
        # Default to --all when no specific ID is given.
        if not args.id and not args.start_all:
            args.start_all = True
        if args.start_all:
            servers = [s for s in store.list_servers() if s.enabled]
            if not servers:
                print("no enabled servers")
                return 0
            failed = False
            for s in servers:
                try:
                    state = mgr.start(s.id)
                    if state.error:
                        failed = True
                        _status_line(s.id, "FAILED", state.error)
                    else:
                        _status_line(s.id, "started", f":{s.port}")
                except (ValueError, OSError) as exc:
                    failed = True
                    _status_line(s.id, "FAILED", str(exc))
            return 1 if failed else 0
        if not args.id:
            print("server start requires ID or --all", file=sys.stderr)
            return 2
        try:
            state = mgr.start(args.id)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if state.error:
            _status_line(state.server_id, "FAILED", state.error)
            return 1
        server = store.get_server(args.id)
        _status_line(state.server_id, "started", f":{server.port}")
        return 0

    if action == "stop":
        from .servers import ServerManager

        mgr = ServerManager(store)
        # Default to --all when no specific ID is given.
        if not args.id and not args.stop_all:
            args.stop_all = True
        if args.stop_all:
            count = mgr.stop_all()
            print(f"stopped {count} server(s)")
            return 0
        if not args.id:
            print("server stop requires ID or --all", file=sys.stderr)
            return 2
        if mgr.stop(args.id):
            print(f"stopped {args.id}")
        else:
            print(f"{args.id} is not running")
        return 0

    if action == "restart":
        from .servers import ServerManager

        mgr = ServerManager(store)
        if args.restart_all:
            servers = [s for s in store.list_servers() if s.enabled]
            if not servers:
                print("no enabled servers")
                return 0
            failed = False
            for s in servers:
                try:
                    mgr.stop(s.id)
                    state = mgr.start(s.id)
                    if state.error:
                        failed = True
                        _status_line(s.id, "FAILED", state.error)
                    else:
                        _status_line(s.id, "restarted", f":{s.port}")
                except (ValueError, OSError) as exc:
                    failed = True
                    _status_line(s.id, "FAILED", str(exc))
            return 1 if failed else 0
        if not args.id:
            print("server restart requires ID or --all", file=sys.stderr)
            return 2
        try:
            mgr.stop(args.id)
            state = mgr.start(args.id)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if state.error:
            _status_line(state.server_id, "FAILED", state.error)
            return 1
        server = store.get_server(args.id)
        _status_line(state.server_id, "restarted", f":{server.port}")
        return 0

    if action == "edit":
        from .servers import ServerManager

        server = store.get_server(args.id)
        if server is None:
            _not_found("server", args.id, store)
            return 1
        if args.name is not None:
            server.name = args.name
        if args.port is not None:
            server.port = args.port
        if args.protocol is not None:
            server.protocol = args.protocol
        if args.listen is not None:
            server.listen = args.listen
        if args.profile:
            profile = store.get_profile(args.profile)
            if profile is None:
                _not_found("profile", args.profile, store)
                return 1
            server.outbound_id = args.profile
            server.outbound_type = "profile"
        elif args.group:
            group = store.get_group(args.group)
            if group is None:
                _not_found("group", args.group, store)
                return 1
            server.outbound_id = args.group
            server.outbound_type = "group"
        elif args.direct:
            server.outbound_id = ""
            server.outbound_type = "direct"
        store.save()
        # Restart if the server was running so changes take effect.
        mgr = ServerManager(store)
        state = mgr.get_state(args.id)
        if state and state.is_running():
            mgr.stop(args.id)
            try:
                mgr.start(args.id)
                print(f"edited and restarted server {args.id}")
            except (ValueError, OSError) as exc:
                print(f"edited server {args.id} but restart failed: {exc}", file=sys.stderr)
        else:
            print(f"edited server {args.id}")
        return 0

    if action == "remove":
        from .servers import ServerManager

        mgr = ServerManager(store)
        mgr.stop(args.id)  # stop if running (ignore result)
        if not store.remove_server(args.id):
            _not_found("server", args.id, store)
            return 1
        store.save()
        print(f"removed server {args.id}")
        return 0

    return _command_help(args, "server")


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
    if sys.stdout.isatty():
        from rich.console import Console
        from rich.table import Table

        table = Table(title="Subscription Health", border_style="dim")
        table.add_column("Name")
        table.add_column("Status")
        table.add_column("Expiry")
        table.add_column("Traffic", justify="right")
        for status in statuses:
            if status["expired"]:
                state = "[bold red]EXPIRED[/bold red]"
            elif status["expiring"]:
                state = f"[yellow]expiring ({status['days_left']}d)[/yellow]"
            else:
                state = "[green]ok[/green]"
            expiry = status["expires"].strftime("%Y-%m-%d") if status["expires"] else "-"
            table.add_row(status["name"], state, expiry, human_bytes(status["traffic_used"]))
        Console().print(table)
    else:
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


def _resolve_test_scope(store: ConfigStore, scope: str):
    from .test.latency import select_profiles

    ids = [part.strip() for part in scope.split(",") if part.strip()]
    if scope.strip() == "all":
        return select_profiles(store, "all")
    if scope.strip() == "routing":
        return select_profiles(store, "routing_targets")
    if len(ids) == 1:
        if store.get_subscription(ids[0]) is not None:
            return select_profiles(store, ("subscription", ids[0]))
        if store.get_group(ids[0]) is not None:
            return select_profiles(store, ("group", ids[0]))
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
    except (OSError, ValueError, TypeError) as exc:
        print(f"restore failed: {exc}", file=sys.stderr)
        return 1
    print(f"restored from {path}")
    return 0


def _export(store: ConfigStore, path: str, redact: bool) -> int:
    from . import exchange

    try:
        exchange.export_full(store, path, redact=redact)
    except (OSError, ValueError, TypeError) as exc:
        print(f"export failed: {exc}", file=sys.stderr)
        return 1
    print(f"exported to {path}")
    return 0


def _import(store: ConfigStore, path: str, replace: bool) -> int:
    from . import exchange

    mode = "replace" if replace else "merge"
    try:
        exchange.import_full(store, path, mode=mode)
    except (OSError, ValueError, TypeError) as exc:
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


def _parse_proxy_url(proxy_url: str) -> tuple[str, int, str]:
    """Parse a proxy URL like socks5://host:port or http://host:port.

    Returns (host, port, protocol) where protocol is 'socks' or 'http'.
    """
    url = proxy_url.strip()
    # Determine protocol
    if url.startswith("socks5://"):
        protocol = "socks"
        url = url[len("socks5://") :]
    elif url.startswith("socks://"):
        protocol = "socks"
        url = url[len("socks://") :]
    elif url.startswith("http://"):
        protocol = "http"
        url = url[len("http://") :]
    elif url.startswith("https://"):
        protocol = "http"
        url = url[len("https://") :]
    else:
        raise ValueError(f"unsupported proxy scheme (use socks5:// or http://)")
    # Strip trailing slash
    url = url.rstrip("/")
    # Handle IPv6 [host]:port
    if url.startswith("["):
        bracket_end = url.find("]")
        if bracket_end < 0:
            raise ValueError("malformed proxy URL: missing ]")
        host = url[1:bracket_end]
        rest = url[bracket_end + 1 :]
        if rest.startswith(":"):
            port = int(rest[1:])
        else:
            raise ValueError("proxy URL requires port")
    else:
        # host:port
        if ":" not in url:
            raise ValueError("proxy URL requires port")
        host, port_str = url.rsplit(":", 1)
        port = int(port_str)
    if not host:
        raise ValueError("proxy URL requires a host")
    if not 1 <= port <= 65535:
        raise ValueError(f"proxy port must be 1-65535")
    return host, port, protocol


def _temp_server_start(store: ConfigStore, args) -> int:
    """Start a temporary server that runs until Ctrl+C."""
    from .models import Server, Settings
    from .servers import ServerManager
    from .outbounds.manual import add_socks_proxy, add_http_proxy

    # Build an in-memory Server object (never saved to config)
    server = Server(
        name="temporary",
        port=args.port,
        protocol=args.protocol,
        listen=args.listen,
    )

    if args.profile:
        profile = store.get_profile(args.profile)
        if profile is None:
            _not_found("profile", args.profile, store)
            return 1
        server.outbound_id = args.profile
        server.outbound_type = "profile"
    elif args.group:
        group = store.get_group(args.group)
        if group is None:
            _not_found("group", args.group, store)
            return 1
        server.outbound_id = args.group
        server.outbound_type = "group"
    elif args.proxy:
        host, port, proto = _parse_proxy_url(args.proxy)
        # Create a temporary in-memory profile for this proxy
        if proto == "socks":
            tmp_profile = add_socks_proxy("temp-proxy", host, port)
        else:
            tmp_profile = add_http_proxy("temp-proxy", host, port)
        store.add_profile(tmp_profile)
        server.outbound_id = tmp_profile.id
        server.outbound_type = "profile"
    else:
        print("--temp requires --profile, --group, or --proxy", file=sys.stderr)
        return 2

    mgr = ServerManager(store)
    # Generate config and start the engine
    try:
        config_json, target_engine = mgr._generate_server_config(server)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    import json as _json
    from pathlib import Path
    from .engines import get_adapter
    from .engines.binary import locate_binary

    runtime_dir = mgr.runtime_dir / "temp"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    config_path = runtime_dir / "config.json"
    config_path.write_text(_json.dumps(config_json, indent=2) + "\n", encoding="utf-8")

    try:
        binary = locate_binary(
            target_engine,
            store.config.engines.get(target_engine, {}),
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    adapter = get_adapter(target_engine)
    argv = [str(binary), *adapter.run_args(str(config_path))]

    proc = mgr._spawn(argv, runtime_dir, capture_stderr=True)
    # Brief pause to catch engines that crash immediately
    for _ in range(10):
        if proc.poll() is not None:
            break
        time.sleep(0.1)

    if proc.poll() is not None:
        stderr_lines = getattr(proc, "_captured_stderr", [])
        detail = " ".join(stderr_lines[-3:]) if stderr_lines else f"exit code {proc.returncode}"
        print(f"error: engine exited immediately: {detail}", file=sys.stderr)
        _cleanup_temp_proxy(store, args)
        return 1

    proto_display = args.protocol
    print(f"temporary {proto_display} server listening on {args.listen}:{args.port}")
    print(f"engine: {target_engine}  pid: {proc.pid}")
    print("press Ctrl+C to stop")

    try:
        while proc.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        import signal
        try:
            os.kill(proc.pid, signal.SIGTERM)
            for _ in range(20):
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
            if proc.poll() is None:
                os.kill(proc.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        _cleanup_temp_proxy(store, args)
        print("stopped")
    return 0


def _cleanup_temp_proxy(store: ConfigStore, args) -> None:
    """Remove temporary proxy profile created by --proxy."""
    if args.proxy:
        # Find and remove the temp profile we added
        for p in list(store.config.profiles):
            if p.name == "temp-proxy" and p.source == "manual":
                store.remove_profile(p.id)
                break


def _status_line(server_id: str, action: str, detail: str = "") -> None:
    """Print a color-coded server status line."""
    if sys.stdout.isatty():
        color = {"started": "32", "restarted": "33", "stopped": "33", "FAILED": "31"}.get(action, "0")
        print(f"\033[1m{server_id}\033[0m  \033[{color}m{action}\033[0m  {detail}")
    else:
        print(f"{server_id}  {action}  {detail}")


def _summary(store: ConfigStore) -> int:
    conf = store.config
    if sys.stdout.isatty():
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table

        console = Console()
        table = Table(title=None, show_header=False, box=None, padding=(0, 1))
        table.add_column("", style="bold")
        table.add_column("")
        table.add_row("version", f"v{__version__}")
        table.add_row("config", str(store.path))
        table.add_row("profiles", str(len(conf.profiles)))
        table.add_row("subscriptions", str(len(conf.subscriptions)))
        table.add_row("groups", str(len(conf.groups)))
        table.add_row("servers", str(len(conf.servers)))
        table.add_row("routing mode", conf.routing.mode)
        console.print(Panel(table, title=f"v2raycli v{__version__}", border_style="blue"))
    else:
        print(f"v2raycli v{__version__}")
        print(f"config: {store.path}")
        print(
            f"profiles: {len(conf.profiles)}  "
            f"subscriptions: {len(conf.subscriptions)}  "
            f"groups: {len(conf.groups)}"
        )
    return 0


BASH_COMPLETION = '''# v2raycli bash completion — add to ~/.bashrc or ~/.bash_completion
_v2raycli_complete() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    local line="${COMP_LINE}"
    local completions
    completions=($(v2raycli completion --complete "$line"))
    COMPREPLY=($(compgen -W "${completions[*]}" -- "$cur"))
    return 0
}
complete -F _v2raycli_complete v2raycli
'''

ZSH_COMPLETION = '''#compdef v2raycli
# v2raycli zsh completion — source from ~/.zshrc
_v2raycli() {
    local -a completions
    local line="${words[*]}"
    completions=(${(f)"$(v2raycli completion --complete "$line")"})
    compadd -a completions
}
_v2raycli
'''


def _completion_command(args) -> int:
    """Handle the completion command.

    Without --complete, prints the shell script to stdout.
    With --complete LINE, performs actual completion.
    """
    if args.complete_line:
        return _do_complete(args.complete_line[0])
    if args.shell == "bash":
        print(BASH_COMPLETION)
    elif args.shell == "zsh":
        print(ZSH_COMPLETION)
    return 0


def _do_complete(raw_line: str) -> int:
    """Perform actual word completion.

    The line is the raw COMP_WORDS[*] from bash (words joined by spaces).
    We detect the prefix and completed words from it.
    """
    trailing_space = raw_line.endswith(" ")
    # Split into words; if trailing space, last "word" would be empty, so split captures it.
    parts = raw_line.strip().split() if trailing_space else raw_line.rstrip().split()
    if not parts or parts[0] != "v2raycli":
        return 0

    words = parts[1:]  # all words after "v2raycli"
    if trailing_space:
        prefix = ""
    else:
        prefix = words[-1] if words else ""
        words = words[:-1] if words else []

    # Walk completed words to the deepest subparser.
    parser = build_parser()
    current = _walk_parser(parser, words)

    # Collect completions at this level filtered by prefix.
    completions = _collect_actions(current)

    # If prefix exactly matches a subcommand, also show its children.
    for c in sorted(set(completions)):
        if c == prefix:
            sub = _walk_parser(current, [prefix])
            completions = list(set(completions + _collect_actions(sub)))
            break

    for c in sorted(set(completions)):
        if c.startswith(prefix):
            print(c)
    return 0


def _walk_parser(parser: argparse.ArgumentParser, words: list[str]) -> argparse.ArgumentParser:
    """Walk completed words through the parser tree."""
    current = parser
    for word in words:
        found = False
        for action in current._actions:  # type: ignore[attr-defined]
            if isinstance(action, argparse._SubParsersAction):
                if word in action._name_parser_map:
                    current = action._name_parser_map[word]
                    found = True
                    break
        if not found:
            break
    return current


def _collect_actions(parser: argparse.ArgumentParser) -> list[str]:
    """Collect available subcommands and option strings from a parser."""
    completions: list[str] = []
    for action in parser._actions:  # type: ignore[attr-defined]
        if isinstance(action, argparse._SubParsersAction):
            completions.extend(action._name_parser_map.keys())
        else:
            for opt in (action.option_strings or []):
                completions.append(opt)
            if action.choices:
                completions.extend(action.choices)
    return completions


def _print_completions(completions: list[str], prefix: str) -> None:
    """Print completions that match the current partial word."""
    for c in sorted(set(completions)):
        if c.startswith(prefix):
            print(c)


if __name__ == "__main__":
    raise SystemExit(main())
