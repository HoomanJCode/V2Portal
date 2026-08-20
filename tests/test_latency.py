from pathlib import Path

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
        return str(Path("/tmp") / "v2raycli-probe.json")

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
    assert proc.argv[0] == "/fake/sing-box"
    assert proc.argv[1] == "run"
    assert "v2raycli-probe.json" in proc.argv[3]
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
    def refused(*args, **kwargs):
        raise OSError(111, "refused")

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


class FakeWebSocketSocket:
    def __init__(self, response=b""):
        self.response = response
        self.sent = []
        self.timeout = None

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, data):
        self.sent.append(data)
        if data.startswith(b"GET "):
            request = data.decode("ascii")
            key = next(line.split(": ", 1)[1] for line in request.split("\\r\\n") if line.startswith("Sec-WebSocket-Key:"))
            accept = latency.base64.b64encode(
                latency.hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
            ).decode("ascii")
            self.response = (
                "HTTP/1.1 101 Switching Protocols\\r\\n"
                "Upgrade: websocket\\r\\n"
                "Connection: Upgrade\\r\\n"
                f"Sec-WebSocket-Accept: {accept}\\r\\n\\r\\n"
            ).encode("ascii")

    def recv(self, size):
        data, self.response = self.response[:size], self.response[size:]
        return data

    def close(self):
        pass


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
    sock = FakeWebSocketSocket(b"HTTP/1.1 404 Not Found\\r\\n\\r\\n")

    ok, _, status = latency._websocket_handshake(sock, "ws.example", "/", {})

    assert ok is False
    assert status == "handshake_status"


def test_websocket_ping_requires_matching_pong():
    sock = FakeWebSocketSocket(b"\\x8a\\x08v2raycli")

    ok, elapsed, status = latency._websocket_ping(sock)

    assert ok is True
    assert elapsed >= 0
    assert status == "ok"
    assert sock.sent[0][0] == 0x89
    assert sock.sent[0][1] & 0x80

    invalid = FakeWebSocketSocket(b"\\x8a\\x03bad")
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
