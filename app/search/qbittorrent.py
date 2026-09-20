"""qBittorrent WebUI 搜索源。

思路：qn 客户端自带搜索插件（yts/bt4g/kickass_torrent/limetorrents…），
本 provider 直接复用它的 /api/v2/search 接口，把结果转成候选列表。
比自己爬站点稳定得多，也不依赖大模型编链接。

配置（provider.options）：
  username / password   WebUI 账号（留空则尝试免登录访问）
  plugins               指定插件（逗号分隔），留空表示全部插件；
                        一个插件卡住会拖累整次搜索，建议固定几个快的
  category              搜索分类，默认 all
  limit                 拉取结果上限，默认 100
  search_timeout        轮询等待上限秒数，默认 45
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from ..config import ProviderConfig
from ..llm import detect_quality
from ..models import SearchRequest, SourceItem
from . import SearchProvider

# 推荐插件：yts/bt4g/kickass 这类响应快；避免默认全量插件（容易卡住）
# 注意：插件站点在境内可达性差异很大，实测经常只有少数可用
# （例：2026-09 某 NAS 上只有 piratebay 能在 3s 内返回，其余插件站点直连全挂）
DEFAULT_PLUGIN_HINT = "piratebay,yts,yts_am,bt4g,limetorrents,kickass_torrent,dmhyorg"
# 首次搜索（超时/无结果）后自动重试的“短名单”
FALLBACK_PLUGINS = "piratebay,dmhyorg"


def _human_size(n: Any) -> str:
    try:
        value = float(n)
    except (TypeError, ValueError):
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while value >= 1024 and i < len(units) - 1:
        value /= 1024
        i += 1
    return f"{value:.2f} {units[i]}"


def _classify(url: str) -> str:
    low = (url or "").lower()
    if low.startswith("magnet:"):
        return "magnet"
    if ".torrent" in low:
        return "torrent"
    if low.startswith("http"):
        return "http"
    return "unknown"


class QBittorrentProvider(SearchProvider):
    def __init__(self, pc: ProviderConfig):
        self.pc = pc
        self.name = pc.name or "qBittorrent 搜索"
        opts = pc.options or {}
        self.base = (pc.url or "http://127.0.0.1:8085").rstrip("/")
        self.username = str(opts.get("username") or "")
        self.password = str(opts.get("password") or "")
        self.plugins = str(opts.get("plugins") or "").strip()
        self.category = str(opts.get("category") or "all")
        try:
            self.limit = int(opts.get("limit") or 100)
        except (TypeError, ValueError):
            self.limit = 100
        try:
            self.search_timeout = float(opts.get("search_timeout") or 45)
        except (TypeError, ValueError):
            self.search_timeout = 45

    # ---------- 基础请求 ----------
    async def _login(self, client: httpx.AsyncClient) -> list[str]:
        warnings: list[str] = []
        if not self.username:
            return warnings
        try:
            resp = await client.post(
                f"{self.base}/api/v2/auth/login",
                data={"username": self.username, "password": self.password},
                headers={"Referer": self.base},
            )
        except httpx.HTTPError as exc:
            return [f"「{self.name}」登录失败：{exc}"]
        if resp.status_code == 403:
            return [f"「{self.name}」登录被拒绝（IP 被临时封禁，稍后再试）"]
        if resp.text.strip() != "Ok.":
            warnings.append(
                f"「{self.name}」登录未通过（返回 {resp.text.strip()[:40]!r}），将尝试匿名访问"
            )
        return warnings

    async def _plugins(self, client: httpx.AsyncClient) -> list[str]:
        try:
            resp = await client.get(f"{self.base}/api/v2/search/plugins")
            data = resp.json()
        except Exception:  # noqa: BLE001
            return []
        return [str(p.get("name") or p.get("fullName") or "") for p in data if isinstance(p, dict)]

    # ---------- 主流程 ----------
    async def search(self, req: SearchRequest) -> tuple[list[SourceItem], list[str]]:
        warnings: list[str] = []
        pattern = req.query.strip()
        if req.year:
            pattern = f"{pattern} {req.year}"
        if req.quality:
            pattern = f"{pattern} {req.quality}"

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            warnings.extend(await self._login(client))

            plugins = self.plugins
            if not plugins:
                available = await self._plugins(client)
                if not available:
                    return [], [
                        f"「{self.name}」未检测到搜索插件：请在 qBittorrent「搜索」页安装插件"
                        f"（推荐 {DEFAULT_PLUGIN_HINT}），或在设置里指定 plugins"
                    ]
                plugins = "all"

            results, status_raw, err = await self._search_once(client, pattern, plugins)

            # 首次无结果（尤其超时）多为插件站点不可达：换“短名单”再试一次
            if not results and plugins != FALLBACK_PLUGINS:
                warnings.append(
                    f"「{self.name}」插件 {plugins} 无结果/超时，已自动改用短名单 {FALLBACK_PLUGINS} 重试"
                )
                results, status_raw, err2 = await self._search_once(client, pattern, FALLBACK_PLUGINS)
                err = err2 or err

        if err:
            warnings.append(err)
        if str(status_raw).lower() in ("running", "queued"):
            if results:
                warnings.append("qBittorrent 搜索超时，已展示部分结果（可在 qBittorrent 搜索页手动重试）")
            else:
                return [], [
                    "qBittorrent 搜索超时且无结果：多为插件站点不可达，"
                    f"建议在设置里只保留可用的几个插件（如 {FALLBACK_PLUGINS}），"
                    "或先在 qBittorrent「搜索」页手动试一下哪些插件能用"
                ]
        if not results:
            warnings.append("qBittorrent 搜索完成但无结果（换关键词或换插件）")

        items = [self._to_item(raw, idx) for idx, raw in enumerate(results)]
        items = [i for i in items if i.url]
        if req.quality:
            q = req.quality.lower()
            filtered = [i for i in items if q in (i.resolution or i.quality or "").lower()]
            if filtered:
                items = filtered
        return items[: self.limit], warnings

    async def _search_once(
        self, client: httpx.AsyncClient, pattern: str, plugins: str
    ) -> tuple[list[dict[str, Any]], Any, str]:
        """跑一次搜索；返回 (结果, 状态, 错误提示)。"""
        try:
            start = await client.post(
                f"{self.base}/api/v2/search/start",
                data={"pattern": pattern, "plugins": plugins, "category": self.category},
            )
        except httpx.HTTPError as exc:
            return [], "", f"「{self.name}」连接失败：{exc}（确认 WebUI 地址与端口）"

        if start.status_code == 409:
            return [], "", f"「{self.name}」搜索任务数已达上限，请稍后重试或清空 qBittorrent 搜索页"
        if start.status_code >= 400:
            return [], "", f"「{self.name}」启动搜索失败：HTTP {start.status_code} {start.text[:120]}"
        try:
            search_id = int(start.json().get("id"))
        except Exception:  # noqa: BLE001
            return [], "", f"「{self.name}」返回异常：{start.text[:120]}"

        results: list[dict[str, Any]] = []
        status_raw: Any = ""
        deadline = time.monotonic() + self.search_timeout
        try:
            while time.monotonic() < deadline:
                resp = await client.get(
                    f"{self.base}/api/v2/search/results",
                    params={"id": search_id, "limit": self.limit, "offset": 0},
                )
                payload = resp.json() if resp.status_code == 200 else {}
                results = payload.get("results") or []
                status_raw = payload.get("status") or ""
                if str(status_raw).lower() not in ("running", "queued"):
                    break
                await asyncio.sleep(2 if results else 1.5)
        finally:
            try:
                await client.post(f"{self.base}/api/v2/search/stop", data={"id": search_id})
                await client.post(f"{self.base}/api/v2/search/delete", data={"id": search_id})
            except Exception:  # noqa: BLE001
                pass
        return results, status_raw, ""

    def _to_item(self, raw: dict[str, Any], idx: int) -> SourceItem:
        url = str(raw.get("fileUrl") or raw.get("magnet") or "").strip()
        title = str(raw.get("fileName") or raw.get("name") or "").strip()
        size_bytes = raw.get("fileSize")
        size = _human_size(size_bytes) if not isinstance(size_bytes, str) else size_bytes
        resolution, quality = detect_quality(title)
        note_bits = []
        if raw.get("siteUrl"):
            note_bits.append(str(raw["siteUrl"]))
        if raw.get("pubDate"):
            note_bits.append(str(raw["pubDate"])[:10])
        if url.startswith("magnet") is False and str(raw.get("descrLink") or ""):
            note_bits.append(str(raw["descrLink"]))
        return SourceItem(
            id=f"qbt-{idx}-{abs(hash(url)) % (10**10)}",
            title=title or f"结果 {idx + 1}",
            quality=quality,
            resolution=resolution,
            size=size or "",
            seeds=int(raw["nbSeeders"]) if str(raw.get("nbSeeders", "")).isdigit() else None,
            peers=int(raw["nbLeechers"]) if str(raw.get("nbLeechers", "")).isdigit() else None,
            source=self.name,
            url=url,
            url_type=_classify(url),  # type: ignore[arg-type]
            note=" · ".join(note_bits),
            raw={k: raw.get(k) for k in ("fileName", "fileSize", "nbSeeders", "nbLeechers", "siteUrl")},
        )
