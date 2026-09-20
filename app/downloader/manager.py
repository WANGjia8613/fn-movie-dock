from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from ..config import AppConfig
from ..models import TaskOut
from ..organizer import Organizer, parse_title_year
from .http_fallback import download_http_to


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _human_size(n: float | int | None) -> str:
    if n is None:
        return ""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    return f"{n:.2f} {units[i]}"


@dataclass
class DownloadTask:
    task_id: str
    gid: str = ""
    status: str = "queued"
    title: str = ""
    url: str = ""
    quality: str = ""
    year: Optional[int] = None
    progress: float = 0.0
    download_speed: str = ""
    total_length: str = ""
    completed_length: str = ""
    files: list[str] = field(default_factory=list)
    saved_path: str = ""
    organized_path: str = ""
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    organize_opts: dict[str, Any] = field(default_factory=dict)
    engine: str = "aria2"
    http_dest: str = ""

    def to_out(self) -> TaskOut:
        return TaskOut(
            task_id=self.task_id,
            gid=self.gid,
            status=self.status,
            title=self.title,
            url=self.url,
            quality=self.quality,
            year=self.year,
            progress=self.progress,
            download_speed=self.download_speed,
            total_length=self.total_length,
            completed_length=self.completed_length,
            files=list(self.files),
            saved_path=self.saved_path,
            organized_path=self.organized_path,
            error=self.error,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class Aria2Client:
    def __init__(self, rpc_url: str, secret: str = ""):
        self.rpc_url = rpc_url
        self.secret = secret
        self._id = 0

    async def call(self, method: str, params: list[Any] | None = None) -> Any:
        self._id += 1
        if self.secret:
            params = [f"token:{self.secret}", *(params or [])]
        else:
            params = params or []
        payload = {"jsonrpc": "2.0", "id": str(self._id), "method": method, "params": params}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(self.rpc_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        if "error" in data:
            raise RuntimeError(str(data["error"]))
        return data.get("result")

    async def add_uri(self, uris: list[str], options: dict[str, Any]) -> str:
        result = await self.call("aria2.addUri", [uris, options])
        return str(result)

    async def tell_status(self, gid: str) -> dict[str, Any]:
        keys = [
            "gid",
            "status",
            "totalLength",
            "completedLength",
            "downloadSpeed",
            "files",
            "errorMessage",
            "dir",
        ]
        result = await self.call("aria2.tellStatus", [gid, keys])
        return result if isinstance(result, dict) else {}

    async def is_available(self) -> bool:
        try:
            ver = await self.call("aria2.getVersion")
            return bool(ver)
        except Exception:  # noqa: BLE001
            return False


class DownloadManager:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.tasks: dict[str, DownloadTask] = {}
        self.aria2 = Aria2Client(cfg.downloader.aria2.rpc_url, cfg.downloader.aria2.rpc_secret)
        self.organizer = Organizer(cfg.organize, cfg.download_root())
        self._poller: asyncio.Task | None = None
        self._background_tasks: set[asyncio.Task] = set()

    def apply_config(self, cfg: AppConfig) -> None:
        """配置热更新：同步下载根目录、整理规则、aria2 RPC。"""
        self.cfg = cfg
        self.organizer = Organizer(cfg.organize, cfg.download_root())
        self.aria2 = Aria2Client(cfg.downloader.aria2.rpc_url, cfg.downloader.aria2.rpc_secret)
        try:
            cfg.download_root().mkdir(parents=True, exist_ok=True)
            cfg.incoming_dir().mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def start_background(self) -> None:
        if self._poller is None:
            self._poller = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._poller:
            self._poller.cancel()
            try:
                await self._poller
            except asyncio.CancelledError:
                pass
            self._poller = None
        for t in list(self._background_tasks):
            t.cancel()
        self._background_tasks.clear()

    def list_tasks(self) -> list[TaskOut]:
        items = sorted(self.tasks.values(), key=lambda t: t.created_at, reverse=True)
        return [t.to_out() for t in items]

    def get(self, task_id: str) -> DownloadTask | None:
        return self.tasks.get(task_id)

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    async def start_download(
        self,
        url: str,
        title: str = "",
        year: int | None = None,
        quality: str = "",
        organize: dict[str, Any] | None = None,
    ) -> DownloadTask:
        url = (url or "").strip()
        if not title:
            parsed_title, parsed_year = parse_title_year(url)
            title = parsed_title or "未命名任务"
            if year is None:
                year = parsed_year
        else:
            t2, y2 = parse_title_year(title)
            if t2:
                title = t2
            if year is None:
                year = y2

        task = DownloadTask(
            task_id=uuid.uuid4().hex[:12],
            title=title,
            url=url,
            quality=quality or "",
            year=year,
            status="queued",
            created_at=_now(),
            updated_at=_now(),
            organize_opts=organize or {},
        )
        self.tasks[task.task_id] = task
        self._spawn(self._run_task(task))
        return task

    def _classify(self, url: str) -> str:
        low = (url or "").lower()
        if low.startswith("magnet:"):
            return "magnet"
        if ".torrent" in low:
            return "torrent"
        if low.startswith("http://") or low.startswith("https://"):
            return "http"
        return "unknown"

    async def _run_task(self, task: DownloadTask) -> None:
        kind = self._classify(task.url)
        try:
            if kind in ("magnet", "torrent", "http"):
                aria2_ok = await self.aria2.is_available()
            else:
                aria2_ok = False

            if aria2_ok:
                task.engine = "aria2"
                await self._start_aria2(task)
            elif kind == "http":
                task.engine = "http"
                await self._start_http(task)
            else:
                task.status = "error"
                task.error = (
                    "当前环境未检测到 aria2 下载引擎，且该链接不是 HTTP 直链，无法下载磁力/种子。"
                    "请在飞牛上通过 Docker 部署本应用（镜像内置 aria2），或先配置 aria2 RPC。"
                )
                task.updated_at = _now()
        except Exception as exc:  # noqa: BLE001
            task.status = "error"
            task.error = str(exc)
            task.updated_at = _now()

    async def _start_aria2(self, task: DownloadTask) -> None:
        incoming = self.cfg.incoming_dir()
        incoming.mkdir(parents=True, exist_ok=True)
        options: dict[str, Any] = {
            "dir": str(incoming),
            "seed-time": "0",
            "bt-max-peers": "64",
            "max-connection-per-server": "8",
            "split": "8",
            "continue": "true",
            "auto-file-renaming": "true",
            "allow-overwrite": "false",
            "file-allocation": "none",
        }
        gid = await self.aria2.add_uri([task.url], options)
        task.gid = gid
        task.status = "active"
        task.updated_at = _now()

    async def _start_http(self, task: DownloadTask) -> None:
        incoming = self.cfg.incoming_dir()
        incoming.mkdir(parents=True, exist_ok=True)
        path = await download_http_to(
            task.url,
            incoming,
            preferred_name=task.title,
            on_progress=lambda done, total, speed: self._on_http_progress(task, done, total, speed),
        )
        task.http_dest = str(path)
        task.files = [str(path)]
        task.saved_path = str(path)
        task.progress = 100.0
        task.status = "complete"
        if path.exists():
            task.completed_length = task.total_length or _human_size(path.stat().st_size)
        task.updated_at = _now()
        self._organize_if_needed(task, [path] if path.exists() else [])

    def _on_http_progress(self, task: DownloadTask, done: int, total: int, speed: float) -> None:
        task.completed_length = _human_size(done)
        task.total_length = _human_size(total) if total else ""
        task.progress = round(done * 100 / total, 2) if total else 0.0
        task.download_speed = _human_size(speed) + "/s" if speed else ""
        task.status = "active"
        task.updated_at = _now()

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._poll_once()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(2)

    async def _poll_once(self) -> None:
        pending = [
            t
            for t in self.tasks.values()
            if t.engine == "aria2"
            and t.gid
            and t.status in ("queued", "active", "paused", "waiting")
        ]
        if not pending:
            return
        for task in pending:
            try:
                st = await self.aria2.tell_status(task.gid)
            except Exception as exc:  # noqa: BLE001
                task.error = str(exc)
                continue
            status = str(st.get("status") or "")
            if status:
                task.status = status
            try:
                total = int(st.get("totalLength") or 0)
            except (TypeError, ValueError):
                total = 0
            try:
                done = int(st.get("completedLength") or 0)
            except (TypeError, ValueError):
                done = 0
            try:
                speed = int(st.get("downloadSpeed") or 0)
            except (TypeError, ValueError):
                speed = 0
            task.total_length = _human_size(total) if total else ""
            task.completed_length = _human_size(done) if done else ""
            task.download_speed = f"{_human_size(speed)}/s" if speed else ""
            if total:
                task.progress = round(done * 100 / total, 2)
            elif status == "complete":
                task.progress = 100.0
            files_raw = st.get("files") or []
            file_paths: list[str] = []
            for f in files_raw:
                if isinstance(f, dict) and f.get("path"):
                    file_paths.append(str(f["path"]))
            if file_paths:
                task.files = file_paths
                task.saved_path = str(Path(file_paths[0]).parent)
            if st.get("errorMessage"):
                task.error = str(st.get("errorMessage"))
            task.updated_at = _now()

            if status == "complete":
                paths = [Path(p) for p in file_paths if p and Path(p).exists()]
                if not paths:
                    paths = [p for p in self._scan_incoming_for_task(task)]
                task.saved_path = str(paths[0].parent) if paths else str(self.cfg.incoming_dir())
                self._organize_if_needed(task, paths)
                task.status = "complete"
            elif status == "error":
                task.status = "error"
                if not task.error:
                    task.error = "下载失败"

    def _scan_incoming_for_task(self, task: DownloadTask) -> list[Path]:
        """尽量只返回与当前任务相关的文件，避免并发任务误整理。"""
        root = self.cfg.incoming_dir()
        if not root.exists():
            return []
        all_files: list[Path] = []
        for p in root.rglob("*"):
            if p.is_file() and not p.name.endswith(".aria2"):
                all_files.append(p)
        all_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        keywords = [w for w in (task.quality, str(task.year) if task.year else "", task.title) if w]
        matched: list[Path] = []
        for p in all_files:
            name = p.name.lower()
            if any(str(k).lower() in name for k in keywords if k):
                matched.append(p)
        return matched or all_files[:5]

    def _organize_if_needed(self, task: DownloadTask, paths: list[Path]) -> None:
        opts = task.organize_opts or {}
        enabled = bool(opts.get("enabled", self.cfg.organize.enabled))
        media_ext = {
            ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts",
            ".webm", ".rmvb", ".mpg", ".mpeg", ".iso",
        }
        if not enabled or not paths:
            return
        primary = None
        for p in paths:
            if p.is_file() and p.suffix.lower() in media_ext:
                primary = p
                break
        if primary is None:
            files = [p for p in paths if p.is_file()]
            if not files:
                return
            if len(files) == 1:
                primary = files[0]
            else:
                primary = max(files, key=lambda p: p.stat().st_size if p.exists() else 0)

        try:
            final = self.organizer.organize_file(
                primary,
                title=task.title,
                year=task.year,
                quality=task.quality,
                options=opts if opts else None,
            )
            task.organized_path = str(final)
            task.files = [str(final)]
        except Exception as exc:  # noqa: BLE001
            task.error = f"下载完成，但自动整理失败：{exc}"
            task.organized_path = ""

    async def aria2_status(self) -> dict[str, Any]:
        ok = await self.aria2.is_available()
        info: dict[str, Any] = {"available": ok, "rpc_url": self.cfg.downloader.aria2.rpc_url}
        if ok:
            try:
                ver = await self.aria2.call("aria2.getVersion")
                info["version"] = ver.get("version") if isinstance(ver, dict) else str(ver)
            except Exception:  # noqa: BLE001
                pass
        return info
