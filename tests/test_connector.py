"""Tests for connect-by-reference (Phase 05)."""

from __future__ import annotations

import pytest

from v2raycli.connector import connect_ref, resolve_ref_entity
from v2raycli.models import Group, Profile, Subscription
from v2raycli.storage import ConfigStore


def _store(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    p = store.add_profile(Profile(name="p", kind="vmess"))
    s = store.add_subscription(Subscription(name="s", profile_ids=[p.id]))
    g = store.add_group(Group(name="g", type="single", profile_ids=[p.id]))
    return store, p, s, g


def test_resolve_ref_entity_detects_kind(tmp_path):
    store, p, s, g = _store(tmp_path)
    assert resolve_ref_entity(store, p.id) is p
    assert resolve_ref_entity(store, s.id) is s
    assert resolve_ref_entity(store, g.id) is g


def test_resolve_ref_entity_unknown(tmp_path):
    store, _, _, _ = _store(tmp_path)
    with pytest.raises(ValueError, match="unknown id: 999"):
        resolve_ref_entity(store, "999")


def test_connect_ref_subscription_routes_to_controller(tmp_path):
    store, _, s, _ = _store(tmp_path)

    calls = []

    class FakeController:
        def connect(self, selection):
            calls.append(selection)
            return "status"

    result = connect_ref(store, s.id, FakeController())
    assert result == "status"
    assert calls == [s]  # the Subscription model was passed through


def test_connect_ref_unknown_raises(tmp_path):
    store, _, _, _ = _store(tmp_path)
    with pytest.raises(ValueError, match="unknown id"):
        connect_ref(store, "nope", object())