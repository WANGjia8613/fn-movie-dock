from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

import httpx

from ..config import ProviderConfig
from ..llm import parse_llm_sources
from ..models import SearchRequest, SourceItem
from . import SearchProvider


class CustomApiProvider(SearchProvider):
    """用户自定义检索接口。

    约定：
    - GET 默认查询参数：q / query, year, quality
    - POST 时 JSON 提交相同字段
    - 响应 JSON 数组，或 {items|results|sources: [...]}
    - 字段兼容：title/name, url/magnet/link, quality, resolution, size, seeds, note
    """

    def __init__(self, pc: ProviderConfig):
        self.pc = pc
        self.name = pc.name or "自定义索引"

    async def search(self, req: SearchRequest) -> tuple[list[SourceItem], list[str]]:
        url = (self.pc.url or "").strip()
        if not url:
            return [], [f"「{self.name}」未配置 url，已跳过（可在设置中填写）"]

        params = {"q": req.query.strip(), "query": req.query.strip()}
        if req.year:
            params["year"] = str(req.year)
        if req.quality:
            params["quality"] = req.quality

        method = (self.pc.method or "GET").upper()
        headers = dict(self.pc.headers or {})
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                if method == "POST":
                    resp = await client.post(url, headers=headers, json=params)
                else:
                    sep = "&" if "?" in url else "?"
                    resp = await client.get(f"{url}{sep}{urlencode(params)}", headers=headers)
        except httpx.HTTPError as exc:
            return [], [f"「{self.name}」请求失败：{exc}"]

        if resp.status_code >= 400:
            return [], [f"「{self.name}」返回 HTTP {resp.status_code}"]

        try:
            data: Any = resp.json()
        except Exception:  # noqa: BLE001
            return [], [f"「{self.name}」响应不是 JSON"]

        if not isinstance(data, (list, dict)):
            return [], [f"「{self.name}」返回结构不受支持"]

        try:
            items = parse_llm_sources(json.dumps(data, ensure_ascii=False), provider_name=self.name)
        except Exception as exc:  # noqa: BLE001
            return [], [f"「{self.name}」解析失败：{exc}"]

        if not items:
            return [], [f"「{self.name}」未返回可用候选"]
        warnings: list[str] = []
        if any(i.url_type == "unknown" for i in items):
            warnings.append("部分链接类型未能识别，请优先选择磁力或直链。")
        return items, warnings
