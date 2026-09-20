# -*- coding: utf-8 -*-
"""桌面版/跨平台层自检（Windows/Linux 都能跑）。

覆盖：运行时探测（工具/目录/aria2 参数）、桌面首次运行配置准备、解压工具接入。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

results: list[tuple[str, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, "PASS" if cond else "FAIL", str(detail)))


tmp_root = Path(tempfile.mkdtemp(prefix="moviedock-desktop-"))
os.environ["MOVIE_DOCK_HOME"] = str(tmp_root / "home")

from app.runtime import ensure_utf8

ensure_utf8()

from app import runtime  # noqa: E402
from app.config import load_config  # noqa: E402
from app.desktop import launcher  # noqa: E402
from app.subtitle import extract as extract_mod  # noqa: E402

# ---------- 1) 平台与目录 ----------
check("platform_tag", runtime.platform_tag() in ("win64", "linux64", "macos"), runtime.platform_tag())
check("app_data_dir_honours_env", str(runtime.app_data_dir()) == str(tmp_root / "home"), runtime.app_data_dir())
check("default_config_path", runtime.default_config_path().name == "config.yaml", runtime.default_config_path())
check("default_data_dir", str(runtime.default_data_dir()).startswith(str(tmp_root / "home")), runtime.default_data_dir())
check("default_download_root", bool(str(runtime.default_download_root())), runtime.default_download_root())

# ---------- 2) 工具探测：vendor 优先于 PATH ----------
fake_vendor = tmp_root / "vendor"
(fake_vendor / runtime.platform_tag()).mkdir(parents=True, exist_ok=True)
fake_7z = fake_vendor / runtime.platform_tag() / ("7z.exe" if runtime.IS_WINDOWS else "7z")
fake_7z.write_bytes(b"stub")
orig_vendor_dir = runtime.vendor_dir
runtime.vendor_dir = lambda: fake_vendor  # type: ignore[assignment]
found = runtime.find_tool("7z")
check("find_tool_vendor_first", found == str(fake_7z), found)
runtime.vendor_dir = orig_vendor_dir  # type: ignore[assignment]
check("find_tool_missing_returns_none", runtime.find_tool("definitely-not-a-tool") is None, "none")
check("aria2_binary_probe", runtime.aria2_binary() is None or Path(runtime.aria2_binary()).exists(),
      runtime.aria2_binary())

# ---------- 3) aria2 启动参数 ----------
args = runtime.aria2_command(binary="aria2c", port=6801, dir_path="/tmp/x", bt_trackers="udp://t:1")
joined = " ".join(args)
check("aria2_no_seed", "--seed-time=0" in joined and "--seed-ratio=0.0" in joined, "--seed-time=0")
check("aria2_loopback_only", "--rpc-listen-all=false" in joined, "--rpc-listen-all=false")
check("aria2_port_and_tracker", "--rpc-listen-port=6801" in joined and "--bt-tracker=udp://t:1" in joined, "port/tracker")
check("aria2_secret_optional", "--rpc-secret=s3cret" in " ".join(
    runtime.aria2_command(binary="aria2c", dir_path="/tmp/x", rpc_secret="s3cret")), "secret")
check("aria2_rpc_not_ready_dead_port", runtime.aria2_rpc_ready(1, timeout=1.0) is False, "dead port")

# ---------- 4) 桌面首次运行配置准备 ----------
cfg_path = tmp_root / "home" / "config.yaml"
prepared = launcher.prepare_config(cfg_path, download_dir=str(tmp_root / "movies"))
check("prepare_config_created", prepared.exists(), str(prepared))
cfg = load_config(prepared)
check("prepare_config_download_root", str(cfg.download_root()) == str((tmp_root / "movies").resolve())
      or cfg.paths.download_root.endswith("movies"), cfg.paths.download_root)
check("prepare_config_aria2_autostart", cfg.downloader.aria2.auto_start is True, cfg.downloader.aria2.auto_start)
check("prepare_config_state_dir", bool(cfg.paths.state_dir), cfg.paths.state_dir)

# 二次运行不能覆盖用户改动
import yaml  # noqa: E402

data = yaml.safe_load(prepared.read_text(encoding="utf-8"))
data["organize"]["mode"] = "hardlink"
data["subtitle"]["prefer_simplified"] = False
prepared.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
launcher.prepare_config(prepared)
again = yaml.safe_load(prepared.read_text(encoding="utf-8"))
check("prepare_config_idempotent",
      again["organize"]["mode"] == "hardlink" and again["subtitle"]["prefer_simplified"] is False,
      f"{again['organize']['mode']}/{again['subtitle']['prefer_simplified']}")

# ---------- 5) 解压工具接入 runtime ----------
extract_mod.find_tool = lambda name, override=None: str(fake_7z) if name == "7z" else None  # type: ignore[assignment]
check("extract_tool_via_runtime", extract_mod._tool_path("7z") == str(fake_7z), extract_mod._tool_path("7z"))
check("extract_tool_missing", extract_mod._tool_path("bsdtar") is None, "none")

# _run_tool 命令构造（不真的执行）
import subprocess as _sp  # noqa: E402

calls: list[list[str]] = []


class _FakeCompleted:
    returncode = 0
    stdout = "ok"
    stderr = ""


def _fake_run(cmd, **kwargs):  # noqa: ANN001
    calls.append(list(cmd))
    return _FakeCompleted()


orig_run = _sp.run
_sp.run = _fake_run  # type: ignore[assignment]
try:
    extract_mod._run_tool("7z.exe", Path("/tmp/a.rar"), Path("/tmp/out"))
    extract_mod._run_tool("7zz", Path("/tmp/a.rar"), Path("/tmp/out"))
    extract_mod._run_tool("UnRAR.exe", Path("/tmp/a.rar"), Path("/tmp/out"))
    extract_mod._run_tool("bsdtar", Path("/tmp/a.rar"), Path("/tmp/out"))
finally:
    _sp.run = orig_run  # type: ignore[assignment]
check("extract_cmd_7z", calls[0][:3] == ["7z.exe", "x", "-y"], calls[0][:3])
check("extract_cmd_7zz", calls[1][:3] == ["7zz", "x", "-y"], calls[1][:3])
check("extract_cmd_unrar_win", calls[2][0] == "UnRAR.exe" and "x" in calls[2], calls[2][:3])
check("extract_cmd_bsdtar", calls[3][:2] == ["bsdtar", "-xf"], calls[3][:2])

# ---------- 6) 启动器辅助函数 ----------
check("pick_port", isinstance(launcher.pick_port(8099), int), launcher.pick_port(8099))
launcher._pid_file = lambda: tmp_root / "running.pid"  # type: ignore[assignment]
check("pidfile_empty", launcher._port_from_pidfile() is None, "None")
launcher._write_pidfile(8090)
check("pidfile_roundtrip", launcher._port_from_pidfile() == 8090, launcher._port_from_pidfile())
launcher._clear_pidfile()
check("pidfile_cleared", launcher._port_from_pidfile() is None, "None")

env = runtime.describe_environment()
check("describe_environment", {"platform", "aria2", "7z", "webview"} <= set(env), list(env))

# ---------- 7) 启动页与启动日志（修“拒绝连接”缺陷的配套） ----------
from app.desktop import window as win_mod  # noqa: E402

splash = ROOT / "app" / "static" / "splash.html"
check("splash_exists", splash.exists(), str(splash))
if splash.exists():
    text = splash.read_text(encoding="utf-8")
    check("splash_polls_health", "/api/health" in text and "location.replace" in text, "poll ok")
    check("splash_has_timeout_hint", "启动超时" in text, "timeout hint")
check("splash_url_has_port", "port=8090" in win_mod.splash_url(8090), win_mod.splash_url(8090))
check("splash_url_is_file_uri", win_mod.splash_url(8090).startswith("file://"), win_mod.splash_url(8090)[:30])

log_path = launcher.setup_logging()
check("setup_logging_returns_path", log_path is not None and str(log_path).endswith("app.log"), log_path)
check("wait_health_dead_port_none", launcher.wait_health(1, timeout=1.0) is None, "None")
_st = launcher.ServerThread("127.0.0.1", 1)
check("server_thread_captures_error", hasattr(_st, "error") and _st.error is None, "attr ok")

# ---------- 8) 前端入口可见性（修“双击空白处点不到”） ----------
html_text = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
js_text = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
check("ui_paste_button", 'id="btn-paste"' in html_text, "btn-paste")
check("ui_paste_handler", "openPasteModal" in js_text and "parseMagnetName" in js_text, "handlers")
check("ui_url_editable_when_manual", 'id="dl-url" rows="3" placeholder' in html_text, "editable textarea")
check("ui_empty_state_has_entry", "btn-paste-inline" in js_text and "还没检索" in js_text, "empty-state entry")

print("=" * 68)
failed = 0
for name, status, detail in results:
    print(f"[{status}] {name} :: {detail}")
    if status == "FAIL":
        failed += 1
print("=" * 68)
print(f"TOTAL={len(results)} FAIL={failed}")
sys.exit(1 if failed else 0)
