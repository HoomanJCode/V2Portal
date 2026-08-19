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


def test_file_missing_raises(tmp_path):
    with pytest.raises(FetchError):
        fetch(f"file://{tmp_path}/nope.txt")


def test_http_fetch_mocked(monkeypatch):
    class FakeResponse:
        text = "vmess://x"
        headers = {"Subscription-Userinfo": "upload=1; download=2; total=3; expire=1700000000"}

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            pass

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
