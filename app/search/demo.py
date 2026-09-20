from __future__ import annotations

import hashlib

from ..config import ProviderConfig
from ..llm import detect_quality
from ..models import SearchRequest, SourceItem
from . import SearchProvider


class DemoProvider(SearchProvider):
    """内置演示数据，便于不连外网时验证界面与下载链路。"""

    def __init__(self, pc: ProviderConfig | None = None):
        self.name = (pc.name if pc and pc.name else "演示数据")

    async def search(self, req: SearchRequest) -> tuple[list[SourceItem], list[str]]:
        query = req.query.strip()
        year = req.year or 2024
        digest = hashlib.md5(query.encode("utf-8")).hexdigest()[:8]
        samples = [
            {
                "title": f"{query} ({year}) 2160p UHD Demo",
                "quality": "2160p",
                "resolution": "2160p",
                "size": "18.2 GB",
                "seeds": 42,
                "peers": 12,
                "url_type": "magnet",
                "url": f"magnet:?xt=urn:btih:{digest}{'0'*(40-len(digest))}&dn={query}-2160p-demo",
                "note": "演示磁力，仅用于验证检索列表 UI；真实下载请配置检索源或粘贴有效链接",
            },
            {
                "title": f"{query} ({year}) 1080p BluRay Demo",
                "quality": "1080p",
                "resolution": "1080p",
                "size": "8.4 GB",
                "seeds": 88,
                "peers": 30,
                "url_type": "magnet",
                "url": f"magnet:?xt=urn:btih:{digest}{'1'*(40-len(digest))}&dn={query}-1080p-demo",
                "note": "演示数据",
            },
            {
                "title": f"{query} ({year}) 720p WEB-DL Demo",
                "quality": "720p",
                "resolution": "720p",
                "size": "3.1 GB",
                "seeds": 25,
                "peers": 8,
                "url_type": "http",
                "url": "https://example.com/demo/sample-720p.mkv",
                "note": "演示直链，example.com 不可真实下载",
            },
        ]
        if req.quality:
            q = req.quality.lower()
            samples = [s for s in samples if q in s["quality"].lower() or q in s["resolution"].lower()] or samples

        items: list[SourceItem] = []
        for i, s in enumerate(samples):
            res, quality = detect_quality(s["title"])
            items.append(
                SourceItem(
                    id=f"demo-{i}-{digest}",
                    title=s["title"],
                    quality=s["quality"] or quality,
                    resolution=s["resolution"] or res,
                    size=s["size"],
                    seeds=s["seeds"],
                    peers=s["peers"],
                    source=self.name,
                    url=s["url"],
                    url_type=s["url_type"],  # type: ignore[arg-type]
                    note=s["note"],
                )
            )
        return items, ["当前包含「演示数据」结果，用于验证界面流程。"]
