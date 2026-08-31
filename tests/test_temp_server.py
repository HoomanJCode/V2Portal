"""Tests for temporary server start (--temp) and proxy URL parsing."""

import pytest

from v2portal.app import _parse_proxy_url


class TestParseProxyUrl:
    def test_socks5(self):
        host, port, proto = _parse_proxy_url("socks5://192.168.1.2:10804")
        assert host == "192.168.1.2"
        assert port == 10804
        assert proto == "socks"

    def test_socks(self):
        host, port, proto = _parse_proxy_url("socks://127.0.0.1:1080")
        assert host == "127.0.0.1"
        assert port == 1080
        assert proto == "socks"

    def test_http(self):
        host, port, proto = _parse_proxy_url("http://10.0.0.1:8080")
        assert host == "10.0.0.1"
        assert port == 8080
        assert proto == "http"

    def test_https(self):
        host, port, proto = _parse_proxy_url("https://proxy.example.com:443")
        assert host == "proxy.example.com"
        assert port == 443
        assert proto == "http"

    def test_trailing_slash(self):
        host, port, proto = _parse_proxy_url("socks5://127.0.0.1:1080/")
        assert host == "127.0.0.1"
        assert port == 1080
        assert proto == "socks"

    def test_ipv6(self):
        host, port, proto = _parse_proxy_url("socks5://[::1]:1080")
        assert host == "::1"
        assert port == 1080
        assert proto == "socks"

    def test_bad_scheme(self):
        with pytest.raises(ValueError, match="unsupported proxy scheme"):
            _parse_proxy_url("tcp://127.0.0.1:1080")

    def test_missing_port(self):
        with pytest.raises(ValueError, match="requires port"):
            _parse_proxy_url("socks5://127.0.0.1")

    def test_bad_port(self):
        with pytest.raises(ValueError, match="proxy port must be"):
            _parse_proxy_url("socks5://127.0.0.1:99999")

    def test_empty_host(self):
        with pytest.raises(ValueError, match="requires a host"):
            _parse_proxy_url("socks5://:1080")
