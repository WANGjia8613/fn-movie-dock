from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from ..config import AppConfig
from ..llm import LLMClient
from ..models import TaskOut
from ..organizer import Organizer, parse_episode, parse_title_year
from ..ranking import detect_tags
from ..subtitle import SubtitleService
from .http_fallback import download_http_to

MEDIA_EXTS = {
    ".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m2ts",
    ".webm", ".rmvb", ".mpg", ".mpeg", ".iso",
}


def _title_from_url(url: str) -> tuple[str, Optional[int]]:
    """从链接推断片名/年份：磁力优先看 dn= 参数，其余交给 parse_title_year。"""
    from urllib.parse import parse_qs, unquote

    raw = (url or "").strip()
    if raw.lower().startswith("magnet:") and "?" in raw:
        try:
            qs = parse_qs(raw.split("?", 1)[1])
        except ValueError:
            qs = {}
        dn = (qs.get("dn") or [""])[0]
        if dn:
            name = unquote(dn).replace("+", " ")
            title, year = parse_title_year(name)
            if title:
                return title, year
    return parse_title_year(raw)


def _friendly_aria2_error(raw: str) -> str:
    """把 aria2 的英文错误改成能看懂的中文提示（保留原文便于排查）。"""
    text = (raw or "").strip()
    low = text.lower()
    mapping = [
        ("already registered", "该资源已在 aria2 下载列表中（可能正在下载），无需重复添加"),
        ("no uri", "链接为空或无法识别"),
        ("not found", "aria2 中找不到该任务"),
        ("timeout", "连接超时（资源站/做种者不可达）"),
        ("unrecognized", "链接格式无法识别"),
        ("unfinished", "仍有未完成的分片，下载已中断"),
        ("max file not found", "种子内找不到可下载的文件"),
    ]
    for key, zh in mapping:
        if key in low:
            return f"{zh}（aria2: {text[:120]}）"
    return text


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
    episode: str = ""
    tags: list[str] = field(default_factory=list)
    subtitle_status: str = ""
    subtitle_path: str = ""
    subtitle_note: str = ""
    error: str = ""
    created_at: str = ""
    updated_at: str = ""
    organize_opts: dict[str, Any] = field(default_factory=dict)
    engine: str = "aria2"
    http_dest: str = ""
    fetch_subtitle: bool = True
    incoming_dir: str = ""

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
            episode=self.episode,
            tags=list(self.tags),
            subtitle_status=self.subtitle_status,
            subtitle_path=self.subtitle_path,
            subtitle_note=self.subtitle_note,
            engine=self.engine,
            error=self.error,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    def to_state(self) -> dict[str, Any]:
        return asdict(self)


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
            # 磁力链接：元数据下载会派生真正的下载任务
            "followedBy",
            "following",
            "belongsTo",
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
        self.organizer = Organizer(cfg.organize, cfg.download_root(), cfg.library_root())
        self.subtitle = SubtitleService(cfg.subtitle, llm=LLMClient(cfg.llm), proxy=cfg.network.proxy)
        self._poller: asyncio.Task | None = None
        self._background_tasks: set[asyncio.Task] = set()
        self._state_path = cfg.state_dir() / "tasks.json"
        self._dirty = False
        self._load_state()

    # ---------- 状态持久化 ----------
    @property
    def state_path(self) -> Path:
        return self._state_path

    def _load_state(self) -> None:
        try:
            if not self._state_path.exists():
                return
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return
        entries = raw.get("tasks") if isinstance(raw, dict) else raw
        if not isinstance(entries, list):
            return
        valid = {f.name for f in DownloadTask.__dataclass_fields__.values()}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            data = {k: v for k, v in entry.items() if k in valid}
            if not data.get("task_id"):
                continue
            try:
                task = DownloadTask(**data)
            except TypeError:
                continue
            if task.status not in ("complete", "error"):
                task.status = "interrupted"
                task.error = task.error or "应用重启，下载会话已丢失，请重新添加任务"
            self.tasks[task.task_id] = task

    def _persist(self, force: bool = False) -> None:
        if not force and not self._dirty:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"saved_at": _now(), "tasks": [t.to_state() for t in self.tasks.values()]}
            tmp = self._state_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self._state_path)
            self._dirty = False
        except OSError:
            pass

    def apply_config(self, cfg: AppConfig) -> None:
        """配置热更新：同步下载根目录、整理规则、aria2 RPC、字幕设置。"""
        self.cfg = cfg
        self.organizer = Organizer(cfg.organize, cfg.download_root(), cfg.library_root())
        self.subtitle = SubtitleService(cfg.subtitle, llm=LLMClient(cfg.llm), proxy=cfg.network.proxy)
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
        self._persist(force=True)

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

    # ---------- 创建任务 ----------
    def task_dir(self, task: DownloadTask) -> Path:
        if not self.cfg.downloader.per_task_dir:
            return self.cfg.incoming_dir()
        if task.incoming_dir:
            return Path(task.incoming_dir)
        path = self.cfg.incoming_dir() / task.task_id
        task.incoming_dir = str(path)
        return path

    async def start_download(
        self,
        url: str,
        title: str = "",
        year: int | None = None,
        quality: str = "",
        organize: dict[str, Any] | None = None,
        fetch_subtitle: bool | None = None,
    ) -> DownloadTask:
        url = (url or "").strip()
        if not title:
            parsed_title, parsed_year = _title_from_url(url)
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
            fetch_subtitle=(self.cfg.subtitle.enabled if fetch_subtitle is None else bool(fetch_subtitle)),
        )
        task.tags = detect_tags(f"{title} {quality}")
        season, episode = parse_episode(f"{title} {url}")
        if episode is not None:
            from ..organizer import episode_label

            task.episode = episode_label(season, episode)
        self.tasks[task.task_id] = task
        self._dirty = True
        self._persist()
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
            aria2_ok = False
            if kind in ("magnet", "torrent", "http"):
                aria2_ok = await self.aria2.is_available()

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
                self._dirty = True
                self._persist()
        except Exception as exc:  # noqa: BLE001
            task.status = "error"
            task.error = _friendly_aria2_error(str(exc))
            task.updated_at = _now()
            self._dirty = True
            self._persist()

    def _aria2_options(self, task: DownloadTask) -> dict[str, Any]:
        target = self.task_dir(task)
        target.mkdir(parents=True, exist_ok=True)
        options: dict[str, Any] = {
            "dir": str(target),
            # 不做种（防止 NAS 变 PCDN 节点）
            "seed-time": "0",
            "seed-ratio": "0.0",
            "bt-max-peers": "64",
            "max-connection-per-server": "8",
            "split": "8",
            "continue": "true",
            "auto-file-renaming": "true",
            "allow-overwrite": "false",
            "file-allocation": "none",
            "follow-torrent": "true",
            "bt-save-metadata": "true",
            "enable-dht": "true",
            "bt-enable-lpd": "true",
        }
        trackers = (self.cfg.downloader.bt_trackers or "").strip()
        if trackers:
            options["bt-tracker"] = trackers
        options.update({str(k): str(v) for k, v in (self.cfg.downloader.extra_options or {}).items()})
        return options

    async def _start_aria2(self, task: DownloadTask) -> None:
        options = self._aria2_options(task)
        gid = await self.aria2.add_uri([task.url], options)
        task.gid = gid
        task.status = "active"
        task.updated_at = _now()
        self._dirty = True

    async def _start_http(self, task: DownloadTask) -> None:
        target = self.task_dir(task)
        target.mkdir(parents=True, exist_ok=True)
        path = await download_http_to(
            task.url,
            target,
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
        await self._finish_task(task, [path] if path.exists() else [])
        self._dirty = True
        self._persist()

    def _on_http_progress(self, task: DownloadTask, done: int, total: int, speed: float) -> None:
        task.completed_length = _human_size(done)
        task.total_length = _human_size(total) if total else ""
        task.progress = round(done * 100 / total, 2) if total else 0.0
        task.download_speed = _human_size(speed) + "/s" if speed else ""
        task.status = "active"
        task.updated_at = _now()

    async def _poll_loop(self) -> None:
        tick = 0
        while True:
            try:
                await self._poll_once()
            except Exception:  # noqa: BLE001
                pass
            tick += 1
            self._persist(force=(tick % 5 == 0))
            await asyncio.sleep(2)

    async def _poll_once(self) -> None:
        pending = [
            t
            for t in self.tasks.values()
            if t.engine == "aria2"
            and t.gid
            and t.status in ("queued", "active", "paused", "waiting", "interrupted")
        ]
        if not pending:
            return
        for task in pending:
            try:
                st = await self.aria2.tell_status(task.gid)
            except Exception as exc:  # noqa: BLE001
                task.error = str(exc)
                if task.status == "interrupted":
                    task.error = "下载会话已丢失（应用重启后无法恢复），请重新添加任务"
                continue
            if not st:
                continue

            # 磁力链接：首次 addUri 拿到的是「元数据下载」的 GID，
            # 元数据完成时 aria2 会派生子任务（followedBy）——那才是真正的下载。
            followed = st.get("followedBy")
            if isinstance(followed, list) and followed:
                new_gid = str(followed[0] or "")
                if new_gid and new_gid != task.gid:
                    task.gid = new_gid
                    task.status = "active"
                    task.updated_at = _now()
                    self._dirty = True
                    try:
                        st = await self.aria2.tell_status(new_gid) or st
                    except Exception:  # noqa: BLE001
                        continue

            status = str(st.get("status") or "")
            if status:
                task.status = status
                task.error = "" if status != "error" else task.error
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
                task.error = _friendly_aria2_error(str(st.get("errorMessage")))
            task.updated_at = _now()
            self._dirty = True

            if status == "complete":
                paths = self._collect_output_files(task, file_paths)
                primary = self._pick_primary(paths)
                # 磁力元数据刚完成时文件还是 0 字节/占位，别急着整理
                if primary is not None and not self._file_complete(primary, files_raw):
                    task.status = "active"
                    task.progress = min(task.progress, 99.9)
                    continue
                task.saved_path = str(paths[0].parent) if paths else self.task_dir(task)
                task.status = "complete"
                await self._finish_task(task, paths)
            elif status == "error":
                task.status = "error"
                if not task.error:
                    task.error = "下载失败"

    def _collect_output_files(self, task: DownloadTask, file_paths: list[str]) -> list[Path]:
        """优先用 aria2 报的准确文件列表；仅在缺失时回退到任务自己的目录扫描。

        会排除 .aria2 临时文件与 .torrent 元数据文件。
        """
        candidates: list[Path] = []
        for raw in file_paths:
            p = Path(raw)
            if p.suffix.lower() == ".torrent" or p.name.endswith(".aria2"):
                continue
            if p.exists() and p.is_file():
                candidates.append(p)
        if not candidates:
            root = self.task_dir(task)
            if root.exists():
                candidates = [
                    p
                    for p in root.rglob("*")
                    if p.is_file()
                    and p.suffix.lower() != ".torrent"
                    and not p.name.endswith(".aria2")
                ]
        return candidates

    @staticmethod
    def _pick_primary(paths: list[Path]) -> Path | None:
        media = [p for p in paths if p.suffix.lower() in MEDIA_EXTS]
        if media:
            return max(media, key=DownloadManager._safe_size)
        files = [p for p in paths if p.is_file()]
        return max(files, key=DownloadManager._safe_size) if files else None

    @staticmethod
    def _file_complete(path: Path, files_raw: list[Any]) -> bool:
        """对照 aria2 报的单文件长度，确认文件真的写完了（防磁力占位文件被整理）。"""
        try:
            actual = path.stat().st_size
        except OSError:
            return False
        expected = None
        for item in files_raw:
            if isinstance(item, dict) and str(item.get("path") or "") == str(path):
                try:
                    expected = int(item.get("length") or 0)
                except (TypeError, ValueError):
                    expected = None
                break
        if expected:
            return actual >= expected * 0.999
        return actual > 0

    async def _finish_task(self, task: DownloadTask, paths: list[Path]) -> None:
        """下载完成后的收尾：整理 + 字幕。任一步失败也不把任务判成失败。"""
        video: Path | None = None
        try:
            video = await self._organize_if_needed(task, paths)
        except Exception as exc:  # noqa: BLE001
            task.error = f"自动整理异常：{exc}"
        try:
            await self._subtitle_if_needed(task, video)
        except Exception as exc:  # noqa: BLE001
            task.subtitle_status = "failed"
            task.subtitle_note = f"字幕匹配异常：{exc}"
        task.updated_at = _now()
        self._dirty = True
        self._persist(force=True)

    async def _organize_if_needed(self, task: DownloadTask, paths: list[Path]) -> Path | None:
        opts = dict(task.organize_opts or {})
        enabled = bool(opts.get("enabled", self.cfg.organize.enabled))
        primary = self._pick_primary(paths)
        if primary is None:
            return None
        task.saved_path = str(primary.parent)

        if not enabled:
            return primary
        try:
            # shutil.move/copy 是阻塞 IO，放到线程池避免卡住事件循环
            final = await asyncio.to_thread(
                self.organizer.organize_file,
                primary,
                title=task.title,
                year=task.year,
                quality=task.quality,
                options=opts if opts else None,
            )
            task.organized_path = str(final)
            task.files = [str(final)]
            return final
        except Exception as exc:  # noqa: BLE001
            task.error = f"下载完成，但自动整理失败：{exc}"
            task.organized_path = ""
            return primary

    async def _subtitle_if_needed(self, task: DownloadTask, video: Path | None) -> None:
        if not task.fetch_subtitle:
            task.subtitle_status = "skipped"
            return
        if video is None or not video.exists():
            task.subtitle_status = "failed"
            task.subtitle_note = "找不到视频文件，跳过字幕匹配"
            return
        if video.suffix.lower() not in MEDIA_EXTS:
            task.subtitle_status = "skipped"
            task.subtitle_note = "非视频文件，跳过字幕匹配"
            return
        task.subtitle_status = "searching"
        self._dirty = True
        result = await self.subtitle.fetch_for_video(
            video, title=task.title, year=task.year, quality=task.quality
        )
        if result.ok:
            task.subtitle_status = "done"
            task.subtitle_path = result.files[0] if result.files else ""
            task.subtitle_note = result.message
        else:
            task.subtitle_status = "failed"
            task.subtitle_path = ""
            task.subtitle_note = result.message

    async def retry_subtitle(self, task: DownloadTask) -> TaskOut:
        """手动重试字幕匹配（换关键词后再试）。"""
        target = Path(task.organized_path or task.saved_path or "")
        if target and target.is_file():
            video = target
        else:
            video = None
            for raw in task.files:
                p = Path(raw)
                if p.is_file() and p.suffix.lower() in MEDIA_EXTS:
                    video = p
                    break
        if video is None:
            task.subtitle_status = "failed"
            task.subtitle_note = "找不到视频文件，无法匹配字幕"
            return task.to_out()
        task.fetch_subtitle = True
        await self._subtitle_if_needed(task, video)
        task.updated_at = _now()
        self._persist(force=True)
        return task.to_out()

    @staticmethod
    def _safe_size(p: Path) -> int:
        try:
            return p.stat().st_size
        except OSError:
            return 0

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
