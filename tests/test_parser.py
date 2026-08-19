import base64
from pathlib import Path

import pytest

from v2raycli.models import Group
from v2raycli.storage import ConfigStore
from v2raycli.subs.parser import _userinfo, import_subscription, parse_payload, update_subscription


FIXTURE_LINKS = [
    "vless://00000000-0000-0000-0000-000000000002@5.6.7.8:443?security=tls&sni=vl.example.com&type=ws&path=%2Fvless#vless-node",
    "trojan://password123@9.10.11.12:443?security=tls&sni=tj.example.com#trojan-node",
    "socks://user:pass@17.18.19.20:1080#socks-node",
    "http://user:pass@21.22.23.24:8080#http-node",
    "hysteria2://h2pass@31.32.33.34:443?insecure=1&sni=h2.example.com#hysteria2-node",
    "tuic://00000000-0000-0000-0000-000000000003:tuicpass@35.36.37.38:443?congestion_control=bbr&alpn=h3&sni=tuic.example.com#tuic-node",
]


def test_parse_payload_plain():
    assert parse_payload("\n".join(FIXTURE_LINKS) + "\n") == FIXTURE_LINKS


def test_parse_payload_base64():
    body = "\n".join(FIXTURE_LINKS)
    b64 = base64.urlsafe_b64encode(body.encode()).decode().rstrip("=")
    assert parse_payload(b64) == FIXTURE_LINKS


def test_parse_payload_plain_text_is_not_base64():
    assert parse_payload("hello world\nsecond line\n") == ["hello world", "second line"]


@pytest.mark.parametrize("body", [None, b"vless://x", 123])
def test_parse_payload_rejects_non_text(body):
    with pytest.raises(ValueError, match="payload must be text"):
        parse_payload(body)


def test_userinfo_normalizes_malformed_counters_and_expiry():
    traffic, expires = _userinfo(
        {
            "subscription-userinfo": (
                "upload=-1; download=2; total=bad; "
                "expire=999999999999999999999999"
            )
        }
    )
    assert traffic == 2
    assert expires is None


def test_sample_fixture_imports_all_protocols():
    fixture = Path(__file__).parent / "fixtures" / "sample_subscription.txt"
    sub, profiles, errors = import_subscription("S", f"file://{fixture}")
    assert not errors
    kinds = {p.kind for p in profiles}
    assert {"vless", "trojan", "socks", "http", "hysteria2", "tuic"} <= kinds
    assert sub.profile_ids == [p.id for p in profiles]


def test_import_subscription(tmp_path):
    f = tmp_path / "sub.txt"
    f.write_text("\n".join(FIXTURE_LINKS))
    sub, profiles, errors = import_subscription("S", f"file://{f}")
    assert not errors
    assert len(profiles) == len(FIXTURE_LINKS)
    assert sub.profile_ids == [p.id for p in profiles]
    assert all(p.subscription_id == sub.id for p in profiles)


def test_import_subscription_reports_bad_links(tmp_path):
    f = tmp_path / "sub.txt"
    f.write_text("foo://bar\n" + FIXTURE_LINKS[0])
    _sub, profiles, errors = import_subscription("S", f"file://{f}")
    assert len(profiles) == 1
    assert len(errors) == 1


def test_import_subscription_reports_malformed_handler_errors(tmp_path):
    f = tmp_path / "sub.txt"
    f.write_text("vmess://not-base64\n" + FIXTURE_LINKS[0])

    _sub, profiles, errors = import_subscription("S", f"file://{f}")

    assert len(profiles) == 1
    assert len(errors) == 1


def test_update_rejects_all_invalid_payload_without_pruning(tmp_path):
    f = tmp_path / "sub.txt"
    f.write_text(FIXTURE_LINKS[0])
    store = ConfigStore(tmp_path / "config.json")
    store.load()

    sub, profiles, errors = import_subscription("S", f"file://{f}")
    assert not errors
    store.add_subscription(sub)
    store.add_profile(profiles[0])
    group = store.add_group(Group(name="G", type="single", profile_ids=[profiles[0].id]))

    f.write_text("not-a-supported-share-link")
    with pytest.raises(ValueError, match="no valid profiles"):
        update_subscription(store, sub.id)

    assert store.config.profiles == profiles
    assert group.profile_ids == [profiles[0].id]


def test_update_deletes_vanished_and_prunes_groups(tmp_path):
    f = tmp_path / "sub.txt"
    f.write_text("\n".join(FIXTURE_LINKS[:3]))
    store = ConfigStore(tmp_path / "config.json")
    store.load()

    sub, profiles, errors = import_subscription("S", f"file://{f}")
    assert not errors
    store.add_subscription(sub)
    for p in profiles:
        store.add_profile(p)
    profiles[0].name = "Custom"
    group = store.add_group(Group(name="G", type="balancer", profile_ids=[p.id for p in profiles]))

    # third node vanishes upstream
    f.write_text("\n".join(FIXTURE_LINKS[:2]))
    new_profiles, errors = update_subscription(store, sub.id)
    assert not errors
    assert len(new_profiles) == 2
    assert new_profiles[0].name == "Custom"  # name preserved for unchanged node
    assert set(group.profile_ids) == {p.id for p in new_profiles}
    assert len([p for p in store.config.profiles if p.subscription_id == sub.id]) == 2
