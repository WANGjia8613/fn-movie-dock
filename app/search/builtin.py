"""内置直连索引源（不依赖 qBittorrent，Windows 本地模式默认用它）。

已实测（2026-09，境内直连 / 走 Clash 代理）：

| 源 | 接口 | 直连 | 走代理 | 覆盖 |
|----|------|------|--------|------|
| TPB (apibay.org) | JSON | ✅ | ✅ | 电影/剧集，磁力 + 做种数 |
| YTS | JSON | ✖ | 部分 | 电影（小体积、做种多） |
| DMHY 动漫花园 | RSS | ✖ | ✅ | 动漫/剧集（中文标题） |

每个源都带镜像列表，按顺序尝试；任一成功即用。
配置（provider.options）：
  sources  例 "tpb,yts,dmhy"，默认 "tpb,yts,dmhy"
  proxy    该源专用代理；留空则用全局 network.proxy
  timeout  秒，默认取全局 network.timeout_seconds
  limit    每源最多条数，默认 60
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from typing import Any

import httpx

from ..config import ProviderConfig
from ..llm import detect_quality
from ..models import SearchRequest, SourceItem
from . import SearchProvider
from .common import build_magnet, classify_url, human_size, int_or_none

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class BuiltinSource(ABC):
    """单个索引源的实现。"""

    key: str = ""
    label: str = ""
    endpoints: list[str] = []

    def __init__(self, limit: int = 60):
        self.limit = limit

    @abstractmethod
    def parse(self, payload: Any, base: str) -> list[SourceItem]:
        ...

    def build_url(self, base: str, query: str) -> str:  # noqa: ARG002
        raise NotImplementedError

    async def search(
        self, client: httpx.AsyncClient, query: str, source_name: str
    ) -> tuple[list[SourceItem], str]:
        """按镜像顺序尝试；返回 (结果, 错误信息)。"""
        last_error = ""
        for base in self.endpoints:
            url = self.build_url(base, query)
            try:
                resp = await client.get(url, headers={"User-Agent": UA, "Referer": base})
            except httpx.HTTPError as exc:
                last_error = f"{base} 连接失败：{exc}"
                continue
            if resp.status_code >= 400:
                last_error = f"{base} HTTP {resp.status_code}"
                continue
            try:
                items = self.parse(resp.text, base)
            except Exception as exc:  # noqa: BLE001
                last_error = f"{base} 解析失败：{exc}"
                continue
            if items:
                return items[: self.limit], ""
            last_error = f"{base} 无结果"
        return [], f"「{source_name}」{self.label}：{last_error or '不可用'}"


# ---------------------------------------------------------------- TPB (apibay)
class TPBSource(BuiltinSource):
    key = "tpb"
    label = "海盗湾"
    endpoints = ["https://apibay.org", "https://apibay.nl"]

    def build_url(self, base: str, query: str) -> str:
        from urllib.parse import quote

        return f"{base}/q.php?q={quote(query)}"

    def parse(self, payload: Any, base: str) -> list[SourceItem]:
        import json

        data = json.loads(payload)
        if not isinstance(data, list):
            return []
        items: list[SourceItem] = []
        for idx, row in enumerate(data):
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            info_hash = str(row.get("info_hash") or "").strip()
            # apibay 无结果时会返回一条 name 为 "No results returned" 的占位
            if not name or not info_hash or "no results" in name.lower():
                continue
            resolution, quality = detect_quality(name)
            items.append(
                SourceItem(
                    id=f"tpb-{idx}-{info_hash[:8]}",
                    title=name,
                    quality=quality,
                    resolution=resolution,
                    size=human_size(row.get("size")),
                    seeds=int_or_none(row.get("seeders")),
                    peers=int_or_none(row.get("leechers")),
                    source=self.label,
                    url=build_magnet(info_hash, name),
                    url_type="magnet",
                    note=f"TPB · 文件数 {row.get('num_files', '?')}",
                    raw={"info_hash": info_hash},
                )
            )
        return items


# ---------------------------------------------------------------- YTS
class YTSSource(BuiltinSource):
    key = "yts"
    label = "YTS"
    endpoints = ["https://yts.mx", "https://yts.rs", "https://yts.lt", "https://yts.am"]

    def build_url(self, base: str, query: str) -> str:
        from urllib.parse import quote

        return f"{base}/api/v2/list_movies.json?query_term={quote(query)}&limit=50"

    def parse(self, payload: Any, base: str) -> list[SourceItem]:
        import json

        data = json.loads(payload)
        movies = ((data or {}).get("data") or {}).get("movies") or []
        items: list[SourceItem] = []
        for movie in movies:
            if not isinstance(movie, dict):
                continue
            title = str(movie.get("title_long") or movie.get("title") or "").strip()
            year = movie.get("year")
            if year and str(year) not in title:
                title = f"{title} ({year})"
            for torrent in movie.get("torrents") or []:
                if not isinstance(torrent, dict):
                    continue
                quality = str(torrent.get("quality") or "")
                resolution, _ = detect_quality(quality)
                info_hash = str(torrent.get("hash") or "")
                label = f"{title} {quality} {torrent.get('type', '')} {torrent.get('video_codec', '')}".strip()
                items.append(
                    SourceItem(
                        id=f"yts-{info_hash[:10] or len(items)}",
                        title=label,
                        quality=quality or "未知",
                        resolution=resolution,
                        size=human_size(torrent.get("size_bytes")) or str(torrent.get("size") or ""),
                        seeds=int_or_none(torrent.get("seeds")),
                        peers=int_or_none(torrent.get("peers")),
                        source=self.label,
                        url=build_magnet(info_hash, label),
                        url_type="magnet" if info_hash else "unknown",
                        note=f"YTS · {torrent.get('type', '')}".strip(),
                        raw={"hash": info_hash},
                    )
                )
        return [i for i in items if i.url_type != "unknown"]


# ---------------------------------------------------------------- DMHY (RSS)
class DMHYSource(BuiltinSource):
    key = "dmhy"
    label = "动漫花园"
    endpoints = ["https://share.dmhy.org", "https://dmhy.org"]

    def build_url(self, base: str, query: str) -> str:
        from urllib.parse import quote

        return f"{base}/topics/rss/rss.xml?keyword={quote(query)}"

    def parse(self, payload: Any, base: str) -> list[SourceItem]:
        root = ET.fromstring(payload)
        items: list[SourceItem] = []
        for entry in root.iter("item"):
            title = (entry.findtext("title") or "").strip()
            enclosure = entry.find("enclosure")
            magnet = ""
            if enclosure is not None:
                magnet = enclosure.get("url") or ""
            if not magnet:
                for el in entry.iter():
                    text = (el.text or "").strip()
                    if text.startswith("magnet:"):
                        magnet = text
                        break
            if not title or not magnet.startswith("magnet:"):
                continue
            size_match = re.search(r"([\d.]+)\s*(GB|MB)", entry.findtext("description") or "", re.I)
            size = f"{size_match.group(1)} {size_match.group(2).upper()}" if size_match else ""
            resolution, quality = detect_quality(title)
            items.append(
                SourceItem(
                    id=f"dmhy-{len(items)}",
                    title=title,
                    quality=quality,
                    resolution=resolution,
                    size=size,
                    source=self.label,
                    url=magnet,
                    url_type="magnet",
                    note="DMHY · " + (entry.findtext("pubDate") or "")[:16],
                )
            )
        return items


_BUILTIN_SOURCES: dict[str, type[BuiltinSource]] = {
    TPBSource.key: TPBSource,
    YTSSource.key: YTSSource,
    DMHYSource.key: DMHYSource,
}

DEFAULT_SOURCES = "tpb,yts,dmhy"


class BuiltinProvider(SearchProvider):
    """内置直连索引源聚合（默认开启，不依赖 qBittorrent）。"""

    def __init__(
        self,
        pc: ProviderConfig,
        *,
        global_proxy: str = "",
        global_timeout: int = 20,
    ):
        self.pc = pc
        self.name = pc.name or "内置索引"
        opts = pc.options or {}
        keys = [k.strip().lower() for k in str(opts.get("sources") or DEFAULT_SOURCES).split(",") if k.strip()]
        self.sources = [_BUILTIN_SOURCES[k]() for k in keys if k in _BUILTIN_SOURCES]
        if not self.sources:
            self.sources = [TPBSource()]
        self.proxy = str(opts.get("proxy") or global_proxy or "").strip()
        try:
            self.timeout = float(opts.get("timeout") or global_timeout or 20)
        except (TypeError, ValueError):
            self.timeout = 20.0
        try:
            self.limit = int(opts.get("limit") or 60)
        except (TypeError, ValueError):
            self.limit = 60

    async def search(self, req: SearchRequest) -> tuple[list[SourceItem], list[str]]:
        query = req.query.strip()
        if query:
            hints = [query]
            if req.year:
                hints.append(f"{query} {req.year}")
        else:
            return [], ["「内置索引」请输入片名"]

        warnings: list[str] = []
        items: list[SourceItem] = []
        timeout = httpx.Timeout(self.timeout, connect=min(10.0, self.timeout))
        client_kwargs: dict[str, Any] = {"timeout": timeout, "follow_redirects": True}
        if self.proxy:
            client_kwargs["proxy"] = self.proxy
        async with httpx.AsyncClient(**client_kwargs) as client:  # type: ignore[arg-type]
            for source in self.sources:
                source.limit = self.limit
                for hint in hints:
                    found, err = await source.search(client, hint, self.name)
                    if err:
                        if hint == hints[0]:
                            warnings.append(err)
                        continue
                    items.extend(found)
                    break  # 该源用第一个有结果的提示词即可

        if not items:
            warnings.append(
                f"内置索引（{', '.join(s.label for s in self.sources)}）都没有结果："
                "换关键词、或在设置里给该源配代理（全局 network.proxy）"
            )

        # 去重（按 url）
        seen: set[str] = set()
        uniq: list[SourceItem] = []
        for item in items:
            key = item.url or ""
            if not key or key in seen:
                continue
            seen.add(key)
            uniq.append(item)

        if req.quality:
            q = req.quality.lower()
            filtered = [i for i in uniq if q in (i.resolution or i.quality or "").lower()]
            if filtered:
                uniq = filtered
        return uniq, warnings


__all__ = ["BuiltinProvider", "TPBSource", "YTSSource", "DMHYSource", "DEFAULT_SOURCES", "classify_url"]
