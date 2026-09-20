# -*- coding: utf-8 -*-
"""代码复查后的本地回归测试（仅开发机）。"""
from __future__ import annotations

import copy
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# --- 单元级：配置深拷贝 / 解析 / 清晰度 / 整理 ---
from app.config import _DEFAULT_DATA, load_config, save_app_config

try:  # Windows 控制台编码
    from app.runtime import ensure_utf8

    ensure_utf8()
except Exception:
    pass
from app.llm import detect_quality, parse_llm_sources
from app.organizer import Organizer, apply_template, parse_title_year
from app.config import OrganizeConfig

results = []


def check(name, cond, detail=""):
    results.append((name, "PASS" if cond else "FAIL", detail))


# 1) 默认配置不被 load 污染
before = copy.deepcopy(_DEFAULT_DATA)
os.environ["LLM_API_KEY"] = "sk-test-key-should-not-leak-to-default"
os.environ["DOWNLOAD_ROOT"] = str(ROOT / "downloads")
cfg1 = load_config(ROOT / "config.yaml")
check("env_api_key_applied", cfg1.llm.api_key == "sk-test-key-should-not-leak-to-default", cfg1.llm.api_key)
check("default_not_polluted", _DEFAULT_DATA["llm"]["api_key"] == before["llm"]["api_key"], repr(_DEFAULT_DATA["llm"]["api_key"]))
check("download_root_local", "movie-dock" in cfg1.paths.download_root.replace("\\", "/"), cfg1.paths.download_root)

# 2) 清晰度识别：HDR 不应误判为 720p
r, q = detect_quality("Movie.Name.2024.HDR.2160p.UHD.BluRay")
check("quality_hdr_2160p", q in ("4K", "2160p") or r == "2160p", f"{r}/{q}")
r2, q2 = detect_quality("Something.HDR.x265")
check("quality_hdr_unknown", r2 == "" and q2 == "未知", f"{r2}/{q2}")

# 3) parse_llm_sources 非 JSON 兜底
items = parse_llm_sources("没有 JSON，但有磁力 magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567")
check("parse_non_json_magnet", any(i.url_type == "magnet" for i in items), str(len(items)))
items2 = parse_llm_sources('```json\n[{"title":"A 1080p","url":"magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","quality":"1080p","seeds":"12"}]\n```')
check("parse_json_ok", len(items2) == 1 and items2[0].seeds == 12, items2[0].title if items2 else "empty")

# 4) 年份解析
t, y = parse_title_year("沙丘2 (2024) 1080p BluRay")
check("parse_title_year", t == "沙丘2" and y == 2024, f"{t}/{y}")
t2, y2 = parse_title_year("银翼杀手2049")
check("parse_year_edge", y2 in (2049, None), f"{t2}/{y2}")

# 5) 整理文件
with tempfile.TemporaryDirectory() as td:
    td_path = Path(td)
    src = td_path / "raw" / "file.mkv"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x" * 10)
    org = Organizer(OrganizeConfig(enabled=True, mode="copy"), td_path / "dl")
    final = org.organize_file(src, title="沙丘2", year=2024, quality="1080p", options={"enabled": True, "mode": "copy"})
    check("organize_path", final.name == "沙丘2 (2024) - 1080p.mkv" and final.exists(), str(final))
    folder = apply_template("{title} ({year})", title="测试", year=None, unknown_year="未知年份")
    check("organize_unknown_year", folder == "测试 (未知年份)", folder)

# 6) 配置持久化（先去掉环境变量，验证文件层写入）
os.environ.pop("LLM_API_KEY", None)
os.environ.pop("DOWNLOAD_ROOT", None)
tmp_cfg = ROOT / "downloads" / "_test_config.yaml"
os.environ["MOVIE_DOCK_CONFIG"] = str(tmp_cfg)
if tmp_cfg.exists():
    tmp_cfg.unlink()
cfg2 = load_config(tmp_cfg)
# 环境变量优先是预期行为：清空后再测文件持久化
check("default_has_custom_api", any(p.type == "custom_api" for p in cfg2.search.providers), [p.type for p in cfg2.search.providers])
cfg2.llm.api_key = "sk-persist"
cfg2.llm.base_url = "https://example.com/v1"
cfg2.organize.movie_dir_template = "{title}_{year}"
for p in cfg2.search.providers:
    if p.type == "demo":
        p.enabled = False
save_app_config(cfg2)
cfg3 = load_config(tmp_cfg)
check("persist_llm", cfg3.llm.api_key == "sk-persist" and cfg3.llm.base_url == "https://example.com/v1", f"{cfg3.llm.api_key}/{cfg3.llm.base_url}")
check("persist_organize", cfg3.organize.movie_dir_template == "{title}_{year}", cfg3.organize.movie_dir_template)
demo_p = next(p for p in cfg3.search.providers if p.type == "demo")
check("persist_provider", demo_p.enabled is False, str(demo_p.enabled))

# 7) HTTP API 回归（使用临时配置，避免污染项目 config.yaml）
api_cfg_path = ROOT / "downloads" / "_api_test_config.yaml"
if api_cfg_path.exists():
    api_cfg_path.unlink()
# 先生成一份可用基础配置
os.environ["MOVIE_DOCK_CONFIG"] = str(api_cfg_path)
os.environ["DOWNLOAD_ROOT"] = str(ROOT / "downloads")
os.environ.pop("LLM_API_KEY", None)
os.environ["SERVER_PORT"] = "8091"
base_cfg = load_config(api_cfg_path)
save_app_config(base_cfg)

import httpx
import uvicorn
from app.main import app

config = uvicorn.Config(app, host="127.0.0.1", port=8091, log_level="warning")
server = uvicorn.Server(config)
threading.Thread(target=server.run, daemon=True).start()
for _ in range(40):
    if server.started:
        break
    time.sleep(0.25)

base = "http://127.0.0.1:8091"
with httpx.Client(base_url=base, timeout=60.0) as client:
    h = client.get("/api/health").json()
    check("api_health", h.get("ok") is True and h.get("name") == "片坞", str(h))
    check("api_index", "片坞" in client.get("/").text, "index")
    search = client.post("/api/search", json={"query": "沙丘2", "year": 2024}).json()
    check("api_search_demo", len(search.get("items") or []) >= 1, str(len(search.get("items") or [])))
    # 保存自定义索引配置
    cfg_api = client.get("/api/config").json()
    providers = cfg_api["search_providers"]
    found_custom = False
    for p in providers:
        if p["type"] == "custom_api":
            p["enabled"] = True
            p["url"] = "http://127.0.0.1:9/not-exist"
            p["name"] = "测试索引"
            p["method"] = "GET"
            found_custom = True
    if not found_custom:
        providers.append({
            "type": "custom_api",
            "enabled": True,
            "name": "测试索引",
            "url": "http://127.0.0.1:9/not-exist",
            "method": "GET",
            "headers": {},
        })
    put = client.put(
        "/api/config",
        json={
            "llm": cfg_api["llm"],
            "organize": {
                "movie_dir_template": "{title} ({year})",
                "file_name_template": "{title} ({year}) - {quality}",
                "mode": "copy",
                "enabled": True,
            },
            "search_providers": providers,
        },
    ).json()
    check("api_config_put", put.get("ok") is True, str(put))
    cfg_api2 = client.get("/api/config").json()
    custom = [p for p in cfg_api2["search_providers"] if p["type"] == "custom_api"]
    check(
        "api_custom_provider_saved",
        bool(custom) and custom[0].get("url") == "http://127.0.0.1:9/not-exist",
        str(custom),
    )
    search2 = client.post("/api/search", json={"query": "测试"}).json()
    check("api_search_custom_warn", any("测试索引" in w for w in search2.get("warnings") or []), str(search2.get("warnings")))
    org = client.post("/api/organize/preview", json={"title": "沙丘2", "year": 2024, "quality": "1080p"}).json()
    check("api_organize_preview", "沙丘2 (2024)" in org.get("preview_path", ""), org.get("preview_path", ""))

server.should_exit = True
time.sleep(0.4)

print("=" * 60)
failed = 0
for name, status, detail in results:
    print(f"[{status}] {name} :: {detail}")
    if status == "FAIL":
        failed += 1
print("=" * 60)
print(f"TOTAL={len(results)} FAIL={failed}")
sys.exit(1 if failed else 0)
