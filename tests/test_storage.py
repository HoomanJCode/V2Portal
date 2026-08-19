import pytest

from v2raycli.models import Group, Profile, Subscription
from v2raycli.storage import ConfigLoadError, ConfigStore


def test_first_run_creates_default(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    cfg = store.load()
    assert cfg.schema_version == 2
    assert cfg.settings.mixed_port == 1080
    assert cfg.settings.default_engine == "sing-box"
    assert cfg.profiles == []
    assert (tmp_path / "config.json").exists()


def test_load_rejects_malformed_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not-json")

    with pytest.raises(ConfigLoadError, match="could not load config"):
        ConfigStore(path).load()


def test_load_rejects_wrong_config_shape(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"profiles": {}}')

    with pytest.raises(ConfigLoadError, match="must be a list"):
        ConfigStore(path).load()


def test_round_trip(tmp_path):
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    store.load()
    store.add_profile(Profile(name="A", kind="socks"))
    store.save()

    reloaded = ConfigStore(path)
    reloaded.load()
    assert len(reloaded.config.profiles) == 1
    assert reloaded.config.profiles[0].name == "A"


def test_atomic_write_leaves_no_temp_files(tmp_path):
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    store.load()
    store.save()
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_remove_subscription_unlinks_profiles(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    sub = store.add_subscription(Subscription(name="S"))
    store.add_profile(Profile(name="P", subscription_id=sub.id))

    assert store.remove_subscription(sub.id) is True
    assert store.config.profiles[0].subscription_id is None
    assert store.remove_subscription("missing") is False


def test_profile_and_group_crud(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    p = store.add_profile(Profile(name="P"))
    g = store.add_group(Group(name="G", profile_ids=[p.id]))

    assert store.get_profile(p.id) is p
    assert store.get_group(g.id) is g
    assert store.remove_group(g.id) is True
    assert store.remove_profile(p.id) is True
    assert store.get_profile(p.id) is None


def test_update_settings_and_engine(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    store.update_settings(mixed_port=9999)
    store.update_engine("sing-box", binary_path="/usr/bin/sing-box")

    assert store.config.settings.mixed_port == 9999
    assert store.config.engines["sing-box"]["binary_path"] == "/usr/bin/sing-box"
