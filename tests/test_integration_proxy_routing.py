"""Integration tests: proxy profiles → servers → config generation → split routing.

Covers the full flow of adding SOCKS/HTTP proxy profiles, creating inbound
servers that reference them, verifying the generated engine configs route
traffic to the correct outbounds, and testing split-routing rules that
distribute traffic across multiple outbound targets.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from v2portal import app
from v2portal.engines import get_adapter
from v2portal.models import Group, Profile, RoutingConfig, RoutingRule, Server, Settings
from v2portal.outbounds.groups import (
    enrich_target_with_routing,
    resolve_refs,
    resolve_target,
)
from v2portal.routing.rules import add_rule
from v2portal.servers import ServerManager
from v2portal.storage import ConfigStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SOCKS_OUTBOUND = {"settings": {"servers": [{"address": "10.0.0.1", "port": 1080}]}}
HTTP_OUTBOUND = {"settings": {"servers": [{"address": "10.0.0.2", "port": 8080}]}}

VMESS_OUTBOUND = {
    "settings": {
        "vnext": [
            {
                "address": "vmess.example.com",
                "port": 443,
                "users": [
                    {"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "alterId": 0, "security": "auto"}
                ],
            }
        ]
    },
    "streamSettings": {"network": "tcp"},
}

VLESS_OUTBOUND = {
    "settings": {
        "vnext": [
            {
                "address": "vless.example.com",
                "port": 443,
                "users": [{"id": "11111111-2222-3333-4444-555555555555"}],
            }
        ]
    },
    "streamSettings": {"network": "tcp"},
}


def _store(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    return store


def _generate(store, selection, default="sing-box"):
    target = resolve_target(store, selection, default_engine=default)
    adapter = get_adapter(target.engine)
    return adapter.generate(store.config.settings, store.config.routing, target)


# ===========================================================================
# 1. Add SOCKS/HTTP proxy profiles
# ===========================================================================


class TestAddProxyProfiles:
    """Verify SOCKS and HTTP proxy profiles can be added and persisted."""

    def test_add_socks_profile_via_cli(self, tmp_path, capsys):
        store = _store(tmp_path)
        args = app.build_parser().parse_args(
            ["profile", "add", "socks", "office-proxy", "10.0.0.1", "1080"]
        )
        assert app._profile_command(store, args) == 0
        profiles = store.list_profiles()
        assert len(profiles) == 1
        p = profiles[0]
        assert p.kind == "socks"
        assert p.name == "office-proxy"
        assert p.outbound["settings"]["servers"][0]["address"] == "10.0.0.1"
        assert p.outbound["settings"]["servers"][0]["port"] == 1080

    def test_add_http_profile_via_cli(self, tmp_path, capsys):
        store = _store(tmp_path)
        args = app.build_parser().parse_args(
            ["profile", "add", "http", "corporate-http", "10.0.0.2", "8080"]
        )
        assert app._profile_command(store, args) == 0
        profiles = store.list_profiles()
        assert len(profiles) == 1
        p = profiles[0]
        assert p.kind == "http"
        assert p.outbound["settings"]["servers"][0]["address"] == "10.0.0.2"

    def test_add_socks_profile_with_auth(self, tmp_path, capsys):
        store = _store(tmp_path)
        args = app.build_parser().parse_args(
            ["profile", "add", "socks", "auth-proxy", "10.0.0.3", "1080",
             "--username", "user1", "--password", "pass1"]
        )
        assert app._profile_command(store, args) == 0
        p = store.list_profiles()[0]
        users = p.outbound["settings"]["servers"][0]["users"]
        assert users == [{"user": "user1", "pass": "pass1"}]

    def test_add_multiple_proxies_persist(self, tmp_path):
        store = _store(tmp_path)
        p1 = store.add_profile(
            Profile(name="socks1", kind="socks", outbound=SOCKS_OUTBOUND)
        )
        p2 = store.add_profile(
            Profile(name="http1", kind="http", outbound=HTTP_OUTBOUND)
        )
        store.save()

        store2 = ConfigStore(tmp_path / "config.json")
        store2.load()
        assert len(store2.list_profiles()) == 2
        kinds = {p.kind for p in store2.list_profiles()}
        assert kinds == {"socks", "http"}


# ===========================================================================
# 2. Create servers referencing proxy profiles
# ===========================================================================


class TestCreateServers:
    """Verify inbound servers can be created referencing proxy profiles."""

    def test_server_add_socks_profile_ref(self, tmp_path, capsys):
        store = _store(tmp_path)
        p = store.add_profile(Profile(name="my-socks", kind="socks", outbound=SOCKS_OUTBOUND))
        store.save()

        args = app.build_parser().parse_args(
            ["server", "add", "--port", "11080", p.id]
        )
        assert app._server_command(store, args) == 0
        servers = store.list_servers()
        assert len(servers) == 1
        s = servers[0]
        assert s.port == 11080
        assert s.outbound_type == "profile"
        assert s.outbound_id == p.id

    def test_server_add_http_profile_ref(self, tmp_path, capsys):
        store = _store(tmp_path)
        p = store.add_profile(Profile(name="my-http", kind="http", outbound=HTTP_OUTBOUND))
        store.save()

        args = app.build_parser().parse_args(
            ["server", "add", "--port", "18080", "--protocol", "http", p.id]
        )
        assert app._server_command(store, args) == 0
        s = store.list_servers()[0]
        assert s.protocol == "http"
        assert s.outbound_id == p.id

    def test_server_add_direct_outbound(self, tmp_path, capsys):
        store = _store(tmp_path)
        args = app.build_parser().parse_args(
            ["server", "add", "--port", "12080", "--direct"]
        )
        assert app._server_command(store, args) == 0
        s = store.list_servers()[0]
        assert s.outbound_type == "direct"

    def test_server_add_balancer_group_ref(self, tmp_path, capsys):
        store = _store(tmp_path)
        p1 = store.add_profile(Profile(name="us", kind="socks", outbound=SOCKS_OUTBOUND))
        p2 = store.add_profile(Profile(name="eu", kind="socks", outbound=SOCKS_OUTBOUND))
        g = store.add_group(
            Group(name="fast", type="balancer", strategy="latency", profile_ids=[p1.id, p2.id])
        )
        store.save()

        args = app.build_parser().parse_args(
            ["server", "add", "--port", "13080", g.id]
        )
        assert app._server_command(store, args) == 0
        s = store.list_servers()[0]
        assert s.outbound_type == "group"
        assert s.outbound_id == g.id

    def test_two_servers_on_different_ports(self, tmp_path):
        store = _store(tmp_path)
        p1 = store.add_profile(Profile(name="us", kind="socks", outbound=SOCKS_OUTBOUND))
        p2 = store.add_profile(Profile(name="eu", kind="http", outbound=HTTP_OUTBOUND))
        s1 = store.add_server(
            Server(name="us-server", port=11080, outbound_id=p1.id, outbound_type="profile")
        )
        s2 = store.add_server(
            Server(name="eu-server", port=12080, outbound_id=p2.id, outbound_type="profile")
        )
        store.save()

        store2 = ConfigStore(tmp_path / "config.json")
        store2.load()
        assert len(store2.list_servers()) == 2
        ports = {s.port for s in store2.list_servers()}
        assert ports == {11080, 12080}


# ===========================================================================
# 3. Server config generation → verify routing to outbounds
# ===========================================================================


class TestServerConfigGeneration:
    """Verify generated engine configs route to the correct outbound targets."""

    def test_socks_server_routes_to_socks_outbound(self, tmp_path):
        store = _store(tmp_path)
        p = store.add_profile(Profile(name="us-proxy", kind="socks", outbound=SOCKS_OUTBOUND))
        server = store.add_server(
            Server(name="s1", port=11080, outbound_id=p.id, outbound_type="profile")
        )
        mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")
        config, engine = mgr._generate_server_config(server)

        # The outbound for the socks profile should be present.
        outbounds = config.get("outbounds", [])
        tags = [o.get("tag") for o in outbounds]
        assert p.id in tags
        # The selected outbound should be the socks profile.
        socksb = next(o for o in outbounds if o.get("tag") == p.id)
        assert socksb.get("type") == "socks"
        assert socksb.get("server") == "10.0.0.1"
        assert socksb.get("server_port") == 1080
        # Route final should point to the socks outbound.
        assert config.get("route", {}).get("final") == p.id

    def test_http_server_routes_to_http_outbound(self, tmp_path):
        store = _store(tmp_path)
        p = store.add_profile(
            Profile(name="corp-proxy", kind="http", outbound=HTTP_OUTBOUND)
        )
        server = store.add_server(
            Server(name="s1", port=18080, outbound_id=p.id, outbound_type="profile",
                   protocol="http")
        )
        mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")
        config, engine = mgr._generate_server_config(server)

        outbounds = config.get("outbounds", [])
        tags = [o.get("tag") for o in outbounds]
        assert p.id in tags
        httpb = next(o for o in outbounds if o.get("tag") == p.id)
        assert httpb.get("type") == "http"
        assert httpb.get("server") == "10.0.0.2"
        assert httpb.get("server_port") == 8080

    def test_balancer_server_routes_to_all_members(self, tmp_path, monkeypatch):
        """Balancer server config includes all member outbounds."""
        from v2portal.test import latency

        store = _store(tmp_path)
        p1 = store.add_profile(Profile(name="us", kind="socks", outbound=SOCKS_OUTBOUND))
        p2 = store.add_profile(Profile(name="eu", kind="socks", outbound=SOCKS_OUTBOUND))
        group = store.add_group(
            Group(name="fast", type="balancer", strategy="latency", profile_ids=[p1.id, p2.id])
        )
        server = store.add_server(
            Server(name="s1", port=13080, outbound_id=group.id, outbound_type="group")
        )

        # Mock endpoint probe — both alive, p1 faster.
        from tests.test_servers import _probe_result
        monkeypatch.setattr(
            latency, "probe_endpoint",
            lambda profile, timeout=5.0: (
                _probe_result(profile, 10.0) if profile.id == p1.id
                else _probe_result(profile, 100.0)
            ),
        )

        mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")
        config, engine = mgr._generate_server_config(server)

        outbounds = config.get("outbounds", [])
        tags = [o.get("tag") for o in outbounds]
        # Pinned mode: only the fastest member is in the config.
        assert p1.id in tags
        assert p2.id not in tags  # unpinned members are dropped
        # The pinned node should be the fastest.
        assert mgr.selected_pinned is not None
        assert mgr.selected_pinned.id == p1.id

    def test_direct_server_has_no_proxy_outbound(self, tmp_path):
        store = _store(tmp_path)
        server = store.add_server(
            Server(name="direct", port=14080, outbound_type="direct")
        )
        mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")
        config, engine = mgr._generate_server_config(server)

        outbounds = config.get("outbounds", [])
        # Should only have a direct/block fallback, no socks/vmess outbounds.
        proxy_types = {o.get("type") for o in outbounds} - {"direct", "block", "selector", "urltest"}
        assert not proxy_types


# ===========================================================================
# 4. Split routing rules — traffic over multiple outbounds
# ===========================================================================


class TestSplitRouting:
    """Verify split-routing rules distribute traffic to different outbounds."""

    def test_direct_rule_bypasses_proxy(self, tmp_path):
        """Domain matching a 'direct' rule goes direct, not through the proxy."""
        store = _store(tmp_path)
        p = store.add_profile(Profile(name="proxy", kind="socks", outbound=SOCKS_OUTBOUND))
        store.config.routing = RoutingConfig(
            mode="split",
            rules=[add_rule("direct", {"domains": ["example.com"]})],
        )
        target = resolve_target(store, p, default_engine="sing-box")
        target = enrich_target_with_routing(target, store.config.routing, store)
        adapter = get_adapter("sing-box")
        config = adapter.generate(store.config.settings, store.config.routing, target)

        rules = config.get("route", {}).get("rules", [])
        # The direct rule should exist with outbound "direct".
        direct_rules = [r for r in rules if r.get("outbound") == "direct"]
        assert len(direct_rules) >= 1
        # The domain matcher should be present.
        assert any(
            "example.com" in r.get("domain_suffix", [])
            for r in direct_rules
        )

    def test_block_rule_blocks_traffic(self, tmp_path):
        """Domain matching a 'block' rule should be blocked."""
        store = _store(tmp_path)
        p = store.add_profile(Profile(name="proxy", kind="socks", outbound=SOCKS_OUTBOUND))
        store.config.routing = RoutingConfig(
            mode="split",
            rules=[add_rule("block", {"domains": ["keyword:ads"]})],
        )
        target = resolve_target(store, p, default_engine="sing-box")
        target = enrich_target_with_routing(target, store.config.routing, store)
        adapter = get_adapter("sing-box")
        config = adapter.generate(store.config.settings, store.config.routing, target)

        rules = config.get("route", {}).get("rules", [])
        block_rules = [r for r in rules if r.get("outbound") == "block"]
        assert len(block_rules) >= 1

    def test_proxy_rule_routes_to_specific_profile(self, tmp_path):
        """A 'proxy' rule with a target_id routes matching traffic to that profile."""
        store = _store(tmp_path)
        main = store.add_profile(Profile(name="main", kind="socks", outbound=SOCKS_OUTBOUND))
        netflix = store.add_profile(
            Profile(name="netflix-proxy", kind="socks", outbound=HTTP_OUTBOUND)
        )
        store.config.routing = RoutingConfig(
            mode="split",
            rules=[add_rule("proxy", {"domains": ["netflix.com"]}, target_id=netflix.id)],
        )

        target = resolve_target(store, main, default_engine="sing-box")
        target = enrich_target_with_routing(target, store.config.routing, store)
        adapter = get_adapter("sing-box")
        config = adapter.generate(store.config.settings, store.config.routing, target)

        outbounds = config.get("outbounds", [])
        tags = [o.get("tag") for o in outbounds]
        # Both main and netflix outbounds should be present.
        assert main.id in tags
        assert netflix.id in tags
        # The routing rule should point to the netflix profile.
        rules = config.get("route", {}).get("rules", [])
        proxy_to_netflix = [
            r for r in rules
            if r.get("outbound") == netflix.id
            or r.get("outboundTag") == netflix.id
        ]
        assert len(proxy_to_netflix) >= 1

    def test_split_traffic_across_three_outbounds(self, tmp_path):
        """Three different routing rules each route to a different outbound."""
        store = _store(tmp_path)
        main = store.add_profile(Profile(name="default", kind="socks", outbound=SOCKS_OUTBOUND))
        streaming = store.add_profile(
            Profile(name="streaming", kind="socks", outbound=HTTP_OUTBOUND)
        )
        gaming = store.add_profile(
            Profile(name="gaming", kind="vmess", outbound=VMESS_OUTBOUND)
        )
        store.config.routing = RoutingConfig(
            mode="split",
            rules=[
                add_rule("proxy", {"domains": ["netflix.com", "disney.com"]}, target_id=streaming.id),
                add_rule("proxy", {"domains": ["steam.com", "epic.com"]}, target_id=gaming.id),
                add_rule("direct", {"ips": ["192.168.0.0/16"]}),
            ],
        )

        target = resolve_target(store, main, default_engine="sing-box")
        target = enrich_target_with_routing(target, store.config.routing, store)
        adapter = get_adapter("sing-box")
        config = adapter.generate(store.config.settings, store.config.routing, target)

        outbounds = config.get("outbounds", [])
        tags = [o.get("tag") for o in outbounds]
        # All three outbounds should be in the config.
        assert main.id in tags
        assert streaming.id in tags
        assert gaming.id in tags
        # The direct rule should be present.
        rules = config.get("route", {}).get("rules", [])
        assert any(r.get("outbound") == "direct" for r in rules)

    def test_ip_cidr_direct_rule(self, tmp_path):
        """IP CIDR matching a direct rule bypasses the proxy."""
        store = _store(tmp_path)
        p = store.add_profile(Profile(name="proxy", kind="socks", outbound=SOCKS_OUTBOUND))
        store.config.routing = RoutingConfig(
            mode="split",
            rules=[add_rule("direct", {"ips": ["10.0.0.0/8", "192.168.0.0/16"]})],
        )

        target = resolve_target(store, p, default_engine="sing-box")
        target = enrich_target_with_routing(target, store.config.routing, store)
        adapter = get_adapter("sing-box")
        config = adapter.generate(store.config.settings, store.config.routing, target)

        rules = config.get("route", {}).get("rules", [])
        direct_rules = [r for r in rules if r.get("outbound") == "direct"]
        assert len(direct_rules) >= 1
        # IP CIDR matchers should be present.
        ip_rules = [r for r in direct_rules if r.get("ip_cidr") or r.get("ip_is_private")]
        assert len(ip_rules) >= 1

    def test_balancer_as_routing_target(self, tmp_path):
        """A proxy rule can target a balancer group, splitting traffic across its members."""
        store = _store(tmp_path)
        main = store.add_profile(Profile(name="default", kind="socks", outbound=SOCKS_OUTBOUND))
        us = store.add_profile(Profile(name="us", kind="socks", outbound=SOCKS_OUTBOUND))
        eu = store.add_profile(Profile(name="eu", kind="socks", outbound=SOCKS_OUTBOUND))
        bal = store.add_group(
            Group(name="fast", type="balancer", strategy="latency", profile_ids=[us.id, eu.id])
        )
        store.config.routing = RoutingConfig(
            mode="split",
            rules=[add_rule("proxy", {"domains": ["streaming.com"]}, target_id=bal.id)],
        )

        target = resolve_target(store, main, default_engine="sing-box")
        target = enrich_target_with_routing(target, store.config.routing, store)
        adapter = get_adapter("sing-box")
        config = adapter.generate(store.config.settings, store.config.routing, target)

        outbounds = config.get("outbounds", [])
        tags = [o.get("tag") for o in outbounds]
        # Both balancer members should be present.
        assert us.id in tags
        assert eu.id in tags
        # The balancer group itself should have a urltest/selector construct.
        bal_out = [
            o for o in outbounds
            if o.get("tag") == bal.id and o.get("type") in ("urltest", "selector")
        ]
        assert len(bal_out) >= 1

    def test_subscription_profiles_routed_by_direct_profile_refs(self, tmp_path):
        """A subscription's profiles can be individually targeted by routing rules."""
        from v2portal.models import Subscription

        store = _store(tmp_path)
        main = store.add_profile(Profile(name="default", kind="socks", outbound=SOCKS_OUTBOUND))
        n1 = store.add_profile(Profile(name="node1", kind="socks", outbound=SOCKS_OUTBOUND))
        n2 = store.add_profile(Profile(name="node2", kind="socks", outbound=SOCKS_OUTBOUND))
        sub = store.add_subscription(
            Subscription(name="provider", profile_ids=[n1.id, n2.id])
        )
        store.config.routing = RoutingConfig(
            mode="split",
            rules=[add_rule("proxy", {"domains": ["youtube.com"]}, target_id=n1.id)],
        )

        target = resolve_target(store, main, default_engine="sing-box")
        target = enrich_target_with_routing(target, store.config.routing, store)
        adapter = get_adapter("sing-box")
        config = adapter.generate(store.config.settings, store.config.routing, target)

        outbounds = config.get("outbounds", [])
        tags = [o.get("tag") for o in outbounds]
        # The targeted node profile should be present.
        assert n1.id in tags
        # Route rule should reference the targeted node.
        rules = config.get("route", {}).get("rules", [])
        assert any(
            r.get("outbound") == n1.id or r.get("outboundTag") == n1.id
            for r in rules
        )

    def test_xray_split_routing(self, tmp_path):
        """Split routing works with the xray engine."""
        store = _store(tmp_path)
        main = store.add_profile(Profile(name="main", kind="vmess", outbound=VMESS_OUTBOUND))
        extra = store.add_profile(
            Profile(name="extra", kind="vmess", outbound=VLESS_OUTBOUND
        ))
        store.config.routing = RoutingConfig(
            mode="split",
            rules=[add_rule("proxy", {"domains": ["example.com"]}, target_id=extra.id)],
        )

        target = resolve_target(store, main, default_engine="xray")
        target = enrich_target_with_routing(target, store.config.routing, store)
        adapter = get_adapter("xray")
        config = adapter.generate(store.config.settings, store.config.routing, target)

        outbounds = config.get("outbounds", [])
        tags = [o.get("tag") for o in outbounds]
        assert main.id in tags
        assert extra.id in tags
        # Xray routing rules should reference the extra outbound.
        rules = config.get("routing", {}).get("rules", [])
        assert any(
            r.get("outboundTag") == extra.id
            for r in rules
        )


# ===========================================================================
# 5. Server → server chaining through proxy profiles
# ===========================================================================


class TestServerChaining:
    """Verify server-to-server forwarding through SOCKS/HTTP proxy hops."""

    def test_server_forwards_through_socks_hop(self, tmp_path):
        """A server can forward traffic through another server's SOCKS inbound."""
        store = _store(tmp_path)
        p = store.add_profile(
            Profile(name="upstream-proxy", kind="socks", outbound=SOCKS_OUTBOUND)
        )
        hop = store.add_server(
            Server(name="hop", port=11081, outbound_id=p.id, outbound_type="profile")
        )
        server = store.add_server(
            Server(name="front", port=11080, outbound_id=hop.id, outbound_type="server")
        )
        mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")
        config, engine = mgr._generate_server_config(server)

        # The front server's outbound should be a socks hop to the hop server.
        outbounds = config.get("outbounds", [])
        socks_out = next(o for o in outbounds if o.get("type") == "socks")
        assert socks_out["server"] == "0.0.0.0"
        assert socks_out["server_port"] == 11081

    def test_server_forwards_through_http_hop(self, tmp_path):
        """A server can forward through another server's HTTP inbound."""
        store = _store(tmp_path)
        p = store.add_profile(
            Profile(name="upstream-http", kind="http", outbound=HTTP_OUTBOUND)
        )
        hop = store.add_server(
            Server(name="web-hop", port=18081, outbound_id=p.id, outbound_type="profile",
                   protocol="http")
        )
        server = store.add_server(
            Server(name="front", port=11080, outbound_id=hop.id, outbound_type="server")
        )
        mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")
        config, engine = mgr._generate_server_config(server)

        outbounds = config.get("outbounds", [])
        # For http protocol, the hop should use http type.
        http_out = [o for o in outbounds if o.get("type") in ("http", "socks")]
        assert len(http_out) >= 1


# ===========================================================================
# 6. Auth-enabled SOCKS/HTTP proxy profiles
# ===========================================================================


class TestAuthProxyProfiles:
    """Verify auth-enabled proxy profiles are correctly used in server configs."""

    def test_auth_socks_profile_server_config(self, tmp_path):
        store = _store(tmp_path)
        p = store.add_profile(
            Profile(
                name="auth-socks",
                kind="socks",
                outbound={
                    "settings": {
                        "servers": [
                            {
                                "address": "10.0.0.5",
                                "port": 1080,
                                "users": [{"user": "admin", "pass": "secret"}],
                            }
                        ]
                    }
                },
            )
        )
        server = store.add_server(
            Server(name="s1", port=11080, outbound_id=p.id, outbound_type="profile")
        )
        mgr = ServerManager(store, runtime_dir=tmp_path / "runtime")
        config, engine = mgr._generate_server_config(server)

        outbounds = config.get("outbounds", [])
        sb = next(o for o in outbounds if o.get("tag") == p.id)
        # sing-box uses top-level username/password for SOCKS outbound auth.
        assert sb.get("username") == "admin"
        assert sb.get("password") == "secret"
