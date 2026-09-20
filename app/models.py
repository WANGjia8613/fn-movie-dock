from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="片名或「片名 年份」")
    year: Optional[int] = None
    quality: Optional[str] = None  # 期望清晰度过滤提示，如 1080p
    sort_by_score: Optional[bool] = None  # 是否按评分排序（默认取配置）


class SourceItem(BaseModel):
    id: str
    title: str
    quality: str = "未知"
    resolution: str = ""
    size: str = ""
    seeds: Optional[int] = None
    peers: Optional[int] = None
    source: str = ""
    url: str = ""
    url_type: Literal["magnet", "torrent", "http", "unknown"] = "unknown"
    note: str = ""
    tags: list[str] = Field(default_factory=list)
    score: float = 0.0
    raw: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    items: list[SourceItem]
    providers: list[str]
    warnings: list[str] = Field(default_factory=list)
    best_id: str = ""


class LLMConfigIn(BaseModel):
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 60


class LLMTestResponse(BaseModel):
    ok: bool
    message: str
    model: str = ""
    detail: str = ""


class OrganizeOptionsIn(BaseModel):
    title: str
    year: Optional[int] = None
    quality: Optional[str] = None
    enabled: bool = True
    movie_dir_template: Optional[str] = None
    file_name_template: Optional[str] = None
    series_dir_template: Optional[str] = None
    series_file_template: Optional[str] = None
    mode: Optional[Literal["move", "copy", "hardlink"]] = None
    library_root: Optional[str] = None


class DownloadRequest(BaseModel):
    url: str = Field(..., min_length=4, description="磁力链接、种子URL或HTTP直链")
    title: str = ""
    year: Optional[int] = None
    quality: str = ""
    organize: OrganizeOptionsIn | None = None
    source_id: str = ""
    # 是否在完成后自动匹配中文字幕（缺省沿用配置）
    fetch_subtitle: Optional[bool] = None


class TaskOut(BaseModel):
    task_id: str
    gid: str = ""
    status: str
    title: str
    url: str
    quality: str = ""
    year: Optional[int] = None
    progress: float = 0.0
    download_speed: str = ""
    total_length: str = ""
    completed_length: str = ""
    files: list[str] = Field(default_factory=list)
    saved_path: str = ""
    organized_path: str = ""
    episode: str = ""
    tags: list[str] = Field(default_factory=list)
    subtitle_status: str = ""
    subtitle_path: str = ""
    subtitle_note: str = ""
    engine: str = ""
    error: str = ""
    created_at: str = ""
    updated_at: str = ""


class ConfigOut(BaseModel):
    llm: LLMConfigIn
    download_root: str
    organize: dict[str, Any]
    subtitle: dict[str, Any]
    search_providers: list[dict[str, Any]]
    search_sort_by_score: bool = True
    aria2_rpc_url: str


class ConfigUpdateIn(BaseModel):
    llm: LLMConfigIn | None = None
    organize: dict[str, Any] | None = None
    subtitle: dict[str, Any] | None = None
    search_providers: list[dict[str, Any]] | None = None
    search_sort_by_score: bool | None = None


class SubtitleFetchResponse(BaseModel):
    ok: bool
    message: str = ""
    files: list[str] = Field(default_factory=list)
    task: TaskOut | None = None
