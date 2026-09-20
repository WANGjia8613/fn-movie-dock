from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..config import LLMConfig, ProviderConfig, SearchConfig, save_app_config
from ..downloader import DownloadManager
from ..llm import LLMClient
from ..models import (
    ConfigOut,
    ConfigUpdateIn,
    DownloadRequest,
    LLMConfigIn,
    LLMTestResponse,
    SearchRequest,
    SearchResponse,
    TaskOut,
)
from ..search import load_providers

router = APIRouter(prefix="/api")


def _mgr(request: Request) -> DownloadManager:
    return request.app.state.download_manager


def _cfg(request: Request):
    return request.app.state.config


@router.get("/health")
async def health() -> dict[str, Any]:
    from .. import __version__

    return {"ok": True, "app": "movie-dock", "name": "片坞", "version": __version__}


@router.get("/config", response_model=ConfigOut)
async def get_config(request: Request) -> ConfigOut:
    cfg = _cfg(request)
    return ConfigOut(
        llm=LLMConfigIn(
            base_url=cfg.llm.base_url,
            api_key=cfg.llm.api_key,
            model=cfg.llm.model,
            timeout_seconds=cfg.llm.timeout_seconds,
        ),
        download_root=str(cfg.download_root()),
        organize=cfg.organize.model_dump(),
        search_providers=[p.model_dump() for p in cfg.search.providers],
        aria2_rpc_url=cfg.downloader.aria2.rpc_url,
    )


@router.put("/config")
async def update_config(request: Request, body: ConfigUpdateIn) -> dict[str, Any]:
    app = request.app.state
    cfg = app.config

    if body.llm is not None:
        cfg.llm = LLMConfig(
            base_url=(body.llm.base_url or "").rstrip("/"),
            api_key=body.llm.api_key or "",
            model=(body.llm.model or "").strip(),
            timeout_seconds=max(5, int(body.llm.timeout_seconds or 60)),
        )

    if body.organize is not None:
        data = body.organize
        if "enabled" in data and data["enabled"] is not None:
            cfg.organize.enabled = bool(data["enabled"])
        if data.get("movie_dir_template"):
            cfg.organize.movie_dir_template = str(data["movie_dir_template"])
        if data.get("file_name_template"):
            cfg.organize.file_name_template = str(data["file_name_template"])
        if data.get("mode") in ("move", "copy", "hardlink"):
            cfg.organize.mode = data["mode"]
        if data.get("unknown_year"):
            cfg.organize.unknown_year = str(data["unknown_year"])

    if body.search_providers is not None:
        providers: list[ProviderConfig] = []
        for p in body.search_providers:
            if not isinstance(p, dict):
                continue
            ptype = str(p.get("type") or "").strip()
            if not ptype:
                continue
            providers.append(
                ProviderConfig(
                    type=ptype,
                    enabled=bool(p.get("enabled", False)),
                    name=str(p.get("name") or ""),
                    url=str(p.get("url") or ""),
                    method=str(p.get("method") or "GET").upper(),
                    headers=dict(p.get("headers") or {}),
                )
            )
        cfg.search = SearchConfig(providers=providers)

    path = save_app_config(cfg)
    app.search_providers = load_providers(cfg)
    _mgr(request).apply_config(cfg)
    return {"ok": True, "config_path": str(path)}


@router.post("/llm/test", response_model=LLMTestResponse)
async def test_llm(body: LLMConfigIn) -> LLMTestResponse:
    client = LLMClient.from_in(body)
    return await client.test()


@router.post("/search", response_model=SearchResponse)
async def search(request: Request, body: SearchRequest) -> SearchResponse:
    cfg = _cfg(request)
    providers = getattr(request.app.state, "search_providers", None) or load_providers(cfg)
    if not providers:
        return SearchResponse(
            query=body.query,
            items=[],
            providers=[],
            warnings=["没有启用任何检索源，请在「设置」中打开演示数据、大模型检索或自定义索引。"],
        )

    items = []
    warnings: list[str] = []
    labels: list[str] = []
    for p in providers:
        labels.append(p.name)
        try:
            found, warns = await p.search(body)
            items.extend(found)
            warnings.extend(warns)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"「{p.name}」出错：{exc}")

    seen: set[str] = set()
    uniq = []
    for it in items:
        key = (it.url or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append(it)

    if body.quality:
        q = body.quality.lower()
        filtered = [
            it
            for it in uniq
            if q in (it.quality or "").lower() or q in (it.resolution or "").lower()
        ]
        if filtered:
            uniq = filtered
        else:
            warnings.append(f"没有匹配「{body.quality}」的结果，已展示全部候选。")

    return SearchResponse(query=body.query, items=uniq, providers=labels, warnings=warnings)


@router.post("/download")
async def create_download(request: Request, body: DownloadRequest) -> dict[str, Any]:
    mgr = _mgr(request)
    organize_dict = None
    if body.organize is not None:
        organize_dict = body.organize.model_dump(exclude_none=True)
    task = await mgr.start_download(
        url=body.url,
        title=body.title,
        year=body.year,
        quality=body.quality,
        organize=organize_dict,
    )
    return {"ok": True, "task": task.to_out().model_dump()}


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(request: Request) -> list[TaskOut]:
    return _mgr(request).list_tasks()


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(request: Request, task_id: str) -> TaskOut:
    task = _mgr(request).get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task.to_out()


@router.get("/downloader/status")
async def downloader_status(request: Request) -> dict[str, Any]:
    return await _mgr(request).aria2_status()


@router.post("/organize/preview")
async def organize_preview(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    from ..organizer import apply_template, parse_title_year

    cfg = _cfg(request)
    title = body.get("title") or ""
    year = body.get("year")
    quality = body.get("quality") or ""
    if not title:
        return {"ok": False, "message": "缺少片名"}
    if not year:
        _, year = parse_title_year(title)
    folder = apply_template(
        body.get("movie_dir_template") or cfg.organize.movie_dir_template,
        title=title,
        year=year,
        quality=quality,
        unknown_year=cfg.organize.unknown_year,
    )
    filename = apply_template(
        body.get("file_name_template") or cfg.organize.file_name_template,
        title=title,
        year=year,
        quality=quality,
        ext=".mkv",
        unknown_year=cfg.organize.unknown_year,
    )
    if not filename.lower().endswith(".mkv"):
        filename = f"{filename}.mkv"
    root = cfg.download_root()
    full = str(root / "movies" / folder / filename)
    return {
        "ok": True,
        "year": year,
        "folder": folder,
        "filename": filename,
        "preview_path": full,
        "host_hint": "应用内路径；请对照 compose 中 /downloads 在飞牛上的挂载目录换算。",
    }
