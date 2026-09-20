"""桌面模式（Windows/macOS/Linux 本地运行）的启动器。

职责：
1. 首次运行准备配置（放在系统标准目录，例如 Windows 的 %APPDATA%\\MovieDock）
2. 需要时拉起随包的 aria2c 子进程（RPC 只监听本机回环）
3. 在同进程内跑 FastAPI（uvicorn，后台线程）
4. 打开 WebView 窗口（WebView2），不可用时退回默认浏览器
5. 退出时清理子进程；支持单实例

命令行：
    MovieDock.exe                     # 正常启动（GUI）
    MovieDock.exe --headless          # 只跑服务，不开窗口（服务器/调试用）
    MovieDock.exe --selftest          # 启动→自检→退出（CI 冒烟用，返回码非 0 表示失败）
    MovieDock.exe --browser           # 不开 WebView，直接用默认浏览器
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

from .. import __version__, runtime

DEFAULT_WINDOW = (1360, 900)

# 冻结后的 GUI 版没有控制台，stdout/stderr 为 None —— 把输出重定向到日志文件
_LOG_HANDLE = None


def setup_logging() -> Path | None:
    """GUI(无控制台) 模式下把打印写进 %APPDATA%\\MovieDock\\logs\\app.log。"""
    global _LOG_HANDLE
    try:
        log_dir = runtime.app_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "app.log"
        if sys.stdout is None or sys.stderr is None:
            if _LOG_HANDLE is None or getattr(_LOG_HANDLE, "closed", False):
                _LOG_HANDLE = path.open("a", encoding="utf-8", buffering=1)
            if sys.stdout is None:
                sys.stdout = _LOG_HANDLE
            if sys.stderr is None:
                sys.stderr = _LOG_HANDLE
        return path
    except OSError:
        return None


# ---------------------------------------------------------------- 配置准备
def _copy_example_config(dest: Path) -> bool:
    candidates = [
        runtime.bundle_root() / "config.example.yaml",
        runtime.project_root() / "config.example.yaml",
    ]
    for src in candidates:
        try:
            if src.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
                return True
        except OSError:
            continue
    return False


def prepare_config(config_path: Path, download_dir: str | None = None) -> Path:
    """确保配置文件存在，并为桌面模式写入合理默认值。"""
    import yaml

    config_path = config_path.expanduser()
    first_run = not config_path.exists()
    if first_run:
        if not _copy_example_config(config_path):
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text("{}", encoding="utf-8")

    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        data = {}
    if not isinstance(data, dict):
        data = {}

    changed = False
    paths = data.setdefault("paths", {})
    if first_run or download_dir:
        target = Path(download_dir).expanduser() if download_dir else runtime.default_download_root()
        paths["download_root"] = str(target)
        changed = True
    if first_run:
        paths["state_dir"] = str(runtime.default_data_dir())
        changed = True

    dl = data.setdefault("downloader", {})
    aria2 = dl.setdefault("aria2", {})
    if first_run:
        # 桌面模式：应用自己拉起 aria2（Docker 模式则保持 False，由 entrypoint 负责）
        aria2["auto_start"] = True
        aria2["port"] = int(data.get("_aria2_port", 0) or 0) or 6800
        aria2["rpc_url"] = f"http://127.0.0.1:{aria2['port']}/jsonrpc"
        changed = True

    if first_run:
        # 打印给第一次使用的人看
        print(f"[片坞] 配置文件：{config_path}")
        print(f"[片坞] 下载目录：{paths.get('download_root')}")

    if changed:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    return config_path


# ---------------------------------------------------------------- 单实例
def _pid_file() -> Path:
    return runtime.app_data_dir() / "running.pid"


def _port_from_pidfile() -> int | None:
    try:
        raw = _pid_file().read_text(encoding="utf-8").strip().splitlines()
        pid = int(raw[0])
        port = int(raw[1]) if len(raw) > 1 else 8090
    except (OSError, ValueError, IndexError):
        return None
    try:
        os.kill(pid, 0)  # 仅探测存活
    except OSError:
        return None
    except Exception:  # noqa: BLE001
        return None
    return port


def _write_pidfile(port: int) -> None:
    try:
        _pid_file().parent.mkdir(parents=True, exist_ok=True)
        _pid_file().write_text(f"{os.getpid()}\n{port}\n", encoding="utf-8")
    except OSError:
        pass


def _clear_pidfile() -> None:
    try:
        _pid_file().unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------- 服务与 aria2
def _port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def pick_port(preferred: int) -> int:
    if _port_free(preferred):
        return preferred
    for candidate in range(preferred + 1, preferred + 20):
        if _port_free(candidate):
            return candidate
    return preferred


class ServerThread(threading.Thread):
    def __init__(self, host: str, port: int, log_level: str = "warning"):
        super().__init__(daemon=True, name="movie-dock-server")
        self.host = host
        self.port = port
        self.log_level = log_level
        self.server = None
        self.error: BaseException | None = None
        self.error_traceback = ""

    def run(self) -> None:
        import traceback

        import uvicorn

        from ..main import app

        config = uvicorn.Config(app, host=self.host, port=self.port, log_level=self.log_level)
        self.server = uvicorn.Server(config)
        try:
            self.server.run()
        except BaseException as exc:  # noqa: BLE001 - 线程内异常必须自己抓住
            self.error = exc
            self.error_traceback = traceback.format_exc()
            print(f"[片坞] ✗ 本地服务启动失败：{exc!r}", file=sys.stderr)
            print(self.error_traceback, file=sys.stderr)

    def stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True


def wait_health(port: int, timeout: float = 25.0) -> dict | None:
    import urllib.request

    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/api/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:  # noqa: S310
                return json.loads(resp.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            time.sleep(0.4)
    return None


def start_aria2_if_needed(cfg, log_path: Path) -> "object | None":
    """桌面模式按配置拉起 aria2c；已在跑（或被 entrypoint 拉起）就跳过。"""
    import httpx

    aria2 = cfg.downloader.aria2
    if not aria2.auto_start:
        return None
    port = int(aria2.port or 0)
    if port and runtime.aria2_rpc_ready(port, timeout=1.5):
        print(f"[片坞] 检测到 aria2 已在 {port} 端口运行，跳过启动")
        return None
    binary = runtime.aria2_binary(aria2.binary or None)
    if not binary:
        print("[片坞] ⚠ 未找到 aria2c：磁力/种子下载不可用（HTTP 直链仍可用）")
        return None
    incoming = cfg.incoming_dir()
    incoming.mkdir(parents=True, exist_ok=True)
    args = runtime.aria2_command(
        binary=binary,
        port=port or 6800,
        dir_path=incoming,
        max_concurrent=cfg.downloader.max_concurrent,
        rpc_secret=aria2.rpc_secret,
        bt_trackers=cfg.downloader.bt_trackers,
        listen_all=False,  # 只监听回环，桌面模式不暴露给局域网
    )
    proc = runtime.spawn_aria2(args, log_path)
    ready = runtime.aria2_rpc_ready(port or 6800, timeout=15.0)
    print(f"[片坞] aria2c 已启动 pid={proc.pid} 就绪={ready} 日志={log_path}")
    return proc


# ---------------------------------------------------------------- 自检（CI）
def selftest(port: int, host: str = "127.0.0.1") -> int:
    """启动服务跑一遍关键 API，用于 CI/装机自检。返回码 0=通过。"""
    import httpx

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, str(detail)[:200]))

    base = f"http://127.0.0.1:{port}"
    env = runtime.describe_environment()
    print("[自检] 环境:", json.dumps(env, ensure_ascii=False))
    check("aria2_binary_found", bool(env["aria2"]), str(env["aria2"]))

    with httpx.Client(base_url=base, timeout=60.0) as client:
        try:
            health = client.get("/api/health").json()
            check("health", health.get("ok") is True, health)
        except Exception as exc:  # noqa: BLE001
            check("health", False, exc)
        try:
            dl = client.get("/api/downloader/status").json()
            check("aria2_rpc", bool(dl.get("available")), dl)
        except Exception as exc:  # noqa: BLE001
            check("aria2_rpc", False, exc)
        try:
            cfg = client.get("/api/config").json()
            check("config", bool(cfg.get("download_root")), cfg.get("download_root"))
        except Exception as exc:  # noqa: BLE001
            check("config", False, exc)
        try:
            idx = client.get("/")
            check("index_html", idx.status_code == 200 and "片坞" in idx.text, idx.status_code)
            js = client.get("/static/app.js")
            check("app_js", js.status_code == 200 and "loadTasks" in js.text, js.status_code)
        except Exception as exc:  # noqa: BLE001
            check("index_html", False, exc)

    failed = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name} :: {detail}")
    print(f"[自检] 共 {len(checks)} 项，失败 {len(failed)}")
    return 1 if failed else 0


# ---------------------------------------------------------------- 主流程
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="MovieDock", description="片坞 Movie Dock 桌面版")
    p.add_argument("--config", help="配置文件路径（默认系统配置目录）")
    p.add_argument("--port", type=int, default=8090, help="本地服务端口（默认 8090）")
    p.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机）")
    p.add_argument("--download-dir", help="首次运行时写入的下载目录")
    p.add_argument("--headless", action="store_true", help="只跑服务，不开窗口")
    p.add_argument("--selftest", action="store_true", help="启动→自检→退出（CI 用）")
    p.add_argument("--browser", action="store_true", help="用默认浏览器代替内置窗口")
    p.add_argument("--no-tray", action="store_true", help="不创建托盘图标")
    p.add_argument("--log-level", default="warning", help="uvicorn 日志级别")
    p.add_argument("--startup-timeout", type=float, default=60.0,
                   help="等待本地服务就绪的秒数（首次启动较慢可调大）")
    p.add_argument("--version", action="store_true", help="打印版本")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime.ensure_utf8()
    log_path = setup_logging()
    if log_path:
        print(f"=== 片坞启动 {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        print(f"[片坞] 日志文件：{log_path}")
    if args.version:
        print(f"Movie Dock {__version__}")
        return 0

    config_path = Path(args.config) if args.config else runtime.default_config_path()
    config_path = prepare_config(config_path, args.download_dir)
    os.environ["MOVIE_DOCK_CONFIG"] = str(config_path)

    from ..config import load_config

    cfg = load_config(config_path)

    port = pick_port(args.port)
    if port != args.port:
        print(f"[片坞] 端口 {args.port} 被占用，改用 {port}")

    log_dir = runtime.app_data_dir() / "logs"
    aria2_proc = start_aria2_if_needed(cfg, log_dir / "aria2.log")

    server = ServerThread(args.host, port, args.log_level)
    server.start()
    health = wait_health(port, timeout=args.startup_timeout)
    if health:
        print(f"[片坞] 服务已就绪：http://127.0.0.1:{port}")
    elif server.error is not None:
        print(f"[片坞] ✗ 服务异常退出：{server.error!r}")
    else:
        print(f"[片坞] ⚠ 服务启动超时（{args.startup_timeout:.0f}s），将先显示启动页")

    if args.selftest:
        code = selftest(port, args.host)
        server.stop()
        runtime.terminate_process(aria2_proc)
        return code

    url = f"http://127.0.0.1:{port}/"
    if args.headless:
        print("[片坞] headless 模式运行中，Ctrl+C 退出")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        server.stop()
        runtime.terminate_process(aria2_proc)
        return 0

    # 已有实例在跑 → 直接打开已有窗口，不重复启动
    existing = _port_from_pidfile()
    if existing and existing != port and wait_health(existing, timeout=1.5):
        print(f"[片坞] 已有实例在运行（端口 {existing}），打开它")
        runtime.open_in_browser(f"http://127.0.0.1:{existing}/")
        server.stop()
        runtime.terminate_process(aria2_proc)
        return 0

    _write_pidfile(port)
    exit_code = 0
    try:
        if args.browser or not runtime.webview_available():
            if not runtime.webview_available():
                print("[片坞] 未安装 pywebview/WebView2，改用默认浏览器打开")
            runtime.open_in_browser(url)
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        else:
            from .window import open_window

            exit_code = open_window(
                url,
                port,
                title=f"片坞 Movie Dock {__version__}",
                no_tray=args.no_tray,
                ready_timeout=max(5.0, args.startup_timeout),
            )
    finally:
        server.stop()
        runtime.terminate_process(aria2_proc)
        _clear_pidfile()
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
