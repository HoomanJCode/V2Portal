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
        "--headless", action="store_true",
        help="[deprecated] print a summary and exit (legacy alias for 'status')",
    )
    parser.add_argument(
        "--test",
        metavar="SCOPE",
        help="[deprecated] latency-test outbounds (use 'test latency' command)",
    )
    parser.add_argument(
        "--probe",
        metavar="SCOPE",
        help="[deprecated] probe endpoints (use 'test endpoint' command)",
    )
    parser.add_argument(
        "--ws-test",
        metavar="SCOPE",
        help="[deprecated] websocket test (use 'test websocket' command)",
    )
    parser.add_argument(
        "--update",
        choices=("sing-box", "xray", "both"),
        metavar="ENGINE",
        help="[deprecated] update engines (use 'engine update' command)",
    )
    parser.add_argument(
        "--proxy",
        metavar="URL",
        help="ephemeral HTTP/SOCKS proxy for engine updates (not stored)",
    )
    parser.add_argument("--backup", action="store_true",
                        help="[deprecated] create a backup (use 'backup create')")
    parser.add_argument("--list-backups", action="store_true",
                        help="[deprecated] list backups (use 'backup list')")
    parser.add_argument("--restore", metavar="PATH",
                        help="[deprecated] restore backup (use 'backup restore')")
    parser.add_argument("--export", metavar="PATH",
                        help="[deprecated] export config (use 'config export')")
    parser.add_argument(
        "--redact", action="store_true",
        help="[deprecated] mask credentials (use with 'config export')",
    )
    parser.add_argument(
        "--import", dest="import_path", metavar="PATH",
        help="[deprecated] import config (use 'config import')",
    )
    parser.add_argument(
        "--replace", action="store_true",
        help="[deprecated] replace on import (use 'config import --replace')",
    )
    parser.add_argument(
        "--install-service",
        metavar="ID",
        help="[deprecated] install boot service (use 'service install')",
    )
    parser.add_argument(
        "--uninstall-service", action="store_true",
        help="[deprecated] remove boot service (use 'service uninstall')",
    )
    parser.add_argument(
        "--health", action="store_true",
        help="[deprecated] show subscription health (use 'health' command)",
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
        "subscription", aliases=["subscriptions"],
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
            "  v2raycli group create chain tunnel ID_A ID_B"
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
            "Create a balancer group. Requires a name and 2+ profile IDs.\n\n"
            "  latency      — pick the lowest-latency profile (sing-box urltest)\n"
            "  random       — pick a random profile\n"
            "  roundRobin   — rotate through profiles in order\n"
            "  leastLoad    — pick the least-loaded (forces xray engine)\n\n"
            "Examples:\n"
            "  v2raycli group create balancer fast ID_A ID_B --strategy latency\n"
            "  v2raycli group create balancer pool ID_A ID_B ID_C --strategy random"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    balancer.add_argument("name", help="display name for this group")
    balancer.add_argument("profile_ids", nargs="+",
                         help="2+ profile IDs that are candidates for this balancer")
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
            "listed in hop order. Traffic flows through the first proxy,\n"
            "then the second, and so on.\n\n"
            "Example:\n"
            "  v2raycli group create chain tunnel ID_A ID_B"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    chain.add_argument("name", help="display name for this group")
    chain.add_argument("profile_ids", nargs="+",
                      help="ordered list of profile IDs forming the chain")
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

    # -- test -----------------------------------------------------------------
    test = commands.add_parser(
        "test",
        help="test proxy outbounds (latency, reachability, websocket)",
        description=(
            "Test profiles to measure latency, check endpoint reachability,\n"
            "or validate WebSocket handshakes. Scope can be 'all', a\n"
            "subscription ID, or a comma-separated list of profile IDs.\n\n"
            "Examples:\n"
            "  v2raycli test latency all\n"
            "  v2raycli test latency SUB_ID\n"
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
        "server",
        help="manage inbound proxy servers (multiple ports, each with its own outbound)",
        description=(
            "A server is a persistent inbound proxy that listens on a dedicated port\n"
            "and forwards traffic to a specific profile or group. Multiple servers\n"
            "can run simultaneously, each on its own port.\n\n"
            "Examples:\n"
            "  v2raycli server add --port 1080 --profile abc --name 'US proxy'\n"
            "  v2raycli server add --port 1081 --group def --protocol http\n"
            "  v2raycli server list\n"
            "  v2raycli server start SERVER_ID\n"
            "  v2raycli server stop SERVER_ID\n"
            "  v2raycli server stop --all"
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
    server_outbound = server_add.add_mutually_exclusive_group(required=True)
    server_outbound.add_argument("--profile", help="profile ID to forward to")
    server_outbound.add_argument("--group", help="group ID to forward to")
    server_add.add_argument("--name", default="", help="display name for this server")
    server_add.add_argument("--protocol", choices=("mixed", "socks", "http"), default="mixed",
                           help="inbound protocol (default: mixed)")
    server_add.add_argument("--listen", default="0.0.0.0", help="listen address (default: 0.0.0.0)")

    server_start = server_commands.add_parser(
        "start",
        help="start a server (or --all)",
        description=(
            "Start a server's engine process. The server must be added first.\n\n"
            "Examples:\n"
            "  v2raycli server start SERVER_ID\n"
            "  v2raycli server start --all"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    server_start.add_argument("id", nargs="?", help="server ID to start (or use --all)")
    server_start.add_argument("--all", action="store_true", dest="start_all",
                             help="start all enabled servers")

    server_stop = server_commands.add_parser(
        "stop",
        help="stop a running server (or --all)",
        description=(
            "Stop a running server's engine process.\n\n"
            "Examples:\n"
            "  v2raycli server stop SERVER_ID\n"
            "  v2raycli server stop --all"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    server_stop.add_argument("id", nargs="?", help="server ID to stop (or use --all)")
    server_stop.add_argument("--all", action="store_true", dest="stop_all",
                            help="stop all running servers")

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
        # Only show health warnings on status/health, not every command.
        if args.command in ("status", "health") and not args.no_auto_update:
            _health_check(store)
        return _command(store, args)

    if not args.no_auto_update:
        _auto_update(store)
        _health_check(store)

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
        if command == "server":
            return _server_command(store, args)
        if command == "health":
            return _health_command(store, args.json)
        return _command_help(args)
    except (OSError, ValueError, TypeError, KeyError, V2RayCLIError) as exc:
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
            print(f"unknown rule id: {args.id}", file=sys.stderr)
            return 1
        store.save()
        print(f"removed rule {args.id}")
        return 0
    if action == "move":
        rules = store.config.routing.rules
        index = next((i for i, r in enumerate(rules) if r.id == args.id), None)
        if index is None:
            print(f"unknown rule id: {args.id}", file=sys.stderr)
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
            print(f"unknown rule id: {args.id}", file=sys.stderr)
            return 1
        rule.enabled = action == "enable"
        store.save()
        state = "enabled" if rule.enabled else "disabled"
        print(f"{state} rule {args.id}")
        return 0
    return _command_help(args, "routing")


def _server_command(store: ConfigStore, args) -> int:
    from .models import Server

    action = args.server_command
    if action == "list":
        from .servers import ServerManager

        mgr = ServerManager(store)
        servers = store.list_servers()
        if args.running:
            running_ids = set(mgr.list_running())
            servers = [s for s in servers if s.id in running_ids]
        rows = []
        for s in servers:
            state = mgr.get_state(s.id)
            rows.append({
                "id": s.id, "name": s.name, "port": s.port,
                "protocol": s.protocol, "outbound_type": s.outbound_type,
                "outbound_id": s.outbound_id, "enabled": s.enabled,
                "running": state.is_running() if state else False,
            })
        if args.json:
            print(json.dumps(rows, ensure_ascii=False))
        elif rows:
            for row in rows:
                status = "running" if row["running"] else "stopped"
                print(f"{row['id']}  :{row['port']:<5} {row['protocol']:<6} {row['outbound_type']:<8} {status:<8} {row['name']}")
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
                print(f"unknown profile id: {args.profile}", file=sys.stderr)
                return 1
            server.outbound_id = args.profile
            server.outbound_type = "profile"
        else:
            group = store.get_group(args.group)
            if group is None:
                print(f"unknown group id: {args.group}", file=sys.stderr)
                return 1
            server.outbound_id = args.group
            server.outbound_type = "group"
        store.add_server(server)
        store.save()
        print(server.id)
        return 0

    if action == "start":
        from .servers import ServerManager

        mgr = ServerManager(store)
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
                        print(f"{s.id}  failed: {state.error}", file=sys.stderr)
                    else:
                        print(f"{s.id}  started on :{s.port}")
                except (ValueError, OSError) as exc:
                    failed = True
                    print(f"{s.id}  failed: {exc}", file=sys.stderr)
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
            print(f"failed: {state.error}", file=sys.stderr)
            return 1
        server = store.get_server(args.id)
        print(f"{state.server_id}  started on :{server.port}")
        return 0

    if action == "stop":
        from .servers import ServerManager

        mgr = ServerManager(store)
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

    if action == "remove":
        from .servers import ServerManager

        mgr = ServerManager(store)
        mgr.stop(args.id)  # stop if running (ignore result)
        if not store.remove_server(args.id):
            print(f"unknown server id: {args.id}", file=sys.stderr)
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
