from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from ..config import AppConfig, LLMConfig, ProviderConfig, SearchConfig, SubtitleConfig, save_app_config
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
    SubtitleFetchResponse,
    TaskOut,
)
from ..organizer import apply_template, parse_episode, parse_title_year
from ..ranking import annotate_scores, best_source, sort_by_score
from ..search import load_providers
from ..search import provider_type_labels
from ..subtitle import SubHDClient

router = APIRouter(prefix="/api")


def _mgr(request: Request) -> DownloadManager:
    return request.app.state.download_manager


def _cfg(request: Request) -> AppConfig:
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
        subtitle=cfg.subtitle.model_dump(),
        network=cfg.network.model_dump(),
        search_providers=[p.model_dump() for p in cfg.search.providers],
        search_sort_by_score=cfg.search.sort_by_score,
        aria2_rpc_url=cfg.downloader.aria2.rpc_url,
    )


@router.get("/provider-types")
async def get_provider_types() -> dict[str, str]:
    return provider_type_labels()


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
        for key in (
            "movie_dir_template",
            "file_name_template",
            "series_dir_template",
            "series_file_template",
            "unknown_year",
            "movies_subdir",
            "library_root",
        ):
            if data.get(key):
                setattr(cfg.organize, key, str(data[key]))
        if data.get("mode") in ("move", "copy", "hardlink"):
            cfg.organize.mode = data["mode"]
        # 明确允许清空 library_root / movies_subdir
        if "library_root" in data and data["library_root"] is not None:
            cfg.organize.library_root = str(data["library_root"]).strip()

    if body.subtitle is not None:
        data = body.subtitle
        if "enabled" in data and data["enabled"] is not None:
            cfg.subtitle.enabled = bool(data["enabled"])
        if "prefer_bilingual" in data and data["prefer_bilingual"] is not None:
            cfg.subtitle.prefer_bilingual = bool(data["prefer_bilingual"])
        if "prefer_simplified" in data and data["prefer_simplified"] is not None:
            cfg.subtitle.prefer_simplified = bool(data["prefer_simplified"])
        if "soft_fail" in data and data["soft_fail"] is not None:
            cfg.subtitle.soft_fail = bool(data["soft_fail"])
        for key in ("match_hint", "name_template", "provider"):
            if data.get(key):
                setattr(cfg.subtitle, key, str(data[key]))
        if isinstance(data.get("extra_keywords"), list):
            cfg.subtitle.extra_keywords = [str(k).strip() for k in data["extra_keywords"] if str(k).strip()]

    if body.network is not None:
        data = body.network
        if "proxy" in data and data["proxy"] is not None:
            cfg.network.proxy = str(data["proxy"]).strip()
        if data.get("timeout_seconds"):
            try:
                cfg.network.timeout_seconds = max(5, int(data["timeout_seconds"]))
            except (TypeError, ValueError):
                pass

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
                    options=dict(p.get("options") or {}),
                )
            )
        cfg.search = SearchConfig(providers=providers, sort_by_score=cfg.search.sort_by_score)

    if body.search_sort_by_score is not None:
        cfg.search.sort_by_score = bool(body.search_sort_by_score)

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

    sort_wanted = cfg.search.sort_by_score if body.sort_by_score is None else bool(body.sort_by_score)
    if sort_wanted:
        uniq = sort_by_score(uniq, prefer_resolution=body.quality or "", query=body.query, year=body.year)
    else:
        annotate_scores(uniq, prefer_resolution=body.quality or "", query=body.query, year=body.year)

    best = best_source(uniq, prefer_resolution=body.quality or "", query=body.query, year=body.year) if uniq else None
    return SearchResponse(query=body.query, items=uniq, providers=labels, warnings=warnings,
                          best_id=best.id if best else "")


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
        fetch_subtitle=body.fetch_subtitle,
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


@router.post("/tasks/{task_id}/subtitle", response_model=SubtitleFetchResponse)
async def retry_task_subtitle(request: Request, task_id: str) -> SubtitleFetchResponse:
    task = _mgr(request).get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    out = await _mgr(request).retry_subtitle(task)
    return SubtitleFetchResponse(ok=out.subtitle_status == "done",
                                 message=out.subtitle_note, files=[out.subtitle_path] if out.subtitle_path else [],
                                 task=out)


@router.get("/downloader/status")
async def downloader_status(request: Request) -> dict[str, Any]:
    return await _mgr(request).aria2_status()


@router.get("/subtitle/candidates")
async def subtitle_candidates(request: Request, keyword: str) -> dict[str, Any]:
    """按关键词列出 SubHD 字幕条目，便于人工确认匹配情况。"""
    kw = (keyword or "").strip()
    if not kw:
        raise HTTPException(status_code=400, detail="缺少 keyword")
    cfg = _cfg(request)
    client = SubHDClient(timeout=max(10, cfg.subtitle.timeout_seconds))
    try:
        entries = await asyncio.to_thread(client.list_by_keyword, kw)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"查询失败：{exc}", "entries": []}
    if not entries:
        return {"ok": False, "message": f"「{kw}」没有字幕条目", "entries": []}
    return {
        "ok": True,
        "message": f"共 {len(entries)} 条",
        "entries": [{"sid": e.sid, "title": e.title, "format": e.fmt} for e in entries],
    }


@router.post("/organize/preview")
async def organize_preview(request: Request, body: dict[str, Any]) -> dict[str, Any]:
    cfg = _cfg(request)
    title = body.get("title") or ""
    year = body.get("year")
    quality = body.get("quality") or ""
    if not title:
        return {"ok": False, "message": "缺少片名"}
    if not year:
        _, year = parse_title_year(title)

    episode_text = str(body.get("episode_text") or "")
    ext = str(body.get("ext") or ".mkv")
    season, episode = parse_episode(episode_text)

    opts = body.get("organize") if isinstance(body.get("organize"), dict) else {}
    manager = getattr(request.app.state, "download_manager", None)
    library_root = (opts or {}).get("library_root")

    if manager is not None:
        dest_dir, dest = manager.organizer.build_paths(
            title=title,
            year=year,
            quality=quality,
            episode_text=episode_text,
            library_root=library_root,
            ext=ext,
        )
        folder = dest_dir.name
        filename = dest.name
        preview_path = str(dest)
    else:  # 理论上不会走到
        folder = apply_template(cfg.organize.movie_dir_template, title=title, year=year, quality=quality,
                                unknown_year=cfg.organize.unknown_year)
        filename = apply_template(cfg.organize.file_name_template, title=title, year=year, quality=quality,
                                  ext=ext, unknown_year=cfg.organize.unknown_year)
        preview_path = str(cfg.library_root() / folder / filename)

    return {
        "ok": True,
        "year": year,
        "season": season,
        "episode": episode,
        "is_series": season is not None or episode is not None,
        "folder": folder,
        "filename": filename,
        "preview_path": preview_path,
        "host_hint": "应用内路径；请对照 compose 中 /downloads、library_root 在飞牛上的挂载目录换算。",
    }
