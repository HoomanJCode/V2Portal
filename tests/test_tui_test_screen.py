from v2raycli.models import Profile
from v2raycli.storage import ConfigStore
from v2raycli.test.latency import TestResult
from v2raycli.tui import test_screen


def test_interactive_test_saves_results(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    profile = store.add_profile(Profile(name="node", kind="socks"))

    saved = []
    rendered = []
    monkeypatch.setattr(test_screen.widgets, "menu", lambda *args, **kwargs: "all")
    monkeypatch.setattr(test_screen, "render_table", lambda results: rendered.extend(results))
    monkeypatch.setattr(test_screen, "save_results", lambda results: saved.extend(results))
    monkeypatch.setattr(
        test_screen,
        "test_many",
        lambda profiles, settings, engines=None: [
            TestResult(profile_id=profile.id, name=profile.name, ok=True)
        ],
    )
    monkeypatch.setattr(test_screen.widgets, "show_message", lambda *args: None)

    test_screen.run(store)

    assert [result.profile_id for result in saved] == [profile.id]
    assert [result.profile_id for result in rendered] == [profile.id]


def test_interactive_test_views_cached_results(tmp_path, monkeypatch):
    store = ConfigStore(tmp_path / "config.json")
    store.load()
    cached = TestResult(profile_id="p1", name="cached", ok=True)
    rendered = []

    monkeypatch.setattr(test_screen.widgets, "menu", lambda *args, **kwargs: "last")
    monkeypatch.setattr(test_screen, "load_results", lambda: [cached])
    monkeypatch.setattr(test_screen, "render_table", lambda results: rendered.extend(results))

    test_screen.run(store)

    assert rendered == [cached]
