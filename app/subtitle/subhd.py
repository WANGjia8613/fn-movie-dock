"""SubHD（subhd.tv）字幕客户端。

流程（必须保持同一会话，prepare 会下发 token cookie）：
  搜索影片 → 列字幕条目 → prepare-download → 访问临时页 → down API → 拿真实下载 URL
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
BASE = "https://subhd.tv"


class SubHDError(RuntimeError):
    pass


@dataclass
class SubHDEntry:
    sid: str
    title: str
    fmt: str = ""
    lang: str = ""
    movie: str = ""
    year: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class SubHDMovie:
    id: str
    title: str = ""
    year: str = ""
    type: str = ""


_SID_RE = re.compile(r'href="/a/([A-Za-z0-9]+)"[^>]*>(.*?)</a>', re.S)
_FMT_RE = re.compile(r'>(ASS|SRT|SUP|SUB|SSA)<', re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub("", html or "")).strip()


class SubHDClient:
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    # ---------- 内部 ----------
    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=self.timeout,
            follow_redirects=True,
            headers={"User-Agent": UA, "Referer": BASE + "/"},
        )

    # ---------- 搜索 ----------
    def search_movies(self, client: httpx.Client, keyword: str) -> list[SubHDMovie]:
        """搜索影片，返回多个候选（SubHD 对英文名/别名匹配很差，需多候选兜底）。"""
        from urllib.parse import quote

        url = f"{BASE}/searchD/{quote(keyword)}"
        try:
            resp = client.get(url)
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise SubHDError(f"搜索失败：{exc}") from exc
        out: list[SubHDMovie] = []
        for it in (data or {}).get("items") or []:
            if not isinstance(it, dict):
                continue
            mid = str(it.get("id") or "")
            if not mid:
                continue
            out.append(SubHDMovie(id=mid, title=str(it.get("title") or ""),
                                  year=str(it.get("year") or ""), type=str(it.get("type") or "")))
        return out

    def search_movie(self, client: httpx.Client, keyword: str) -> str | None:
        movies = self.search_movies(client, keyword)
        return movies[0].id if movies else None

    def _rank_movies(self, movies: list[SubHDMovie], year: int | None) -> list[SubHDMovie]:
        """电影优先、年份匹配优先（否则「电焊工波力」这类同系列短片会抢在最前面）。"""
        def key(m: SubHDMovie):
            type_rank = 0 if m.type.lower() == "movie" else 1
            year_rank = 0 if (year and m.year and str(year) == m.year) else (1 if year else 0)
            return (year_rank, type_rank)

        return sorted(movies, key=key)

    def list_subtitles(self, client: httpx.Client, movie_id: str, movie_title: str = "",
                       movie_year: str = "") -> list[SubHDEntry]:
        try:
            resp = client.get(f"{BASE}/d/{movie_id}")
        except Exception as exc:  # noqa: BLE001
            raise SubHDError(f"获取字幕列表失败：{exc}") from exc
        html = resp.text
        entries: list[SubHDEntry] = []
        for m in _SID_RE.finditer(html):
            sid = m.group(1)
            title = _clean(m.group(2))
            if not title:
                continue
            if any(e.sid == sid for e in entries):
                continue
            tail = _clean(html[m.end(): m.end() + 900])
            fmt_m = _FMT_RE.search(html[m.end(): m.end() + 900])
            langs = [w for w in ("双语", "简体", "繁体", "英语", "国语", "粤语") if w in tail]
            entries.append(SubHDEntry(
                sid=sid,
                title=title[:200],
                fmt=(fmt_m.group(1).upper() if fmt_m else ""),
                lang=" ".join(langs),
                movie=movie_title,
                year=movie_year,
            ))
        return entries

    # ---------- 下载 ----------
    def prepare(self, client: httpx.Client, sid: str) -> str:
        r = client.post(f"{BASE}/api/sub/prepare-download", json={"sid": sid},
                        headers={"Referer": f"{BASE}/a/{sid}"})
        try:
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            raise SubHDError(f"prepare 返回异常：{r.text[:120]}") from exc
        if not data.get("success"):
            raise SubHDError(f"prepare 失败：{str(data)[:160]}")
        url = str(data.get("url") or "")
        if not url:
            raise SubHDError("prepare 未返回临时下载页")
        # 必须访问临时页，拿到页面 token
        client.get(url if url.startswith("http") else BASE + url)
        return url

    def resolve_download_url(self, client: httpx.Client, sid: str) -> str:
        r = client.post(f"{BASE}/api/sub/down", json={"sid": sid},
                        headers={"Referer": f"{BASE}/down/{sid}"})
        try:
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            raise SubHDError(f"down 返回异常：{r.text[:120]}") from exc
        if not data.get("success") or not data.get("pass"):
            raise SubHDError(f"下载被拒绝：{str(data)[:160]}")
        url = str(data.get("url") or "")
        if not url:
            raise SubHDError("down 未返回下载地址")
        return url

    def download_archive(self, client: httpx.Client, url: str, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        try:
            with client.stream("GET", url, headers={"Referer": BASE + "/"}) as resp:
                resp.raise_for_status()
                ctype = resp.headers.get("content-type", "")
                name = url.rsplit("/", 1)[-1].split("?")[0] or "subtitle.bin"
                if "zip" in ctype:
                    name = name if name.lower().endswith(".zip") else f"{name}.zip"
                path = dest_dir / name
                with path.open("wb") as f:
                    for chunk in resp.iter_bytes(64 * 1024):
                        f.write(chunk)
        except httpx.HTTPError as exc:
            raise SubHDError(f"下载字幕包失败：{exc}") from exc
        if path.stat().st_size < 128:
            raise SubHDError("下载到的文件过小，可能链接已过期")
        return path

    # ---------- 组合流程 ----------
    def fetch(self, keyword: str, dest_dir: Path, sid: str | None = None) -> Path:
        """按关键词（或指定 sid）下载字幕压缩包，返回归档文件路径。"""
        with self._client() as client:
            client.get(BASE + "/")
            target = sid
            if not target:
                movie_id = self.search_movie(client, keyword)
                if not movie_id:
                    raise SubHDError(f"未找到影片：{keyword}")
                entries = self.list_subtitles(client, movie_id)
                if not entries:
                    raise SubHDError(f"影片「{keyword}」暂无字幕条目")
                target = entries[0].sid
            self.prepare(client, target)
            url = self.resolve_download_url(client, target)
            return self.download_archive(client, url, dest_dir)

    def list_by_keyword(self, keyword: str, year: int | None = None, max_movies: int = 2) -> list[SubHDEntry]:
        """按关键词取字幕条目；会把搜索到的前几部影片合并去重。"""
        try:
            with self._client() as client:
                client.get(BASE + "/")
                movies = self.search_movies(client, keyword)
                if not movies:
                    return []
                entries: list[SubHDEntry] = []
                seen: set[str] = set()
                for movie in self._rank_movies(movies, year)[:max_movies]:
                    for entry in self.list_subtitles(client, movie.id, movie.title, movie.year):
                        if entry.sid in seen:
                            continue
                        seen.add(entry.sid)
                        entries.append(entry)
                return entries
        except SubHDError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise SubHDError(f"访问 SubHD 失败：{exc}") from exc

    def fetch_entry(self, sid: str, dest_dir: Path) -> Path:
        return self.fetch(keyword="", dest_dir=dest_dir, sid=sid)
