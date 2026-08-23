from datetime import datetime, timedelta, timezone

import pytest

from v2raycli.models import Profile, Subscription
from v2raycli.storage import ConfigStore
from v2raycli.subs import parser
from v2raycli.subs.parser import auto_update_subscriptions, is_stale


def _iso(dt):
    return dt.isoformat()


def _sub(**kw):
    defaults = {"name": "S", "url": "file:///tmp/sub.txt", "auto_update_days": 1}
    defaults.update(kw)
    return Subscription(**defaults)


def test_is_stale_disabled_or_zero():
    assert not is_stale(_sub(auto_update_days=0))
    assert not is_stale(_sub(enabled=False))
    assert not is_stale(_sub(enabled=False, auto_update_days=0))


def test_is_stale_never_updated():
    assert is_stale(_sub(auto_update_days=1, last_updated=None))


def test_is_stale_fresh_vs_old():
    now = datetime.now(timezone.utc)
    fresh = _sub(auto_update_days=7, last_updated=_iso(now - timedelta(days=3)))
    old = _sub(auto_update_days=7, last_updated=_iso(now - timedelta(days=8)))
    assert not is_stale(fresh, now)
    assert is_stale(old, now)


def test_is_stale_bad_timestamp_is_stale():
    assert is_stale(_sub(auto_update_days=1, last_updated="not-a-date"))


def _store_with(tmp_path, *subs):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    for sub in subs:
        store.add_subscription(sub)
    return store


def test_auto_update_updates_only_stale(tmp_path, monkeypatch):
    sub_old = _sub(name="old", auto_update_days=1, last_updated=None)
    sub_fresh = _sub(name="fresh", auto_update_days=1, last_updated=_iso(datetime.now(timezone.utc)))
    store = _store_with(tmp_path, sub_old, sub_fresh)

    calls: list = []
    monkeypatch.setattr(parser.fetcher, "fetch", lambda url, ua=None, proxy=None: ("socks://u:p@1.2.3.4:1080#n\n", {}))

    results = auto_update_subscriptions(store)
    updated_names = {r["name"] for r in results if r["updated"]}
    assert updated_names == {"old"}


def test_auto_update_isolates_failures(tmp_path, monkeypatch):
    sub_bad = _sub(name="bad", url="https://bad.example", auto_update_days=1)
    sub_good = _sub(name="good", url="file:///tmp/good.txt", auto_update_days=1)
    store = _store_with(tmp_path, sub_bad, sub_good)

    def fake_fetch(url, ua=None, proxy=None):
        if url.startswith("https://"):
            raise parser.fetcher.FetchError("boom")
        return "socks://u:p@1.2.3.4:1080#n\n", {}

    monkeypatch.setattr(parser.fetcher, "fetch", fake_fetch)

    results = auto_update_subscriptions(store)
    by_name = {r["name"]: r for r in results}
    assert by_name["good"]["updated"] is True
    assert by_name["bad"]["updated"] is False
    assert "boom" in by_name["bad"]["error"]
    assert len([p for p in store.config.profiles if p.subscription_id == sub_good.id]) == 1


def test_auto_update_saves_profiles(tmp_path, monkeypatch):
    sub = _sub(name="s", auto_update_days=1)
    store = _store_with(tmp_path, sub)
    monkeypatch.setattr(
        parser.fetcher, "fetch", lambda url, ua=None, proxy=None: ("socks://u:p@1.2.3.4:1080#n\n", {})
    )

    results = auto_update_subscriptions(store)
    assert results[0]["updated"] is True
    store.save()
    reloaded = ConfigStore(store.path)
    reloaded.load()
    assert len(reloaded.config.profiles) == 1


def test_app_auto_update_flag(tmp_path, monkeypatch):
    from v2raycli import app, config

    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backup")
    monkeypatch.setattr(config, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(config, "BIN_DIR", tmp_path / "bin")
    monkeypatch.setattr(config, "GEO_DIR", tmp_path / "geo")
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)

    # Seed a stale subscription so auto-update would fire on a normal run.
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    store.add_subscription(_sub(name="stale-sub", auto_update_days=1))
    store.save()

    fetched = []
    monkeypatch.setattr(
        parser.fetcher,
        "fetch",
        lambda url, ua=None, proxy=None: fetched.append(url) or ("socks://u:p@1.2.3.4:1080#n\n", {}),
    )

    # --no-auto-update must skip the fetch entirely.
    assert app.main(["--config-dir", str(tmp_path), "--no-auto-update", "status"]) == 0
    assert fetched == []
