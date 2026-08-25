"""Tests for ProxyConnectionError propagation and storage save-failure messages."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from v2raycli.connection import ConnectionController, ProxyConnectionError
from v2raycli.errors import V2RayCLIError
from v2raycli.models import Group, Profile
from v2raycli.storage import ConfigStore

from conftest import make_fake_script

SOCKS = {"settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}
CHECK_GUARD = 'if [ "$1" = "check" ] || [ "$2" = "-test" ]; then exit 0; fi'


def _store(tmp_path):
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    return store


def _fake(tmp_path, body):
    return make_fake_script(tmp_path, "sing-box", body)


# --- ProxyConnectionError hierarchy -----------------------------------------


class TestProxyConnectionErrorHierarchy:
    """ProxyConnectionError must be catchable as both V2RayCLIError and Exception."""

    def test_is_v2raycli_error(self):
        assert issubclass(ProxyConnectionError, V2RayCLIError)

    def test_is_exception(self):
        assert issubclass(ProxyConnectionError, Exception)

    def test_catchable_as_v2raycli_error(self):
        with pytest.raises(V2RayCLIError):
            raise ProxyConnectionError("test")

    def test_message_preserved(self):
        exc = ProxyConnectionError("missing binary for sing-box: not found")
        assert str(exc) == "missing binary for sing-box: not found"


# --- Connection error → status mapping --------------------------------------


class TestConnectionErrorToStatus:
    """Connection failures must map to ConnectionStatus(state='error')."""

    def test_missing_binary_maps_to_error(self, tmp_path):
        store = _store(tmp_path)
        profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
        store.config.engines["sing-box"] = {
            "binary_path": str(tmp_path / "nope"),
            "version": "x",
        }

        ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
        status = ctl.connect(profile)

        assert status.state == "error"
        assert "missing binary" in status.error
        assert status.target_name == "s"

    def test_invalid_config_maps_to_error(self, tmp_path):
        store = _store(tmp_path)
        profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
        binary = _fake(tmp_path, CHECK_GUARD)
        store.config.engines["sing-box"] = {
            "binary_path": str(binary),
            "version": "x",
        }

        def bad_validate(engine, path, binary=None, env=None):
            raise RuntimeError("config validation failed: unknown field")

        with patch("v2raycli.connection.validate_config", bad_validate):
            ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
            status = ctl.connect(profile)

        assert status.state == "error"
        assert "invalid config" in status.error
        assert "unknown field" in status.error

    def test_engine_exit_maps_to_error_with_logs(self, tmp_path):
        store = _store(tmp_path)
        profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
        binary = _fake(
            tmp_path,
            CHECK_GUARD + '\necho "bind: address already in use"\nexit 1',
        )
        store.config.engines["sing-box"] = {
            "binary_path": str(binary),
            "version": "x",
        }

        ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
        status = ctl.connect(profile)

        assert status.state == "error"
        assert "exited immediately" in status.error
        assert "address already in use" in status.error

    def test_process_start_oserror_maps_to_error(self, tmp_path, monkeypatch):
        store = _store(tmp_path)
        profile = store.add_profile(Profile(name="s", kind="socks", outbound=SOCKS))
        binary = _fake(tmp_path, CHECK_GUARD)
        store.config.engines["sing-box"] = {
            "binary_path": str(binary),
            "version": "x",
        }

        class FailingProc:
            pid = None

            def start(self, argv, env=None):
                raise OSError("permission denied")

            def stop(self):
                pass

        monkeypatch.setattr(
            "v2raycli.connection.Proc", FailingProc
        )
        ctl = ConnectionController(store, bin_dir=tmp_path, runtime_dir=tmp_path)
        status = ctl.connect(profile)

        assert status.state == "error"
        assert "permission denied" in status.error

    def test_stale_group_maps_to_error(self, tmp_path):
        store = _store(tmp_path)
        group = store.add_group(
            Group(name="stale", type="single", profile_ids=["missing"])
        )

        status = ConnectionController(store).connect(group)

        assert status.state == "error"
        assert status.target_name == "stale"
        assert "unknown id" in status.error

    def test_vpn_missing_config_maps_to_error(self, tmp_path):
        store = _store(tmp_path)
        profile = store.add_profile(
            Profile(
                name="vpn",
                kind="openvpn",
                outbound={},
                vpn={"type": "openvpn", "config_path": str(tmp_path / "missing.ovpn")},
            )
        )

        status = ConnectionController(store).connect(profile)

        assert status.state == "error"
        assert "openvpn config not found" in status.error

    def test_vpn_missing_client_maps_to_error(self, tmp_path, monkeypatch):
        store = _store(tmp_path)
        profile = store.add_profile(
            Profile(
                name="vpn",
                kind="openconnect",
                outbound={},
                vpn={"type": "openconnect", "server": "vpn.example.com"},
            )
        )

        monkeypatch.setattr(
            "v2raycli.connection.detect_clients",
            lambda: {"openconnect": None, "openvpn": None},
        )

        status = ConnectionController(store).connect(profile)

        assert status.state == "error"
        assert "not found" in status.error


# --- Storage save-failure error message -------------------------------------


class TestStorageSaveFailure:
    """save() must raise ValueError with 'failed to save config' on OSError."""

    def test_save_oserror_raises_value_error(self, tmp_path):
        store = ConfigStore(tmp_path / "config.json")
        store.load()

        with patch("v2raycli.storage.os.replace", side_effect=OSError("disk full")):
            with pytest.raises(ValueError, match="failed to save config"):
                store.save()

    def test_save_oserror_chains_original(self, tmp_path):
        store = ConfigStore(tmp_path / "config.json")
        store.load()

        with patch("v2raycli.storage.os.replace", side_effect=OSError("disk full")):
            with pytest.raises(ValueError) as exc_info:
                store.save()
            assert isinstance(exc_info.value.__cause__, OSError)
            assert "disk full" in str(exc_info.value.__cause__)

    def test_save_write_error_raises_value_error(self, tmp_path):
        store = ConfigStore(tmp_path / "config.json")
        store.load()

        original_fdopen = __import__("v2raycli.storage", fromlist=["os"]).os.fdopen

        def failing_fdopen(*args, **kwargs):
            raise OSError("cannot write")

        with patch("v2raycli.storage.os.fdopen", failing_fdopen):
            with pytest.raises(ValueError, match="failed to save config"):
                store.save()

    def test_save_cleanups_temp_on_failure(self, tmp_path):
        store = ConfigStore(tmp_path / "config.json")
        store.load()

        with patch("v2raycli.storage.os.replace", side_effect=OSError("disk full")):
            with pytest.raises(ValueError):
                store.save()

        # Temp file must not be left behind.
        leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []

    def test_save_success_no_error(self, tmp_path):
        store = ConfigStore(tmp_path / "config.json")
        store.load()
        store.add_profile(Profile(name="test", kind="socks"))
        store.save()  # Should not raise.

        reloaded = ConfigStore(tmp_path / "config.json")
        reloaded.load()
        assert len(reloaded.config.profiles) == 1
