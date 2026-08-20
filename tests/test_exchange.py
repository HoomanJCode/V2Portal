import json

import pytest

from v2raycli import backup, exchange
from v2raycli.models import Group, Profile, Subscription
from v2raycli.storage import ConfigStore

SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}

VMESS = {
    "settings": {
        "vnext": [
            {
                "address": "vm.example.com",
                "port": 443,
                "users": [{"id": "SECRET-UUID", "alterId": 0, "security": "auto"}],
            }
        ]
    }
}


def _store(tmp_path, name="config.json"):
    store = ConfigStore(tmp_path / name)
    store.load()
    return store


def _export(tmp_path, store, name="exp.json", redact=False):
    path = tmp_path / name
    exchange.export_full(store, path, redact=redact)
    return path


def test_export_import_roundtrip_lossless(tmp_path):
    store = _store(tmp_path)
    sub = store.add_subscription(Subscription(name="sub"))
    p1 = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS, subscription_id=sub.id))
    sub.profile_ids = [p1.id]
    store.add_group(Group(name="g", type="single", profile_ids=[p1.id]))
    store.save()

    path = _export(tmp_path, store)

    other = _store(tmp_path, "other.json")
    exchange.import_full(other, path, mode="merge")

    assert other.config.to_dict() == store.config.to_dict()


def test_redacted_export_has_no_secrets(tmp_path):
    store = _store(tmp_path)
    store.add_profile(Profile(name="vm", kind="vmess", outbound=VMESS))
    store.add_profile(
        Profile(
            name="wg",
            kind="wireguard",
            outbound={
                "settings": {
                    "secretKey": "SECRET-PRIVATE",
                    "address": ["10.0.0.2/32"],
                    "peers": [
                        {
                            "publicKey": "PUB-KEY",
                            "endpoint": "e:1",
                            "allowedIps": ["0.0.0.0/0"],
                            "preSharedKey": "SECRET-PSK",
                        }
                    ],
                }
            },
        )
    )
    store.add_profile(
        Profile(
            name="tr",
            kind="trojan",
            outbound={"settings": {"servers": [{"address": "h", "port": 443, "password": "SECRET-PASS"}]}},
        )
    )
    store.add_profile(
        Profile(
            name="vpn",
            kind="openvpn",
            vpn={
                "type": "openvpn",
                "inline": "client\nauth-user-pass\nVPN-SECRET\n",
                "auth_hint": "VPN-AUTH-HINT",
            },
        )
    )

    data = exchange.export_full(store, redact=True)
    text = json.dumps(data)

    for secret in (
        "SECRET-UUID",
        "SECRET-PRIVATE",
        "SECRET-PSK",
        "SECRET-PASS",
        "VPN-SECRET",
        "VPN-AUTH-HINT",
    ):
        assert secret not in text
    assert "REDACTED" in text


def test_import_merge_dedupes_on_conflict(tmp_path):
    store = _store(tmp_path)
    existing = store.add_profile(Profile(name="keep", kind="socks", outbound=SOCKS))

    incoming = _store(tmp_path, "incoming.json")
    incoming.add_profile(Profile(name="dup", kind="socks", outbound=SOCKS))  # same key, new id
    path = _export(tmp_path, incoming)

    exchange.import_full(store, path, mode="merge")

    assert len(store.config.profiles) == 1
    assert store.config.profiles[0].id == existing.id
    assert store.config.profiles[0].name == "keep"


def test_import_merge_updates_by_id(tmp_path):
    store = _store(tmp_path)
    p = store.add_profile(Profile(name="orig", kind="socks", outbound=SOCKS))

    incoming = _store(tmp_path, "incoming.json")
    incoming.add_profile(Profile(id=p.id, name="renamed", kind="socks", outbound=SOCKS))
    path = _export(tmp_path, incoming)

    exchange.import_full(store, path, mode="merge")

    assert store.config.profiles[0].name == "renamed"


def test_import_merge_triggers_backup_hook(tmp_path):
    store = _store(tmp_path)
    store.add_profile(Profile(name="old", kind="socks", outbound=SOCKS))
    incoming = _store(tmp_path, "incoming.json")
    incoming.add_profile(
        Profile(
            name="new",
            kind="socks",
            outbound={"settings": {"servers": [{"address": "5.6.7.8", "port": 1080}]}},
        )
    )
    path = _export(tmp_path, incoming)
    backup_dir = tmp_path / "backups"
    backup.install_backup_hook(store, backup_dir=backup_dir)

    exchange.import_full(store, path, mode="merge")

    assert any(b.reason == "import-merge" for b in backup.list_backups(backup_dir))


def test_import_merge_noop_does_not_trigger_backup_hook(tmp_path):
    store = _store(tmp_path)
    store.add_profile(Profile(name="existing", kind="socks", outbound=SOCKS))
    path = _export(tmp_path, store, "same.json")
    backup_dir = tmp_path / "backups"
    backup.install_backup_hook(store, backup_dir=backup_dir)

    exchange.import_full(store, path, mode="merge")

    assert backup.list_backups(backup_dir) == []


def test_import_replace_backs_up_first(tmp_path):
    bdir = tmp_path / "backups"
    store = _store(tmp_path)
    store.add_profile(Profile(name="old", kind="socks", outbound=SOCKS))
    store.save()

    incoming = _store(tmp_path, "incoming.json")
    incoming.add_profile(Profile(name="new", kind="socks", outbound=SOCKS))
    path = _export(tmp_path, incoming)

    exchange.import_full(store, path, mode="replace", backup_dir=bdir)

    assert [p.name for p in store.config.profiles] == ["new"]
    assert any(b.reason == "import-replace" for b in backup.list_backups(bdir))


def test_import_full_rejects_malformed_nested_shape_before_backup(tmp_path):
    store = _store(tmp_path)
    backup_dir = tmp_path / "backups"
    backup.install_backup_hook(store, backup_dir=backup_dir)
    bad = tmp_path / "bad-shape.json"
    bad.write_text(json.dumps({"schema_version": 2, "profiles": [{"outbound": []}]}))

    try:
        exchange.import_full(store, bad, mode="replace", backup_dir=backup_dir)
    except ValueError as exc:
        assert "outbound" in str(exc)
    else:
        raise AssertionError("expected ValueError")

    assert store.config.profiles == []
    assert backup.list_backups(backup_dir) == []


def test_import_full_rejects_missing_file_cleanly(tmp_path):
    store = _store(tmp_path)

    with pytest.raises(ValueError, match="could not read export"):
        exchange.import_full(store, tmp_path / "missing.json")


def test_import_full_rejects_bad_schema(tmp_path):
    store = _store(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": 999}))

    try:
        exchange.import_full(store, bad)
    except ValueError as exc:
        assert "schema_version" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_share_link_export_matches_encode(tmp_path):
    store = _store(tmp_path)
    socks = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
    vm = store.add_profile(Profile(name="vm", kind="vmess", outbound=VMESS))
    # wireguard is not encodable and must be skipped
    store.add_profile(Profile(name="wg", kind="wireguard", outbound={"settings": {"secretKey": "k"}}))

    path = tmp_path / "links.txt"
    links = exchange.export_share_links(store.list_profiles(), path)

    from v2raycli.subs.share import encode_link

    assert links == [encode_link(socks), encode_link(vm)]
    assert path.read_text().splitlines() == links


def test_import_share_links_from_file(tmp_path):
    store = _store(tmp_path)
    path = tmp_path / "links.txt"
    path.write_text("socks://user:pass@1.2.3.4:1080#one\nsocks://user:pass@1.2.3.4:1080#dup\n")

    added = exchange.import_share_links(store, str(path))

    assert len(added) == 1  # second link deduped
    assert added[0].kind == "socks"
    assert store.config.profiles[0].name == "one"


def test_import_share_links_from_text(tmp_path):
    store = _store(tmp_path)
    added = exchange.import_share_links(store, "http://1.2.3.4:8080#proxy")
    assert len(added) == 1
    assert added[0].kind == "http"


def test_import_share_links_treats_probe_error_as_text(tmp_path, monkeypatch):
    store = _store(tmp_path)

    def fail_probe(_path):
        raise OSError("path too long")

    monkeypatch.setattr(exchange.Path, "is_file", fail_probe)

    added = exchange.import_share_links(store, "http://1.2.3.4:8080#proxy")

    assert len(added) == 1
    assert added[0].kind == "http"


def test_import_share_links_ignores_non_text_input(tmp_path):
    store = _store(tmp_path)

    assert exchange.import_share_links(store, None) == []


def test_import_share_links_triggers_backup_hook(tmp_path):
    store = _store(tmp_path)
    backup_dir = tmp_path / "backups"
    backup.install_backup_hook(store, backup_dir=backup_dir)

    exchange.import_share_links(store, "http://1.2.3.4:8080#proxy")

    assert any(b.reason == "import-share-links" for b in backup.list_backups(backup_dir))
