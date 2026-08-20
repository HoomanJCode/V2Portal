from v2raycli.models import Profile, Subscription
from v2raycli.storage import ConfigStore
from v2raycli.tui import manage


SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}


def _store(tmp_path):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    return store


def test_manage_adds_subscription_from_ui(tmp_path, monkeypatch):
    store = _store(tmp_path)
    profile = Profile(name="node", kind="socks", outbound=SOCKS)
    subscription = Subscription(name="provider")
    inputs = iter(["provider", "paste://socks://user:pass@1.2.3.4:1080"])
    messages = []

    monkeypatch.setattr(manage.widgets, "menu", lambda *args: "sub")
    monkeypatch.setattr(manage.widgets, "input_text", lambda *args: next(inputs))
    monkeypatch.setattr(
        manage,
        "import_subscription",
        lambda name, url: (subscription, [profile], []),
    )
    monkeypatch.setattr(
        manage.widgets,
        "show_message",
        lambda title, text: messages.append((title, text)),
    )

    manage._add(store)

    assert store.config.subscriptions == [subscription]
    assert store.config.profiles == [profile]
    assert messages == [("Imported", "Added 1 profiles.")]


def test_manage_creates_balancer_and_chain(tmp_path, monkeypatch):
    store = _store(tmp_path)
    first = store.add_profile(Profile(name="a", kind="socks", outbound=SOCKS))
    second = store.add_profile(Profile(name="b", kind="socks", outbound=SOCKS))
    names = iter(["latency-group", "chain-group"])
    selections = iter([[first.id, second.id], [first.id, second.id]])

    monkeypatch.setattr(manage.widgets, "input_text", lambda *args: next(names))
    monkeypatch.setattr(manage.widgets, "menu", lambda *args: "latency")
    monkeypatch.setattr(manage.widgets, "multi_select", lambda *args: next(selections))

    manage._create_balancer(store)
    manage._create_chain(store)

    assert [group.name for group in store.config.groups] == ["latency-group", "chain-group"]
    assert store.config.groups[0].type == "balancer"
    assert store.config.groups[1].type == "chain"
    assert store.config.groups[1].profile_ids == [first.id, second.id]


def test_manage_adds_openvpn_profile_from_ui(tmp_path, monkeypatch):
    store = _store(tmp_path)
    inputs = iter(["vpn", "", "client\n"])

    monkeypatch.setattr(manage.widgets, "menu", lambda *args: "openvpn")
    monkeypatch.setattr(manage.widgets, "input_text", lambda *args: next(inputs))

    manage._add(store)

    assert len(store.config.profiles) == 1
    profile = store.config.profiles[0]
    assert profile.kind == "openvpn"
    assert profile.vpn == {"type": "openvpn", "args": [], "inline": "client\n"}
