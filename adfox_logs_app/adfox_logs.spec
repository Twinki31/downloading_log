# -*- mode: python ; coding: utf-8 -*-
"""Одна конфигурация сборки для macOS и Windows."""

from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all

from app_version import read_version


project_dir = Path(SPECPATH)
app_version = read_version(project_dir / "VERSION")

datas = [
    (str(project_dir / "app.py"), "."),
    (str(project_dir / "VERSION"), "."),
    (str(project_dir / "log_headers.tsv"), "."),
    (str(project_dir / "pages" / "1_Описание_полей.py"), "pages"),
]
binaries = []
hiddenimports = [
    "app_state",
    "app_version",
    "download",
    "execution",
    "fields",
    "filtering",
    "operation_state",
    "operations",
    "path_ownership",
    "ui_localization",
]

for package in ("streamlit", "boto3", "botocore"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

a = Analysis(
    [str(project_dir / "desktop_launcher.py")],
    pathex=[str(project_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="AdFox Logs",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    collected = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        name="AdFox Logs",
    )
    app = BUNDLE(
        collected,
        name="AdFox Logs.app",
        bundle_identifier="ru.company.adfox-logs",
        info_plist={
            "CFBundleDisplayName": "AdFox Logs",
            "CFBundleShortVersionString": app_version,
            "CFBundleVersion": app_version,
            "LSMinimumSystemVersion": "12.0",
        },
    )
else:
    # Один EXE устанавливается Inno Setup и запускается через созданные ярлыки.
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="AdFox Logs",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
    )
