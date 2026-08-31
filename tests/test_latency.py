import sys
from pathlib import Path

import pytest

from v2raycli.engines.binary import BinaryError
from v2raycli.models import Profile, Subscription
from v2raycli.storage import ConfigStore
from v2raycli.test import latency

SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}


def _store(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    return store


class FakeProc:
    """Records start/stop without spawning a real process."""

    instances: list["FakeProc"] = []

    def __init__(self):
        self.argv = None
        self.stopped = False
        FakeProc.instances.append(self)

    def start(self, argv, env=None):
        self.argv = argv

    def stop(self, grace_seconds=2.0):
        self.stopped = True


def _install_fakes(monkeypatch, captured):
    FakeProc.instances.clear()
    monkeypatch.setattr(latency, "Proc", FakeProc)
    monkeypatch.setattr(latency, "locate_binary", lambda *a, **k: Path("/fake/sing-box"))
    monkeypatch.setattr(latency, "_wait_port", lambda *a, **k: True)

    def fake_write(engine, config_dict):
        captured["engine"] = engine
        captured["config"] = config_dict
        return str(Path("/tmp") / "v2portal-probe.json")

    monkeypatch.setattr(latency, "_write_temp_config", fake_write)


def test_build_test_config_routes_through_profile(tmp_path):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))

    engine, cfg = latency.build_test_config(profile, store.config.settings, 9999)

    assert engine == "sing-box"
    assert cfg["route"]["final"] == profile.id
    inbound = cfg["inbounds"][0]
    assert inbound["listen"] == "127.0.0.1"
    assert inbound["listen_port"] == 9999
    assert "socks" in {o.get("type") for o in cfg["outbounds"]}


def test_http_latency_performs_full_request(monkeypatch):
    observed = {}

    class Response:
        status_code = 204

    class Client:
        def __init__(self, proxy, timeout, follow_redirects):
            observed.update(proxy=proxy, timeout=timeout, follow_redirects=follow_redirects)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            observed["url"] = url
            return Response()

    monkeypatch.setitem(sys.modules, "httpx", type("Httpx", (), {"Client": Client}))

    ok, elapsed, error = latency._http_latency("https://example.test/check", 1080, timeout=2.0)

    assert ok is True
    assert elapsed >= 0
    assert error == ""
    assert observed == {
        "proxy": "socks5://127.0.0.1:1080",
        "timeout": 2.0,
        "follow_redirects": True,
        "url": "https://example.test/check",
    }


def test_test_profile_success_structured_result(tmp_path, monkeypatch):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))

    captured: dict = {}
    _install_fakes(monkeypatch, captured)
    monkeypatch.setattr(latency, "_http_latency", lambda url, port, timeout=10.0: (True, 42.0, ""))
    monkeypatch.setattr(latency, "_connect_ms", lambda port, host, dst_port, timeout=10.0: 15.0)

    result = latency.test_profile(profile, store.config.settings)

    assert result.ok is True
    assert result.latency_ms == 42.0
    assert result.connect_ms == 15.0
    assert result.engine == "sing-box"
    assert result.name == "s"
    assert result.error == ""

    # the runner was started against the fake binary with the probe config
    proc = FakeProc.instances[-1]
    assert Path(proc.argv[0]) == Path("/fake/sing-box")
    assert proc.argv[1] == "run"
    assert "v2portal-probe.json" in proc.argv[3]
    assert captured["config"]["route"]["final"] == profile.id
    # process is always cleaned up
    assert proc.stopped is True


def test_test_profile_cleanup_on_http_failure(tmp_path, monkeypatch):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))

    captured: dict = {}
    _install_fakes(monkeypatch, captured)
    monkeypatch.setattr(
        latency, "_http_latency", lambda url, port, timeout=10.0: (False, 500.0, "boom")
    )

    result = latency.test_profile(profile, store.config.settings)

    assert result.ok is False
    assert result.error == "boom"
    assert FakeProc.instances[-1].stopped is True


def test_test_profile_binary_error_returns_result(tmp_path, monkeypatch):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))

    FakeProc.instances.clear()
    monkeypatch.setattr(latency, "Proc", FakeProc)
    monkeypatch.setattr(
        latency, "locate_binary", lambda *a, **k: (_ for _ in ()).throw(BinaryError("nope"))
    )

    result = latency.test_profile(profile, store.config.settings)

    assert result.ok is False
    assert result.error == "nope"
    # no process was ever started
    assert FakeProc.instances == []


def test_test_profile_vpn_skipped(tmp_path, monkeypatch):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="vpn", kind="openvpn", vpn={"type": "openvpn"}))

    called: dict = {"locate": False}
    monkeypatch.setattr(
        latency, "locate_binary", lambda *a, **k: called.__setitem__("locate", True)
    )

    result = latency.test_profile(profile, store.config.settings)

    assert result.not_testable is True
    assert result.ok is False
    assert called["locate"] is False


def test_url_authority():
    assert latency._url_authority("http://example.com/x") == ("example.com", 80)
    assert latency._url_authority("https://example.com:8443/x") == ("example.com", 8443)
    assert latency._url_authority("https://example.com/") == ("example.com", 443)


def test_profile_endpoint_supports_xray_and_singbox_shapes(tmp_path):
    store = _store(tmp_path)
    xray = store.add_profile(Profile(name="x", kind="vmess", outbound={
        "settings": {"vnext": [{"address": "x.example", "port": 443}]}
    }))
    singbox = store.add_profile(Profile(name="s", kind="hysteria2", outbound={
        "server": "h.example", "server_port": 8443
    }))
    wireguard = store.add_profile(Profile(name="w", kind="wireguard", outbound={
        "settings": {"peers": [{"endpoint": "[2001:db8::1]:51820"}]}
    }))

    assert latency.profile_endpoint(xray) == ("x.example", 443)
    assert latency.profile_endpoint(singbox) == ("h.example", 8443)
    assert latency.profile_endpoint(wireguard) == ("2001:db8::1", 51820)


def test_icmp_probe_reports_unsupported(monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError("ping")

    monkeypatch.setattr(latency.subprocess, "run", missing)

    assert latency._icmp_probe("example.com") == (None, "unsupported")


def test_icmp_probe_reports_success_and_blocked(monkeypatch):
    class Completed:
        returncode = 0

    monkeypatch.setattr(latency.subprocess, "run", lambda *args, **kwargs: Completed())
    elapsed, status = latency._icmp_probe("example.com")
    assert status == "ok"
    assert elapsed is not None

    Completed.returncode = 1
    assert latency._icmp_probe("example.com") == (None, "blocked")


def test_tcp_probe_distinguishes_refused_dns_and_timeout(monkeypatch):
    import errno as _errno

    def refused(*args, **kwargs):
        raise OSError(_errno.ECONNREFUSED, "refused")

    monkeypatch.setattr(latency.socket, "create_connection", refused)
    assert latency._tcp_probe("example.com", 443) == (None, "refused")

    def dns_failure(*args, **kwargs):
        raise latency.socket.gaierror("not found")

    monkeypatch.setattr(latency.socket, "create_connection", dns_failure)
    assert latency._tcp_probe("bad.example", 443) == (None, "dns_error")

    def timed_out(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr(latency.socket, "create_connection", timed_out)
    assert latency._tcp_probe("slow.example", 443) == (None, "timeout")


def test_probe_many_returns_input_order(tmp_path, monkeypatch):
    store = _store(tmp_path)
    a = store.add_profile(Profile(name="a", kind="socks", outbound=SOCKS))
    b = store.add_profile(Profile(name="b", kind="socks", outbound=SOCKS))

    def fake(profile, timeout=5.0):
        return latency.EndpointResult(profile_id=profile.id, name=profile.name, tcp_status="ok")

    monkeypatch.setattr(latency, "probe_endpoint", fake)
    results = latency.probe_many([a, b], concurrency=2)

    assert [result.profile_id for result in results] == [a.id, b.id]


def test_probe_server_targets_own_local_inbound(tmp_path, monkeypatch):
    from v2raycli.models import Server

    store = _store(tmp_path)
    server = store.add_server(Server(name="srv", port=1081, protocol="mixed", listen="127.0.0.1"))

    def fake_tcp(host, port, timeout=5.0):
        return 3.0, "ok"

    monkeypatch.setattr(latency, "_tcp_probe", fake_tcp)
    monkeypatch.setattr(latency, "_icmp_probe", lambda host, timeout=3.0: (None, "blocked"))

    result = latency.probe_server(server)

    assert result.profile_id == server.id
    assert result.name == "srv"
    assert result.host == "127.0.0.1"
    assert result.port == 1081
    assert result.tcp_status == "ok"


def test_probe_server_falls_back_to_loopback_for_any_listen(tmp_path, monkeypatch):
    from v2raycli.models import Server

    store = _store(tmp_path)
    server = store.add_server(Server(name="srv", port=1082, protocol="socks", listen="0.0.0.0"))

    monkeypatch.setattr(latency, "_tcp_probe", lambda host, port, timeout=5.0: (1.0, "ok"))
    monkeypatch.setattr(latency, "_icmp_probe", lambda host, timeout=3.0: (None, "blocked"))

    result = latency.probe_server(server)

    assert result.host == "127.0.0.1"  # any-listen binds loopback too
    assert result.port == 1082


def test_probe_server_invalid_port_is_invalid(tmp_path):
    from v2raycli.models import Server

    store = _store(tmp_path)
    server = store.add_server(Server(name="srv", port=0, protocol="mixed"))

    result = latency.probe_server(server)

    assert result.tcp_status == "invalid"
    assert result.port is None


def test_probe_servers_returns_input_order(tmp_path, monkeypatch):
    from v2raycli.models import Server

    store = _store(tmp_path)
    a = store.add_server(Server(name="a", port=1081))
    b = store.add_server(Server(name="b", port=1082))

    def fake(server, timeout=5.0):
        return latency.EndpointResult(profile_id=server.id, name=server.name, tcp_status="ok")

    monkeypatch.setattr(latency, "probe_server", fake)
    results = latency.probe_servers([a, b], concurrency=2)

    assert [result.profile_id for result in results] == [a.id, b.id]


def test_server_websocket_result_is_not_testable(tmp_path):
    from v2raycli.models import Server

    store = _store(tmp_path)
    server = store.add_server(Server(name="srv", port=1081, protocol="mixed"))

    result = latency.server_websocket_result(server)

    assert result.not_testable is True
    assert result.profile_id == server.id
    assert result.error
    assert result.host == "127.0.0.1"
    assert result.port == 1081


class FakeWebSocketSocket:
    def __init__(self, response=b""):
        self.response = response
        self.sent = []
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, data):
        self.sent.append(data)
        if data.startswith(b"GET ") and not self.response:
            request = data.decode("ascii")
            key = next(line.split(": ", 1)[1] for line in request.split("\r\n") if line.startswith("Sec-WebSocket-Key:"))
            accept = latency.base64.b64encode(
                latency.hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
            ).decode("ascii")
            self.response = (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode("ascii")

    def recv(self, size):
        data, self.response = self.response[:size], self.response[size:]
        return data

    def close(self):
        pass


class FakeSocksSocket:
    """Scripted SOCKS5 reply socket for testing _socks_connect."""

    def __init__(self, greeting=b"\x05\x00", connect_reply=b"\x05\x00\x00\x01" + b"\x00" * 6):
        self.greeting = greeting
        self.connect_reply = connect_reply
        self.buf = b""
        self.sent = []
        self.timeout = None

    def sendall(self, data):
        self.sent.append(data)
        if data == b"\x05\x01\x00":
            self.buf = self.greeting
        elif data.startswith(b"\x05\x01\x00\x03"):
            self.buf = self.connect_reply

    def recv(self, size):
        chunk, self.buf = self.buf[:size], self.buf[size:]
        return chunk

    def settimeout(self, timeout):
        self.timeout = timeout

    def close(self):
        pass


def test_socks_connect_encodes_domain_and_parses_ipv4(monkeypatch):
    reply = b"\x05\x00\x00\x01" + b"\x7f\x00\x00\x01" + (8080).to_bytes(2, "big")
    fake = FakeSocksSocket(connect_reply=reply)
    monkeypatch.setattr(latency.socket, "create_connection", lambda *a, **k: fake)

    sock = latency._socks_connect(1080, "example.com", 443, 5.0)

    assert sock is fake
    assert fake.sent[0] == b"\x05\x01\x00"
    assert fake.sent[1] == b"\x05\x01\x00\x03" + bytes([11]) + b"example.com" + (443).to_bytes(2, "big")


def test_socks_connect_parses_domain_reply(monkeypatch):
    reply = b"\x05\x00\x00\x03" + bytes([7]) + b"1.2.3.4" + (443).to_bytes(2, "big")
    fake = FakeSocksSocket(connect_reply=reply)
    monkeypatch.setattr(latency.socket, "create_connection", lambda *a, **k: fake)

    sock = latency._socks_connect(1080, "example.com", 443, 5.0)

    assert sock is fake
    assert fake.sent[1].startswith(b"\x05\x01\x00\x03")


def test_socks_connect_rejects_bad_greeting(monkeypatch):
    fake = FakeSocksSocket(greeting=b"\x05\xff")
    monkeypatch.setattr(latency.socket, "create_connection", lambda *a, **k: fake)

    with pytest.raises(OSError, match="rejected"):
        latency._socks_connect(1080, "example.com", 443, 5.0)


def test_socks_connect_rejects_connect_failure(monkeypatch):
    fake = FakeSocksSocket(connect_reply=b"\x05\x05\x00\x00")
    monkeypatch.setattr(latency.socket, "create_connection", lambda *a, **k: fake)

    with pytest.raises(OSError, match="CONNECT failed"):
        latency._socks_connect(1080, "example.com", 443, 5.0)


def test_websocket_transport_detects_ws_and_wss(tmp_path):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="ws", kind="vmess", outbound={
        "settings": {"vnext": [{"address": "ws.example", "port": 443}]},
        "streamSettings": {
            "network": "ws", "security": "tls",
            "wsSettings": {"path": "/socket", "headers": {"Host": "cdn.example"}},
            "tlsSettings": {"serverName": "cdn.example"},
        },
    }))

    transport = latency.websocket_transport(profile)

    assert transport["secure"] is True
    assert transport["host"] == "cdn.example"
    assert transport["path"] == "/socket"
    assert latency.websocket_transport(Profile(name="tcp", kind="socks", outbound=SOCKS)) is None


def test_websocket_handshake_validates_101_and_accept():
    sock = FakeWebSocketSocket()

    ok, elapsed, status = latency._websocket_handshake(sock, "ws.example", "/", {})

    assert ok is True
    assert elapsed >= 0
    assert status == "ok"
    assert b"Upgrade: websocket" in sock.sent[0]


def test_websocket_handshake_rejects_non_101():
    sock = FakeWebSocketSocket(b"HTTP/1.1 404 Not Found\r\n\r\n")

    ok, _, status = latency._websocket_handshake(sock, "ws.example", "/", {})

    assert ok is False
    assert status == "handshake_status"


def test_websocket_ping_requires_matching_pong():
    sock = FakeWebSocketSocket(b"\x8a\x08v2portal")

    ok, elapsed, status = latency._websocket_ping(sock)

    assert ok is True
    assert elapsed >= 0
    assert status == "ok"
    assert sock.sent[0][0] == 0x89
    assert sock.sent[0][1] & 0x80

    invalid = FakeWebSocketSocket(b"\x8a\x03bad")
    assert latency._websocket_ping(invalid)[2] == "payload_invalid"


def test_websocket_profile_cleans_up_engine(tmp_path, monkeypatch):
    store = _store(tmp_path)
    profile = store.add_profile(Profile(name="ws", kind="vmess", engine="xray", outbound={
        "settings": {"vnext": [{"address": "ws.example", "port": 443, "users": [{"id": "u"}]}]},
        "streamSettings": {"network": "ws", "wsSettings": {"path": "/"}},
    }))
    captured = {}
    _install_fakes(monkeypatch, captured)
    monkeypatch.setattr(latency, "locate_binary", lambda *a, **k: Path("/fake/xray"))
    monkeypatch.setattr(latency, "_websocket_probe", lambda *a, **k: (
        "ws.example", 443, "ok", 12.0, "ok", 3.0, None
    ))

    result = latency.test_websocket_profile(profile, store.config.settings)

    assert result.handshake_status == "ok"
    assert result.payload_status == "ok"
    assert result.handshake_ms == 12.0
    assert result.payload_ms == 3.0
    assert FakeProc.instances[-1].stopped is True


def test_scope_selectors(tmp_path):
    store = _store(tmp_path)
    sub = store.add_subscription(Subscription(name="sub"))
    p1 = store.add_profile(Profile(name="a", kind="socks", outbound=SOCKS, subscription_id=sub.id))
    p2 = store.add_profile(Profile(name="b", kind="socks", outbound=SOCKS))

    assert [p.id for p in latency.select_profiles(store, "all")] == [p1.id, p2.id]
    assert [p.id for p in latency.select_profiles(store, ("subscription", sub.id))] == [p1.id]
    assert [p.id for p in latency.select_profiles(store, ("profiles", [p2.id]))] == [p2.id]
    assert latency.select_profiles(store, "bogus") == []


def test_collect_routing_target_profiles(tmp_path):
    from v2raycli.models import Group, RoutingConfig, RoutingRule

    store = _store(tmp_path)
    p1 = store.add_profile(Profile(name="main", kind="socks", outbound=SOCKS))
    p2 = store.add_profile(Profile(name="netflix", kind="socks", outbound=SOCKS))
    p3 = store.add_profile(Profile(name="extra", kind="socks", outbound=SOCKS))
    bal = store.add_group(
        Group(name="bal", type="balancer", strategy="latency", profile_ids=[p2.id, p3.id])
    )

    # No routing — empty
    assert latency.collect_routing_target_profiles(store) == []

    # Split mode with a profile target
    store.config.routing = RoutingConfig(
        mode="split",
        rules=[RoutingRule(action="proxy", target_id=p2.id, match={"domains": ["netflix.com"]})],
    )
    result = latency.collect_routing_target_profiles(store)
    assert [p.id for p in result] == [p2.id]

    # Group target resolves member profiles
    store.config.routing = RoutingConfig(
        mode="split",
        rules=[RoutingRule(action="proxy", target_id=bal.id, match={"domains": ["streaming.com"]})],
    )
    result = latency.collect_routing_target_profiles(store)
    result_ids = [p.id for p in result]
    assert p2.id in result_ids
    assert p3.id in result_ids

    # Disabled rules are skipped
    store.config.routing = RoutingConfig(
        mode="split",
        rules=[
            RoutingRule(action="proxy", enabled=False, target_id=p2.id, match={"domains": ["a.com"]}),
            RoutingRule(action="proxy", enabled=True, target_id=p3.id, match={"domains": ["b.com"]}),
        ],
    )
    result = latency.collect_routing_target_profiles(store)
    assert [p.id for p in result] == [p3.id]

    # Direct/block rules don't add profiles
    store.config.routing = RoutingConfig(
        mode="split",
        rules=[RoutingRule(action="direct", match={"domains": ["local.dev"]})],
    )
    assert latency.collect_routing_target_profiles(store) == []

    # Server target resolves to a socks/http profile through its inbound
    from v2raycli.models import Server

    sv = store.add_server(Server(name="local", port=1081, protocol="mixed"))
    store.config.routing = RoutingConfig(
        mode="split",
        rules=[RoutingRule(action="proxy", target_id=sv.id, match={"domains": ["x.com"]})],
    )
    result = latency.collect_routing_target_profiles(store)
    assert len(result) == 1
    assert result[0].id == sv.id
    assert result[0].kind == "socks"
    assert result[0].outbound["settings"]["servers"][0]["port"] == sv.port


def test_scope_routing_targets(tmp_path):
    from v2raycli.models import RoutingConfig, RoutingRule

    store = _store(tmp_path)
    p1 = store.add_profile(Profile(name="a", kind="socks", outbound=SOCKS))
    p2 = store.add_profile(Profile(name="b", kind="socks", outbound=SOCKS))
    store.config.routing = RoutingConfig(
        mode="split",
        rules=[RoutingRule(action="proxy", target_id=p2.id, match={"domains": ["x.com"]})],
    )

    result = latency.select_profiles(store, "routing_targets")
    assert [p.id for p in result] == [p2.id]


def test_test_many_preserves_mixed_success_and_failure_results(tmp_path, monkeypatch):
    store = _store(tmp_path)
    good = store.add_profile(Profile(name="good", kind="socks", outbound=SOCKS))
    bad = store.add_profile(Profile(name="bad", kind="socks", outbound=SOCKS))

    def fake(profile, settings, engines=None, bin_dir=None):
        return latency.TestResult(
            profile_id=profile.id,
            name=profile.name,
            ok=profile is good,
            latency_ms=20.0 if profile is good else 0.0,
            error=None if profile is good else "request timeout",
        )

    monkeypatch.setattr(latency, "test_profile", fake)
    results = latency.test_many([good, bad], store.config.settings, concurrency=2)

    assert [result.profile_id for result in results] == [good.id, bad.id]
    assert [result.ok for result in results] == [True, False]
    assert results[1].error == "request timeout"


def test_test_many_returns_in_input_order(tmp_path, monkeypatch):
    store = _store(tmp_path)
    a = store.add_profile(Profile(name="a", kind="socks", outbound=SOCKS))
    b = store.add_profile(Profile(name="b", kind="socks", outbound=SOCKS))

    def fake(profile, settings, engines=None, bin_dir=None):
        return latency.TestResult(
            profile_id=profile.id, name=profile.name, ok=True, latency_ms=10.0
        )

    monkeypatch.setattr(latency, "test_profile", fake)

    results = latency.test_many([a, b], store.config.settings)

    assert [r.profile_id for r in results] == [a.id, b.id]


def test_save_and_load_results(tmp_path):
    path = tmp_path / "test_results.json"
    expected = [
        latency.TestResult(
            profile_id="p1", name="node", kind="socks", engine="sing-box",
            ok=True, latency_ms=25.0, connect_ms=10.0,
        )
    ]

    latency.save_results(expected, path)

    assert latency.load_results(path) == expected

    path.write_text("not json", encoding="utf-8")
    assert latency.load_results(path) == []
