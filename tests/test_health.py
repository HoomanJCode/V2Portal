from datetime import datetime, timedelta, timezone

from v2raycli.models import Subscription
from v2raycli.storage import ConfigStore
from v2raycli.subs.health import check_subscriptions, human_bytes, parse_iso, subscription_status


def test_human_bytes():
    assert human_bytes(None) == "0 B"
    assert human_bytes(0) == "0 B"
    assert human_bytes(1023) == "1023 B"
    assert human_bytes(1024) == "1.0 KiB"
    assert human_bytes(1536) == "1.5 KiB"
    assert human_bytes(5 * 1024 * 1024) == "5.0 MiB"
    assert human_bytes(2 * 1024**3) == "2.0 GiB"


def test_parse_iso():
    assert parse_iso(None) is None
    assert parse_iso("not-a-date") is None
    dt = parse_iso("2026-01-02T03:04:05+00:00")
    assert dt is not None and dt.tzinfo is not None
    naive = parse_iso("2026-01-02T03:04:05")
    assert naive is not None and naive.tzinfo is not None


def test_subscription_status_expired_expiring_ok():
    now = datetime.now(timezone.utc)

    expired = Subscription(name="e", expires=(now - timedelta(days=1)).isoformat())
    assert subscription_status(expired, now)["expired"] is True

    soon = Subscription(name="s", expires=(now + timedelta(days=3)).isoformat())
    status = subscription_status(soon, now, warn_days=7)
    assert status["expiring"] is True and status["expired"] is False
    assert status["days_left"] == 3

    ok = Subscription(name="o", expires=(now + timedelta(days=30)).isoformat())
    status = subscription_status(ok, now, warn_days=7)
    assert status["expiring"] is False and status["expired"] is False


def test_subscription_status_never_expires():
    status = subscription_status(Subscription(name="n"), datetime.now(timezone.utc))
    assert status["expired"] is False and status["expiring"] is False
    assert status["expires"] is None


def test_check_subscriptions_skips_disabled(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    store.add_subscription(Subscription(name="on", expires=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat()))
    store.add_subscription(Subscription(name="off", enabled=False))
    statuses = check_subscriptions(store)
    assert [s["name"] for s in statuses] == ["on"]


def test_health_flag(tmp_path, capsys):
    from v2raycli import app

    store = ConfigStore(tmp_path / "config.json")
    store.load()
    store.add_subscription(
        Subscription(name="sub", expires=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
    )

    assert app._health(store) == 0
    out = capsys.readouterr().out
    assert "sub" in out and "EXPIRED" in out


def test_health_flag_no_subs(tmp_path, capsys):
    from v2raycli import app

    store = ConfigStore(tmp_path / "config.json")
    store.load()
    assert app._health(store) == 0
    assert "no subscriptions" in capsys.readouterr().out


def test_health_check_warns(tmp_path, capsys):
    from v2raycli import app

    store = ConfigStore(tmp_path / "config.json")
    store.load()
    store.add_subscription(
        Subscription(name="expired-sub", expires=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat())
    )

    app._health_check(store)
    err = capsys.readouterr().err
    assert "EXPIRED" in err and "expired-sub" in err
