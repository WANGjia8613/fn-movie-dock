"""托盘图标（可选）。依赖 pystray + Pillow；缺失时静默降级。"""
from __future__ import annotations

import threading
from pathlib import Path


def _make_icon_image(size: int = 64):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([2, 2, size - 2, size - 2], radius=size // 5, fill=(61, 139, 253, 255))
    # 简单的"坞"字形占位：三条横线
    for i, y in enumerate((size * 0.32, size * 0.5, size * 0.68)):
        width = size * (0.62 if i != 1 else 0.44)
        draw.rounded_rectangle(
            [size * 0.2, y - size * 0.045, size * 0.2 + width, y + size * 0.045],
            radius=size * 0.05,
            fill=(255, 255, 255, 235),
        )
    return img


def start_tray(window, url: str, download_dir: Path | None = None):
    """启动托盘图标；返回 icon 对象（失败返回 None）。"""
    try:
        import pystray
    except Exception:  # noqa: BLE001
        return None

    def _open(icon=None, item=None):
        try:
            window.show()
            window.restore()
        except Exception:  # noqa: BLE001
            pass

    def _open_dir(icon=None, item=None):
        try:
            import os
            import subprocess
            import sys

            target = str(download_dir) if download_dir else ""
            if not target:
                return
            if sys.platform.startswith("win"):
                os.startfile(target)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])  # noqa: S603, S607
            else:
                subprocess.Popen(["xdg-open", target])  # noqa: S603, S607
        except Exception:  # noqa: BLE001
            pass

    def _copy_url(icon=None, item=None):
        try:
            import tkinter

            root = tkinter.Tk()
            root.withdraw()
            root.clipboard_clear()
            root.clipboard_append(url)
            root.update()
            root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def _quit(icon=None, item=None):
        try:
            window.destroy()
        except Exception:  # noqa: BLE001
            pass
        if icon is not None:
            icon.stop()

    try:
        menu = pystray.Menu(
            pystray.MenuItem("打开界面", _open, default=True),
            pystray.MenuItem("打开下载目录", _open_dir),
            pystray.MenuItem("复制访问地址", _copy_url),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", _quit),
        )
        icon = pystray.Icon("MovieDock", _make_icon_image(), "片坞 Movie Dock", menu)
        threading.Thread(target=icon.run, daemon=True, name="movie-dock-tray").start()
        return icon
    except Exception:  # noqa: BLE001
        return None
