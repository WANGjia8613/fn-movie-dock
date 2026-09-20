# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（Windows onedir）。

产物：dist/MovieDock/
  MovieDock.exe      GUI 版（WebView2 窗口，无控制台）
  MovieDockCLI.exe   控制台版（--headless / --selftest，排查问题用）
  vendor/win64/      随包 aria2c.exe、7z.exe、7z.dll
  app/static/        中文界面

构建：
    pip install -r requirements.txt -r requirements-desktop.txt pyinstaller
    python scripts/fetch_vendor.py --platform win64
    pyinstaller packaging/moviedock.spec --noconfirm
    # 无窗口 exe 的冒烟：
    dist/MovieDock/MovieDockCLI.exe --selftest --port 8097
"""
import os
from pathlib import Path

SPEC_DIR = Path(os.path.abspath(SPECPATH))
ROOT = SPEC_DIR.parent
VENDOR = ROOT / "vendor"

datas = [
    (str(ROOT / "app" / "static"), "app/static"),
    (str(ROOT / "config.example.yaml"), "."),
]
if VENDOR.exists():
    datas.append((str(VENDOR), "vendor"))

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "webview.platforms.edgechromium",
    "pystray._win32",
    "app.desktop.window",
    "app.desktop.tray",
]

# pythonnet / clr 只在装了才收（pywebview 在 Windows 上依赖它；缺了会退回浏览器）
try:
    import clr  # noqa: F401

    hiddenimports += ["clr", "pythonnet"]
except Exception:  # noqa: BLE001
    pass

excludes = ["matplotlib", "numpy", "pandas", "pytest", "IPython"]

icon_path = SPEC_DIR / "moviedock.ico"
icon = str(icon_path) if icon_path.exists() else None

a = Analysis(
    [str(ROOT / "app" / "desktop" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe_cli = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MovieDockCLI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

exe_gui = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MovieDock",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe_cli,
    exe_gui,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MovieDock",
)
