"""Geo asset download.

xray resolves ``geoip:``/``geosite:`` rules against ``geoip.dat`` and\n``geosite.dat``, which it looks up via the ``XRAY_LOCATION_ASSET`` env var (or\nnext to the binary). sing-box downloads its own rule-sets, so only xray needs\nassets fetched here.
"""

from __future__ import annotations

from pathlib import Path

import httpx

from . import config
from .errors import V2RayCLIError


class GeoError(V2RayCLIError):
    pass


XRAY_GEO_ASSETS = {
    "geoip.dat": "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geoip.dat",
    "geosite.dat": "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download/geosite.dat",
}


def _download(url: str, target: Path) -> None:
    part = target.with_suffix(target.suffix + ".part")
    try:
        with httpx.Client(follow_redirects=True, timeout=60.0) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                with open(part, "wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
        part.replace(target)
    except httpx.HTTPError as exc:
        raise GeoError(f"download failed: {exc}") from exc
    finally:
        part.unlink(missing_ok=True)


def ensure_geo_assets(engine: str, geo_dir: Path | None = None) -> Path:
    """Ensure the geo assets ``engine`` needs exist; return the asset dir.

    Only xray requires pre-downloaded ``.dat`` files; other engines return the
    directory unchanged.
    """
    directory = Path(geo_dir) if geo_dir is not None else config.GEO_DIR
    if engine != "xray":
        return directory
    directory.mkdir(parents=True, exist_ok=True)
    for name, url in XRAY_GEO_ASSETS.items():
        target = directory / name
        if not target.exists():
            _download(url, target)
    return directory
