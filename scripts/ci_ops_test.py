#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真机验证：下载 → 暂停 → 继续 → 删除记录（保留文件）→ 连文件删除。

用法：python scripts/ci_ops_test.py [--port 8088] [--aria2-port 6812] [--size-mb 24]
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

try:
    from app.runtime import ensure_utf8

    ensure_utf8()
except Exception:  # noqa: BLE001
    pass

from scripts.ci_download_test import MEDIA_NAME, free_port, write_test_config  # noqa: E402

RANGE_SERVER = '''
import http.server, os, re, socketserver

class Handler(http.server.SimpleHTTPRequestHandler):
    def send_head(self):
        path = self.translate_path(self.path)
        if not os.path.isfile(path):
            self.send_error(404)
            return None
        size = os.path.getsize(path)
        rng = self.headers.get("Range")
        f = open(path, "rb")
        if rng:
            m = re.match(r"bytes=(\\d+)-(\\d*)", rng)
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            f.seek(start)
            self._remaining = end - start + 1
            return f
        self.send_response(200)
        self.send_header("Content-Length", str(size))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        return f

    def copyfile(self, src, dst):
        remaining = getattr(self, "_remaining", None)
        if remaining is None:
            return super().copyfile(src, dst)
        while remaining > 0:
            chunk = src.read(min(65536, remaining))
            if not chunk:
                break
            dst.write(chunk)
            remaining -= len(chunk)
        if hasattr(self, "_remaining"):
            del self._remaining

socketserver.TCPServer.allow_reuse_address = True
http.server.test(HandlerClass=Handler, port=PORT, bind="127.0.0.1")
'''


def serve_file_range(directory: Path, port: int) -> subprocess.Popen:
    """支持 Range 的本地 HTTP 服务（真实站点都支持断点续传）。"""
    script = directory.parent / f"range_server_{port}.py"
    script.write_text(RANGE_SERVER.replace("PORT", str(port)), encoding="utf-8")
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, str(script)],
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
    raise RuntimeError("Range HTTP 服务启动失败")

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8088)
    ap.add_argument("--aria2-port", type=int, default=6812)
    ap.add_argument("--size-mb", type=int, default=24)
    args = ap.parse_args()

    import httpx

    app_port = free_port(args.port)
    aria2_port = free_port(args.aria2_port)
    tmp = Path(tempfile.mkdtemp(prefix="moviedock-ops-"))
    http_root = tmp / "http"
    http_root.mkdir(parents=True, exist_ok=True)
    payload = os.urandom(args.size_mb * 1024 * 1024)
    (http_root / MEDIA_NAME).write_bytes(payload)

    config_path = tmp / "config.yaml"
    # 限速，方便中途暂停（aria2 单任务选项：max-download-limit）
    write_test_config(
        config_path,
        tmp / "downloads",
        tmp / "data",
        aria2_port,
        extra_options={"max-download-limit": "700K"},
    )

    http_port = free_port(8902)
    http_proc = serve_file_range(http_root, http_port)
    env = dict(os.environ, MOVIE_DOCK_CONFIG=str(config_path), PYTHONUNBUFFERED="1")
    app_proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "app.desktop", "--headless", "--host", "127.0.0.1",
         "--port", str(app_port), "--config", str(config_path), "--log-level", "warning"],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    threading.Thread(
        target=lambda: [print("[app]", line.rstrip()) for line in (app_proc.stdout or [])],
        daemon=True,
    ).start()

    base = f"http://127.0.0.1:{app_port}"
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"[{'PASS' if cond else 'FAIL'}] {name} :: {detail}")
        if not cond:
            failures.append(name)

    try:
        with httpx.Client(base_url=base, timeout=30.0) as client:
            for _ in range(60):
                try:
                    if client.get("/api/health").json().get("ok"):
                        break
                except Exception:  # noqa: BLE001
                    time.sleep(0.5)
            else:
                print("[ops] ✗ 服务未就绪")
                return 1

            task = client.post("/api/download", json={
                "url": f"http://127.0.0.1:{http_port}/{MEDIA_NAME}",
                "title": "Ops Test", "year": 2020, "quality": "1080p",
                "fetch_subtitle": False,
                "organize": {"title": "Ops Test", "year": 2020, "quality": "1080p",
                             "enabled": True, "mode": "move"},
            }).json()["task"]
            tid = task["task_id"]
            print(f"[ops] 任务已创建 {tid}（{len(payload)} B，限速 800K/s）")

            # 等到 3%~70% 之间（确保下载中且没下完）
            current = None
            for _ in range(120):
                time.sleep(0.5)
                current = next((t for t in client.get("/api/tasks").json() if t["task_id"] == tid), None)
                if not current:
                    continue
                if current["status"] in ("complete", "error"):
                    break
                if 3 <= current["progress"] <= 70:
                    break
            check("download_in_progress",
                  bool(current and current["status"] == "active" and 0 < current["progress"] < 100),
                  f"{current['status'] if current else '-'} {current['progress'] if current else '-'}%")

            paused = client.post(f"/api/tasks/{tid}/pause").json()
            check("api_pause", paused.get("status") == "paused", str(paused.get("status")))
            time.sleep(3)
            after = next(t for t in client.get("/api/tasks").json() if t["task_id"] == tid)
            check("paused_progress_frozen",
                  after["status"] == "paused" and after["download_speed"] == "",
                  f"{after['status']} {after['download_speed'] or '(无速度)'}")

            resumed = client.post(f"/api/tasks/{tid}/resume").json()
            check("api_resume", resumed.get("status") == "active", str(resumed.get("status")))

            final = None
            for _ in range(180):
                time.sleep(1)
                cur = next((t for t in client.get("/api/tasks").json() if t["task_id"] == tid), None)
                if cur and cur["status"] in ("complete", "error"):
                    final = cur
                    break
            check("download_completed", bool(final and final["status"] == "complete"),
                  (final or {}).get("error", "")[:80])
            organized = Path((final or {}).get("organized_path") or "")
            check("organized_exists", organized.exists(), str(organized))
            check("organized_size", organized.exists() and organized.stat().st_size == len(payload),
                  f"{organized.stat().st_size if organized.exists() else 0} B")

            # 只删记录：文件保留
            res = client.request("DELETE", f"/api/tasks/{tid}").json()
            check("delete_record_only", res.get("ok") and organized.exists(),
                  f"removed_files={res.get('removed_files')}")
            check("task_gone", all(t["task_id"] != tid for t in client.get("/api/tasks").json()), "ok")

            # 连文件一起删
            task2 = client.post("/api/download", json={
                "url": f"http://127.0.0.1:{http_port}/{MEDIA_NAME}",
                "title": "Ops Test 2", "year": 2020, "quality": "1080p", "fetch_subtitle": False,
                "organize": {"title": "Ops Test 2", "year": 2020, "quality": "1080p",
                             "enabled": True, "mode": "move"},
            }).json()["task"]
            tid2 = task2["task_id"]
            final2 = None
            for _ in range(180):
                time.sleep(1)
                cur = next((t for t in client.get("/api/tasks").json() if t["task_id"] == tid2), None)
                if cur and cur["status"] in ("complete", "error"):
                    final2 = cur
                    break
            organized2 = Path((final2 or {}).get("organized_path") or "")
            res2 = client.request("DELETE", f"/api/tasks/{tid2}", params={"delete_files": "true"}).json()
            check("delete_with_files", not organized2.exists() and res2.get("removed_files"),
                  f"删除 {len(res2.get('removed_files') or [])} 项")

            print(f"[ops] 共 {len(failures)} 项失败" + (f"：{failures}" if failures else ""))
            return 1 if failures else 0
    finally:
        for proc in (app_proc, http_proc):
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
