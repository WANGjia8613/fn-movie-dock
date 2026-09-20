from __future__ import annotations

from ..config import ProviderConfig
from ..llm import LLMClient, llm_find_sources
from ..models import SearchRequest, SourceItem
from . import SearchProvider


class LLMSearchProvider(SearchProvider):
    def __init__(self, client: LLMClient, pc: ProviderConfig | None = None):
        self.client = client
        self.name = pc.name if pc and pc.name else "大模型检索"

    async def search(self, req: SearchRequest) -> tuple[list[SourceItem], list[str]]:
        items, warnings = await llm_find_sources(
            self.client,
            req.query,
            year=req.year,
            quality=req.quality,
        )
        return items, warnings
