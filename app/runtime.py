"""运行时环境探测与跨平台适配（Linux/NAS 与 Windows 通用）。

集中处理平台差异，避免散落在业务代码里：
- 配置文件 / 状态目录位置（Windows 用 %APPDATA%\\MovieDock）
- 外部工具探测：aria2c、7z/7zz、bsdtar、unrar/unar（先看随包 vendor 目录，再看 PATH，再看常见安装路径）
- aria2 进程托管：拼参数、拉起、等 RPC 就绪、退出清理
- 打开浏览器等桌面行为
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

IS_WINDOWS = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

APP_NAME = "MovieDock"
_EXE = ".exe" if IS_WINDOWS else ""


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """打包后（PyInstaller onedir/onefile）的资源根目录；开发态为仓库根。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return project_root()


def vendor_dir() -> Path:
    """随包二进制目录：vendor/<platform>/（aria2c、7z 等）。"""
    return bundle_root() / "vendor"


def platform_tag() -> str:
    if IS_WINDOWS:
        return "win64"
    if IS_MAC:
        return "macos"
    return "linux64"


def app_data_dir() -> Path:
    """配置与状态落盘位置（桌面模式下用系统标准目录）。"""
    env = os.environ.get("MOVIE_DOCK_HOME")
    if env:
        return Path(env).expanduser()
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else (Path.home() / ".config")
    return Path(base) / "movie-dock"


def default_config_path() -> Path:
    return app_data_dir() / "config.yaml"


def default_data_dir() -> Path:
    return app_data_dir() / "data"


def default_download_root() -> Path:
    """桌面模式的默认下载目录（Windows 优先用磁盘上的 Movies 目录）。"""
    if IS_WINDOWS:
        for drive in ("D:", "E:", "C:"):
            candidate = Path(f"{drive}/Movies/movie-dock")
            try:
                if Path(f"{drive}/").exists():
                    return candidate
            except OSError:
                continue
        return Path.home() / "Movies" / "movie-dock"
    return Path.home() / "movie-dock-downloads"


# ---------------------------------------------------------------- 外部工具探测
# 名称 -> 常见安装路径（按平台）
_TOOL_HINTS: dict[str, dict[str, list[str]]] = {
    "aria2c": {
        "win64": [
            r"C:\Program Files\aria2\aria2c.exe",
            r"C:\Program Files (x86)\aria2\aria2c.exe",
            r"C:\aria2\aria2c.exe",
        ],
        "linux64": ["/usr/bin/aria2c", "/usr/local/bin/aria2c", "/usr/trim/bin/aria2c"],
        "macos": ["/opt/homebrew/bin/aria2c", "/usr/local/bin/aria2c"],
    },
    "7z": {
        "win64": [
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files (x86)\7-Zip\7z.exe",
        ],
        "linux64": ["/usr/bin/7z", "/usr/bin/7za", "/usr/trim/bin/7zz", "/usr/bin/7zz"],
        "macos": ["/opt/homebrew/bin/7z", "/usr/local/bin/7z"],
    },
    "unrar": {
        "win64": [r"C:\Program Files\WinRAR\UnRAR.exe", r"C:\Program Files\WinRAR\unrar.exe"],
        "linux64": ["/usr/bin/unrar", "/usr/local/bin/unrar"],
        "macos": ["/opt/homebrew/bin/unrar", "/usr/local/bin/unrar"],
    },
    "bsdtar": {
        "win64": [],
        "linux64": ["/usr/bin/bsdtar"],
        "macos": ["/usr/bin/bsdtar"],
    },
    "unar": {
        "win64": [],
        "linux64": ["/usr/bin/unar"],
        "macos": ["/opt/homebrew/bin/unar"],
    },
}

# 备选可执行名（用户配置里可能写 7za / 7zz 等）
_TOOL_ALIASES: dict[str, list[str]] = {
    "7z": ["7z", "7zz", "7za"],
    "aria2c": ["aria2c"],
    "unrar": ["unrar", "UnRAR"],
    "bsdtar": ["bsdtar", "tar"],
    "unar": ["unar", "lsar"],
}


def _candidate_vendor_paths(name: str) -> list[Path]:
    names = _TOOL_ALIASES.get(name, [name])
    out: list[Path] = []
    for base in (vendor_dir() / platform_tag(), vendor_dir(), bundle_root()):
        for n in names:
            out.append(base / f"{n}{_EXE}")
            out.append(base / n)
    if is_frozen():  # 有的打包布局会把二进制放到 exe 同级
        exe_dir = Path(sys.executable).resolve().parent
        for n in names:
            out.append(exe_dir / f"{n}{_EXE}")
    return out


def find_tool(name: str, override: str | None = None) -> str | None:
    """探测外部工具，返回可执行文件路径。

    顺序：显式 override → 随包 vendor 目录 → PATH → 常见安装路径。
    """
    if override:
        p = Path(override).expanduser()
        if p.exists():
            return str(p)
        found = shutil.which(override)
        if found:
            return found
    for cand in _candidate_vendor_paths(name):
        try:
            if cand.exists() and cand.is_file():
                return str(cand)
        except OSError:
            continue
    for alias in _TOOL_ALIASES.get(name, [name]):
        found = shutil.which(alias)
        if found:
            return found
    for hint in _TOOL_HINTS.get(name, {}).get(platform_tag(), []):
        if Path(hint).exists():
            return hint
    return None


def aria2_binary(override: str | None = None) -> str | None:
    return find_tool("aria2c", override=override)


def seven_zip_binary(override: str | None = None) -> str | None:
    return find_tool("7z", override=override)


# ---------------------------------------------------------------- aria2 进程托管
def aria2_command(
    *,
    binary: str,
    port: int = 6800,
    dir_path: str | Path,
    seed_time: int = 0,
    max_concurrent: int = 3,
    rpc_secret: str = "",
    bt_trackers: str = "",
    listen_all: bool = False,
    extra: list[str] | None = None,
) -> list[str]:
    """统一的 aria2 启动参数（容器 entrypoint 与桌面端行为保持一致）。"""
    args = [
        binary,
        "--enable-rpc",
        f"--rpc-listen-all={'true' if listen_all else 'false'}",
        f"--rpc-listen-port={port}",
        "--rpc-allow-origin-all=true",
        f"--dir={dir_path}",
        f"--seed-time={seed_time}",
        "--seed-ratio=0.0",
        f"--max-concurrent-downloads={max_concurrent}",
        "--continue=true",
        "--auto-file-renaming=true",
        "--allow-overwrite=false",
        "--file-allocation=none",
        "--max-connection-per-server=16",
        "--split=16",
        "--enable-dht=true",
        "--bt-enable-lpd=true",
        "--bt-save-metadata=true",
        "--bt-max-peers=64",
        "--follow-torrent=true",
        "--console-log-level=warn",
        "--summary-interval=0",
    ]
    if bt_trackers:
        args.append(f"--bt-tracker={bt_trackers}")
    if rpc_secret:
        args.append(f"--rpc-secret={rpc_secret}")
    if extra:
        args.extend(extra)
    return args


def spawn_aria2(args: list[str], log_path: Path) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("ab")
    creationflags = 0
    if IS_WINDOWS:
        # 不弹控制台窗口；随父进程退出
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(  # noqa: S603 - 参数由本模块构造
        args,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=not IS_WINDOWS,
    )


def aria2_rpc_ready(port: int, timeout: float = 15.0, url_path: str = "/jsonrpc") -> bool:
    import urllib.error
    import urllib.request

    payload = json.dumps(
        {"jsonrpc": "2.0", "id": "probe", "method": "aria2.getVersion", "params": []}
    ).encode()
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}{url_path}"
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(
                url, data=payload, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310 - 本机回环
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(0.4)
    return False


def terminate_process(proc: subprocess.Popen | None, timeout: float = 5.0) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
    except OSError:
        pass


# ---------------------------------------------------------------- 桌面行为
def open_in_browser(url: str) -> bool:
    import webbrowser

    try:
        return webbrowser.open(url)
    except Exception:  # noqa: BLE001
        return False


def webview_available() -> bool:
    """桌面模式下能否用 WebView 窗口（Windows 需要 WebView2 运行时）。"""
    try:
        import webview  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def ensure_utf8() -> None:
    """Windows 控制台/日志默认 cp936，统一成 UTF-8，避免中文乱码。"""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def describe_environment() -> dict[str, object]:
    """给界面/日志用的环境自检信息。"""
    return {
        "platform": platform_tag(),
        "python": sys.version.split()[0],
        "frozen": is_frozen(),
        "app_data_dir": str(app_data_dir()),
        "vendor_dir": str(vendor_dir()),
        "aria2": aria2_binary(),
        "7z": seven_zip_binary(),
        "webview": webview_available(),
    }
