"""WebView 窗口（WebView2 / WKWebView / WebKitGTK）。

优先用 pywebview 打开原生窗口；不可用时由调用方退回默认浏览器。
"""
from __future__ import annotations

from pathlib import Path

from .. import runtime

DEFAULT_SIZE = (1360, 900)


def open_window(url: str, title: str = "片坞 Movie Dock", no_tray: bool = False) -> int:
    import webview  # 由调用方确认可用

    window = webview.create_window(
        title,
        url,
        width=DEFAULT_SIZE[0],
        height=DEFAULT_SIZE[1],
        min_size=(960, 640),
        text_select=True,
    )

    tray = None
    if not no_tray:
        try:
            from .tray import start_tray

            download_root: Path | None = None
            try:
                import os

                from ..config import load_config

                cfg = load_config()
                download_root = cfg.download_root()
            except Exception:  # noqa: BLE001
                download_root = None
            tray = start_tray(window, url, download_root)
        except Exception:  # noqa: BLE001
            tray = None

    # gui=None 让 pywebview 自动选（Windows→EdgeChromium/WebView2）
    webview.start()
    if tray is not None:
        try:
            tray.stop()
        except Exception:  # noqa: BLE001
            pass
    return 0


__all__ = ["open_window", "runtime"]
