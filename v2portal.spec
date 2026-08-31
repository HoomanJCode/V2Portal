# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a single-folder v2portal bundle.

Build with:  pip install pyinstaller && pyinstaller v2portal.spec
Engine binaries and geo assets are NOT bundled; they download on first run.
"""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("v2portal")

a = Analysis(
    ["src/v2portal/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="v2portal",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="v2portal",
)
