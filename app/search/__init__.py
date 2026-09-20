from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import AppConfig, ProviderConfig
from ..models import SearchRequest, SourceItem


class SearchProvider(ABC):
    name: str = "provider"

    @abstractmethod
    async def search(self, req: SearchRequest) -> tuple[list[SourceItem], list[str]]:
        """返回 (结果列表, 警告信息)。"""


def load_providers(cfg: AppConfig) -> list[SearchProvider]:
    from .builtin import BuiltinProvider
    from .custom_api import CustomApiProvider
    from .demo import DemoProvider
    from .llm_search import LLMSearchProvider
    from .qbittorrent import QBittorrentProvider
    from ..llm import LLMClient

    providers: list[SearchProvider] = []
    proxy = (cfg.network.proxy or "").strip()
    timeout = int(cfg.network.timeout_seconds or 20)
    for pc in cfg.search.providers:
        if not pc.enabled:
            continue
        if pc.type == "builtin":
            providers.append(BuiltinProvider(pc, global_proxy=proxy, global_timeout=timeout))
        elif pc.type == "demo":
            providers.append(DemoProvider(pc))
        elif pc.type == "llm":
            providers.append(LLMSearchProvider(LLMClient(cfg.llm), pc))
        elif pc.type == "qbittorrent":
            providers.append(QBittorrentProvider(pc))
        elif pc.type == "custom_api":
            providers.append(CustomApiProvider(pc, proxy=proxy))
    return providers


def provider_labels(cfg: AppConfig) -> list[str]:
    labels = []
    for pc in cfg.search.providers:
        if not pc.enabled:
            continue
        labels.append(pc.name or pc.type)
    return labels


def provider_type_labels() -> dict[str, str]:
    """前端设置页用的类型中文名。"""
    return {
        "builtin": "内置索引（推荐）",
        "demo": "演示数据",
        "llm": "大模型检索",
        "qbittorrent": "qBittorrent 搜索",
        "custom_api": "自定义索引",
    }


__all__ = [
    "SearchProvider",
    "load_providers",
    "provider_labels",
    "provider_type_labels",
    "ProviderConfig",
]
