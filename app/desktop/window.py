"""WebView 窗口（WebView2 / WKWebView / WebKitGTK）。

启动策略（修掉"窗口先开、服务没起 → 127.0.0.1 拒绝连接"的问题）：
1. 先等本地服务就绪（wait_health）；就绪 → 直接打开应用页
2. 没就绪 → 打开随包的 splash 页（file://），它会每秒轮询 /api/health，
   就绪自动跳转；同时后台守候线程也会在就绪时主动 load_url，双保险
3. 页面就绪后若服务掉线，守候线程会提示并可刷新
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from .. import runtime

DEFAULT_SIZE = (1360, 900)


def splash_url(port: int) -> str:
    page = runtime.bundle_root() / "app" / "static" / "splash.html"
    if not page.exists():
        page = runtime.project_root() / "app" / "static" / "splash.html"
    return f"{page.as_uri()}?port={port}"


def _health_ok(port: int) -> bool:
    return bool(_wait_health_once(port))


def _wait_health_once(port: int, timeout: float = 2.0) -> dict | None:
    from .launcher import wait_health

    return wait_health(port, timeout=timeout)


def open_window(
    url: str,
    port: int,
    title: str = "片坞 Movie Dock",
    no_tray: bool = False,
    ready_timeout: float = 60.0,
) -> int:
    import webview  # 由调用方确认可用

    ready = _wait_health_once(port, timeout=ready_timeout)
    start_url = url if ready else splash_url(port)
    if not ready:
        print(f"[片坞] 服务尚未就绪，先显示启动页（{ready_timeout:.0f}s 未就绪）")

    window = webview.create_window(
        title,
        start_url,
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
                from ..config import load_config

                download_root = load_config().download_root()
            except Exception:  # noqa: BLE001
                download_root = None
            tray = start_tray(window, url, download_root)
        except Exception:  # noqa: BLE001
            tray = None

    stop_flag = threading.Event()

    def watchdog() -> None:
        """服务就绪后把窗口从 splash 切到应用页；掉线则重新加载。"""
        jumped = bool(ready)
        while not stop_flag.is_set():
            try:
                ok = _health_ok(port)
                if ok and not jumped:
                    try:
                        window.load_url(url)
                    except Exception:  # noqa: BLE001
                        pass
                    jumped = True
                    print("[片坞] 本地服务就绪，已进入应用界面")
                elif jumped and not ok:
                    jumped = False
            except Exception:  # noqa: BLE001
                pass
            stop_flag.wait(1.5)

    threading.Thread(target=watchdog, daemon=True, name="movie-dock-watchdog").start()

    try:
        webview.start()  # gui=None：Windows 上用 EdgeChromium(WebView2)
    finally:
        stop_flag.set()
        if tray is not None:
            try:
                tray.stop()
            except Exception:  # noqa: BLE001
                pass
    return 0


__all__ = ["open_window", "splash_url", "runtime"]
