# -*- coding: utf-8 -*-
"""本地冒烟测试：仅在开发机使用，不部署到飞牛。"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ["MOVIE_DOCK_CONFIG"] = str(ROOT / "config.yaml")
os.environ["DOWNLOAD_ROOT"] = str(ROOT / "downloads")
os.environ["SERVER_PORT"] = "8090"

import uvicorn

from app.main import app

config = uvicorn.Config(app, host="127.0.0.1", port=8090, log_level="warning")
server = uvicorn.Server(config)


def run():
    server.run()


t = threading.Thread(target=run, daemon=True)
t.start()

for _ in range(40):
    if server.started:
        break
    time.sleep(0.25)

base = "http://127.0.0.1:8090"
results = []
with httpx.Client(base_url=base, timeout=60.0) as client:
    h = client.get("/api/health").json()
    results.append(("health", h.get("name"), h.get("ok")))

    idx = client.get("/")
    results.append(("index", idx.status_code, "片坞" in idx.text))

    js = client.get("/static/app.js")
    results.append(("app.js", js.status_code, len(js.text)))

    search = client.post("/api/search", json={"query": "沙丘2", "year": 2024}).json()
    results.append(("search", len(search.get("items") or []), search.get("providers")))

    cfg = client.get("/api/config").json()
    results.append(("config_root", cfg.get("download_root"), cfg.get("llm", {}).get("model")))

    aria = client.get("/api/downloader/status").json()
    results.append(("aria2", aria.get("available"), aria.get("rpc_url")))

    org = client.post(
        "/api/organize/preview",
        json={"title": "沙丘2", "year": 2024, "quality": "1080p"},
    ).json()
    results.append(("organize", org.get("preview_path")))

    dl = client.post(
        "/api/download",
        json={
            "url": "https://example.com/demo/test-file.bin",
            "title": "测试影片",
            "year": 2024,
            "quality": "1080p",
            "organize": {
                "title": "测试影片",
                "year": 2024,
                "quality": "1080p",
                "enabled": True,
            },
        },
    ).json()
    results.append(("download_created", dl.get("ok"), (dl.get("task") or {}).get("task_id")))

    time.sleep(4)
    tasks = client.get("/api/tasks").json()
    for task in tasks:
        results.append(
            (
                "task",
                task.get("title"),
                task.get("status"),
                task.get("error"),
                task.get("organized_path") or task.get("saved_path"),
            )
        )

print(json.dumps(results, ensure_ascii=False, indent=2))
server.should_exit = True
time.sleep(0.5)
