#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端下载链路测试（本地/CI 通用，跨平台）。

做的事：
1. 起一个本地 HTTP 服务，放一个假的媒体文件（Movie.Dock.Test.2020.1080p.mkv）
2. 用桌面启动器 headless 模式拉起应用（自动拉起 aria2c）
3. 通过 HTTP API 建下载任务（含整理 / 关字幕，避免依赖外网）
4. 等任务完成，校验：文件真的下完（字节数一致）+ 被整理到目标命名
5. 退出码 0=通过

用法：
    python scripts/ci_download_test.py [--port 8096] [--aria2-port 6801] [--size-mb 5]
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MEDIA_NAME = "Movie.Dock.Test.2020.1080p.BluRay.x264-CI.mkv"


def free_port(preferred: int) -> int:
    for port in range(preferred, preferred + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("找不到可用端口")


def serve_file(directory: Path, port: int) -> subprocess.Popen:
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=str(directory),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(40):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return proc
        except OSError:
            time.sleep(0.25)
    raise RuntimeError("本地 HTTP 服务启动失败")


def write_test_config(path: Path, download_root: Path, state_dir: Path, aria2_port: int) -> None:
    import yaml

    cfg = {
        "server": {"host": "127.0.0.1", "port": 0},
        "paths": {"download_root": str(download_root), "state_dir": str(state_dir)},
        "search": {
            "sort_by_score": True,
            "providers": [
                {"type": "demo", "enabled": True, "name": "演示数据"},
                {"type": "llm", "enabled": False, "name": "大模型检索"},
                {"type": "custom_api", "enabled": False, "name": "自定义索引"},
            ],
        },
        "organize": {
            "enabled": True,
            "movie_dir_template": "{title} ({year})",
            "file_name_template": "{title} ({year}) - {quality}",
            "mode": "move",
            "library_root": "",
        },
        "downloader": {
            "engine": "aria2",
            "aria2": {
                "rpc_url": f"http://127.0.0.1:{aria2_port}/jsonrpc",
                "rpc_secret": "",
                "auto_start": True,
                "binary": "",
                "port": aria2_port,
            },
            "max_concurrent": 2,
            "category_dir": "incoming",
            "per_task_dir": True,
        },
        # CI 里不依赖外网字幕站
        "subtitle": {"enabled": False, "provider": "subhd"},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8096)
    ap.add_argument("--aria2-port", type=int, default=6801)
    ap.add_argument("--size-mb", type=int, default=5)
    args = ap.parse_args()

    import httpx

    app_port = free_port(args.port)
    aria2_port = free_port(args.aria2_port)
    tmp = Path(tempfile.mkdtemp(prefix="moviedock-ci-"))
    http_root = tmp / "http"
    http_root.mkdir(parents=True, exist_ok=True)
    payload = os.urandom(args.size_mb * 1024 * 1024)
    (http_root / MEDIA_NAME).write_bytes(payload)
    print(f"[CI] 测试文件：{http_root / MEDIA_NAME}（{len(payload)} B）")

    config_path = tmp / "config.yaml"
    write_test_config(config_path, tmp / "downloads", tmp / "data", aria2_port)

    http_proc = serve_file(http_root, free_port(8901))
    http_port = int(http_proc.args[3])
    print(f"[CI] 本地 HTTP：http://127.0.0.1:{http_port}/{MEDIA_NAME}")

    env = dict(os.environ)
    env["MOVIE_DOCK_CONFIG"] = str(config_path)
    env["PYTHONUNBUFFERED"] = "1"
    app_proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "app.desktop", "--headless", "--host", "127.0.0.1",
         "--port", str(app_port), "--config", str(config_path), "--log-level", "warning"],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    def pump() -> None:
        assert app_proc.stdout is not None
        for line in app_proc.stdout:
            print("[app]", line.rstrip())

    threading.Thread(target=pump, daemon=True).start()

    base = f"http://127.0.0.1:{app_port}"
    exit_code = 1
    try:
        with httpx.Client(base_url=base, timeout=30.0) as client:
            for _ in range(60):
                try:
                    if client.get("/api/health").json().get("ok"):
                        break
                except Exception:  # noqa: BLE001
                    time.sleep(0.5)
            else:
                print("[CI] ✗ 服务未就绪")
                return 1

            dl = client.get("/api/downloader/status").json()
            print(f"[CI] aria2 available={dl.get('available')} version={dl.get('version')}")
            if not dl.get("available"):
                print("[CI] ✗ aria2 不可用")
                return 1

            task = client.post("/api/download", json={
                "url": f"http://127.0.0.1:{http_port}/{MEDIA_NAME}",
                "title": "Movie Dock Test",
                "year": 2020,
                "quality": "1080p",
                "fetch_subtitle": False,
                "organize": {"title": "Movie Dock Test", "year": 2020, "quality": "1080p",
                             "enabled": True, "mode": "move"},
            }).json()["task"]
            task_id = task["task_id"]
            print(f"[CI] 任务已创建：{task_id}")

            final = None
            for i in range(120):
                time.sleep(1)
                tasks = client.get("/api/tasks").json()
                current = next((t for t in tasks if t["task_id"] == task_id), None)
                if current is None:
                    continue
                if i % 5 == 0:
                    print(f"[CI] {current['status']} {current['progress']}% "
                          f"{current['completed_length']}/{current['total_length']}")
                if current["status"] in ("complete", "error"):
                    final = current
                    break

            if not final:
                print("[CI] ✗ 任务超时未完成")
                return 1
            if final["status"] != "complete":
                print(f"[CI] ✗ 任务失败：{final['error']}")
                return 1

            organized = Path(final["organized_path"])
            print(f"[CI] 整理结果：{organized}")
            if not organized.exists():
                print("[CI] ✗ 整理后的文件不存在")
                return 1
            actual = organized.stat().st_size
            if actual != len(payload):
                print(f"[CI] ✗ 文件大小不符：{actual} != {len(payload)}")
                return 1
            if organized.read_bytes()[:64] != payload[:64]:
                print("[CI] ✗ 文件内容不一致")
                return 1
            expected_name = "Movie Dock Test (2020) - 1080p.mkv"
            if organized.name != expected_name:
                print(f"[CI] ✗ 命名不符：{organized.name} != {expected_name}")
                return 1
            print("[CI] ✅ 下载 → 整理 全链路通过")
            exit_code = 0
    finally:
        try:
            app_proc.terminate()
            app_proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            app_proc.kill()
        http_proc.terminate()
        for leftover in tmp.rglob("*.aria2"):
            leftover.unlink(missing_ok=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
