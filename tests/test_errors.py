"""Tests for the V2RayCLIError exception hierarchy."""

from __future__ import annotations

import pytest

from v2portal.errors import V2RayCLIError
from v2portal.connection import ProxyConnectionError
from v2portal.engines.binary import BinaryError
from v2portal.geo import GeoError
from v2portal.storage import ConfigLoadError
from v2portal.subs.fetcher import FetchError
from v2portal.subs.share import ShareLinkError


ALL_PROJECT_ERRORS = [
    ProxyConnectionError,
    BinaryError,
    GeoError,
    ConfigLoadError,
    FetchError,
    ShareLinkError,
]


class TestV2RayCLIErrorHierarchy:
    """Every project exception must be a V2RayCLIError subclass."""

    @pytest.mark.parametrize("exc_class", ALL_PROJECT_ERRORS, ids=lambda c: c.__name__)
    def test_is_v2portal_error(self, exc_class: type) -> None:
        assert issubclass(exc_class, V2RayCLIError)

    @pytest.mark.parametrize("exc_class", ALL_PROJECT_ERRORS, ids=lambda c: c.__name__)
    def test_is_exception(self, exc_class: type) -> None:
        assert issubclass(exc_class, Exception)

    @pytest.mark.parametrize("exc_class", ALL_PROJECT_ERRORS, ids=lambda c: c.__name__)
    def test_catchable_as_base(self, exc_class: type) -> None:
        """A ``except V2RayCLIError`` clause catches every project exception."""
        with pytest.raises(V2RayCLIError):
            raise exc_class("test")


class TestBackwardCompatibility:
    """Exceptions that previously inherited from ValueError must still work."""

    def test_config_load_error_is_value_error(self) -> None:
        assert issubclass(ConfigLoadError, ValueError)

    def test_share_link_error_is_value_error(self) -> None:
        assert issubclass(ShareLinkError, ValueError)

    def test_config_load_error_catchable_as_value_error(self) -> None:
        with pytest.raises(ValueError):
            raise ConfigLoadError("bad config")

    def test_share_link_error_catchable_as_value_error(self) -> None:
        with pytest.raises(ValueError):
            raise ShareLinkError("bad link")
