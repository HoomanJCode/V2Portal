from v2portal import geo
from v2portal.models import RoutingConfig, RoutingRule
from v2portal.routing.rules import uses_geo


def test_uses_geo():
    assert not uses_geo(RoutingConfig(mode="all", rules=[RoutingRule(match={"geoip": ["cn"]})]))
    assert not uses_geo(RoutingConfig(mode="split", rules=[RoutingRule(match={"domains": ["x.com"]})]))
    assert uses_geo(RoutingConfig(mode="split", rules=[RoutingRule(match={"geosite": ["cn"]})]))
    assert uses_geo(RoutingConfig(mode="split", rules=[RoutingRule(match={"geoip": ["cn"]})]))
    assert uses_geo(RoutingConfig(mode="split", rules=[RoutingRule(match={"domains": ["geosite:cn"]})]))
    assert uses_geo(RoutingConfig(mode="split", rules=[RoutingRule(match={"ips": ["geoip:cn"]})]))


def test_ensure_geo_assets_downloads_missing(tmp_path, monkeypatch):
    calls = []

    def fake_download(url, target):
        calls.append((url, target.name))
        target.write_bytes(b"x")

    monkeypatch.setattr(geo, "_download", fake_download)
    directory = geo.ensure_geo_assets("xray", geo_dir=tmp_path / "geo")
    assert directory == tmp_path / "geo"
    assert len(calls) == 2
    assert (tmp_path / "geo" / "geoip.dat").exists()
    assert (tmp_path / "geo" / "geosite.dat").exists()


def test_ensure_geo_assets_skips_existing(tmp_path, monkeypatch):
    (tmp_path / "geo").mkdir()
    (tmp_path / "geo" / "geoip.dat").write_bytes(b"x")
    (tmp_path / "geo" / "geosite.dat").write_bytes(b"x")

    def boom(url, target):
        raise AssertionError("should not download")

    monkeypatch.setattr(geo, "_download", boom)
    assert geo.ensure_geo_assets("xray", geo_dir=tmp_path / "geo") == tmp_path / "geo"


def test_ensure_geo_assets_non_xray_noop(tmp_path, monkeypatch):
    def boom(url, target):
        raise AssertionError("should not download")

    monkeypatch.setattr(geo, "_download", boom)
    assert geo.ensure_geo_assets("sing-box", geo_dir=tmp_path / "geo") == tmp_path / "geo"
    assert not (tmp_path / "geo").exists()
