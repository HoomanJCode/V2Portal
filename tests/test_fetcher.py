import pytest

from v2raycli.subs import fetcher
from v2raycli.subs.fetcher import FetchError, fetch


def test_file_fetch(tmp_path):
    f = tmp_path / "sub.txt"
    f.write_text("vmess://x\n")
    body, headers = fetch(f"file://{f}")
    assert body == "vmess://x\n"
    assert headers == {}


def test_paste_fetch():
    body, headers = fetch("paste://vless://x")
    assert body == "vless://x"
    assert headers == {}


@pytest.mark.parametrize("url", [None, "", "   ", "ftp://example.com/sub"])
def test_invalid_subscription_urls_raise_typed_error(url):
    with pytest.raises(FetchError):
        fetch(url)


def test_invalid_user_agent_raises_typed_error():
    with pytest.raises(FetchError, match="user agent"):
        fetch("paste://links", user_agent=123)


def test_file_missing_raises(tmp_path):
    with pytest.raises(FetchError):
        fetch(f"file://{tmp_path}/nope.txt")


def test_http_fetch_mocked(monkeypatch):
    captured = {}

    class FakeResponse:
        text = "vmess://x"
        headers = {"Subscription-Userinfo": "upload=1; download=2; total=3; expire=1700000000"}

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(fetcher.httpx, "Client", FakeClient)
    body, headers = fetch("https://example.com/sub")
    assert body == "vmess://x"
    assert headers["subscription-userinfo"].startswith("upload=1")
    assert captured["headers"]["User-Agent"] == fetcher.DEFAULT_USER_AGENT

    fetch("https://example.com/sub", user_agent="custom-client")
    assert captured["headers"]["User-Agent"] == "custom-client"


def test_http_fetch_passes_proxy(monkeypatch):
    captured = {}

    class FakeResponse:
        text = "ok"
        headers = {}

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(fetcher.httpx, "Client", FakeClient)

    fetch("https://example.com/sub", proxy="socks5://127.0.0.1:1080")
    assert captured["proxy"] == "socks5://127.0.0.1:1080"

    captured.clear()
    fetch("https://example.com/sub")
    assert "proxy" not in captured


def test_invalid_proxy_type_raises():
    with pytest.raises(FetchError, match="proxy must be text"):
        fetch("paste://x", proxy=123)
