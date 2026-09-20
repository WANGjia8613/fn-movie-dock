from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..config import OrganizeConfig


_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WS = re.compile(r"\s+")
# 压制/画质/音轨类标记：出现位置之后的内容基本是发布信息，不是片名
_RELEASE_TOKEN_PATTERN = (
    r"(?:2160p|1080p|720p|480p|4k|uhd|bluray|blu-?ray|bdremux|remux|web-?dl|webdl|webrip|hdtv|hdrip|"
    r"brrip|dvdrip|x264|x265|h264|h265|hevc|avc|av1|10bit|8bit|aac|ac3|ddp|dd5|dts(?:-hd)?|truehd|"
    r"atmos|hdr10\+?|hdr|dovi|repack|proper|internal|multi|dual|remastered|imax|extended)"
)

# 剧集集号识别：S01E02 / s1e2 / 1x02 / 第2集 / EP02 / E02
_EPISODE_PATTERNS = [
    re.compile(r"[Ss](\d{1,2})[\s._-]?[Ee][Pp]?(\d{1,3})"),
    re.compile(r"(?<![0-9])(\d{1,2})[xX](\d{1,3})(?![0-9])"),
    re.compile(r"第\s*(\d{1,3})\s*[集话話]"),
    re.compile(r"(?<![A-Za-z0-9])[Ee][Pp]?(\d{1,3})(?![0-9])"),
]


def sanitize_name(name: str, fallback: str = "未知影片") -> str:
    name = (name or "").strip()
    name = _INVALID.sub("", name)
    name = _WS.sub(" ", name).strip(" .")
    return name or fallback


def sanitize_path(name: str, fallback: str = "未知影片") -> str:
    """模板里可能含 "/"（如 {title} ({year})/Season {season}），逐段清理保留层级。"""
    raw = (name or "").replace("\\", "/")
    if "/" not in raw:
        return sanitize_name(raw, fallback)
    segs = [sanitize_name(seg, fallback) for seg in raw.split("/") if seg.strip()]
    return "/".join(segs) or fallback


def parse_title_year(query: str) -> tuple[str, Optional[int]]:
    text = (query or "").strip()
    year = None
    # 优先匹配括号内年份，降低片名自带数字的误伤
    m = re.search(r"[(\[]((?:19|20)\d{2})[)\]]", text)
    if not m:
        m = re.search(r"(?<![0-9])((?:19|20)\d{2})(?![0-9])", text)
    if m:
        year = int(m.group(1))
        text = (text[: m.start()] + text[m.end() :]).strip()
    # 发布名常用点号分词：Spider-Man.No.Way.Home -> Spider-Man No Way Home
    text = re.sub(r"(?<=[A-Za-z0-9])\.(?=[A-Za-z0-9])", " ", text)
    # 遇到第一个压制/画质标记就截断 —— 比逐个删除更能得到干净的片名
    # （例：WALL-E (2008) 1080p BrRip x264 - 1.20GB - YIFY → WALL-E）
    hit = re.search(r"\b" + _RELEASE_TOKEN_PATTERN + r"\b", text, re.I)
    if hit and hit.start() > 0:
        text = text[: hit.start()]
    # 去掉 “1.20GB” 这类体积标记（磁力 dn= 里很常见）
    text = re.sub(r"\d+(?:\.\d+)?\s?(?:GB|MB|KB)\b", "", text, flags=re.I)
    # 只收拾“分隔用”的短横（两侧带空格 / 末尾），别动 WALL-E、Spider-Man 这类词内连字符
    text = re.sub(r"(?:\s+-\s*)+$", "", text)
    text = re.sub(r"(?:\s+-\s*)+", " ", text)
    text = _WS.sub(" ", text).strip(" -_·.")
    return sanitize_name(text), year


def parse_episode(text: str) -> tuple[Optional[int], Optional[int]]:
    """从文件名/标题里解析 (季, 集)。识别不到返回 (None, None)。"""
    raw = (text or "").strip()
    if not raw:
        return None, None
    for idx, pattern in enumerate(_EPISODE_PATTERNS):
        m = pattern.search(raw)
        if not m:
            continue
        try:
            if pattern.groups == 2:
                season, episode = int(m.group(1)), int(m.group(2))
            else:
                # 只有集号：第2集 / E02 → 季未知按 1
                season, episode = 1, int(m.group(1))
        except (TypeError, ValueError):
            continue
        if idx == 2:  # 「第N集」形式
            season = 1 if season in (0, 1) else season
        return season, episode
    return None, None


def episode_label(season: int | None, episode: int | None) -> str:
    if season is None and episode is None:
        return ""
    s = season or 1
    e = episode if episode is not None else 0
    return f"S{s:02d}E{e:02d}"


def apply_template(
    template: str,
    *,
    title: str,
    year: int | None,
    quality: str = "",
    ext: str = "",
    season: int | None = None,
    episode: int | None = None,
    unknown_year: str = "未知年份",
) -> str:
    mapping = {
        "title": sanitize_name(title),        "year": str(year) if year else unknown_year,
        "quality": sanitize_name(quality or "未知", "未知"),
        "resolution": sanitize_name(quality or "未知", "未知"),
        "season": f"{season:02d}" if season else "",
        "episode": f"{episode:02d}" if episode is not None else "",
        "season_raw": str(season) if season else "",
        "episode_raw": str(episode) if episode is not None else "",
        "ext": (ext or "").lstrip("."),
    }
    out = template or ""
    for key, value in mapping.items():
        out = out.replace("{" + key + "}", value)
    out = out.replace("S/E", "").replace("SE", "")
    # 文件名模板可能含扩展名，sanitize 不应去掉后缀里的点
    if ext:
        suffix = ext if ext.startswith(".") else f".{ext}"
        if out.lower().endswith(suffix.lower()):
            stem = out[: -len(suffix)]
            return f"{sanitize_path(stem, '未命名')}{suffix}"
    return sanitize_path(out)


class Organizer:
    def __init__(self, cfg: OrganizeConfig, download_root: Path, library_root: Path | None = None):
        self.cfg = cfg
        self.download_root = Path(download_root)
        self._library_root = Path(library_root) if library_root else None

    def library_root(self, override: str | None = None) -> Path:
        raw = (override or "").strip() if override else ""
        if raw:
            return Path(raw).expanduser()
        if self._library_root is not None:
            return self._library_root
        raw = (self.cfg.library_root or "").strip()
        if raw:
            return Path(raw).expanduser()
        return self.download_root / (self.cfg.movies_subdir or "movies")

    def build_paths(
        self,
        title: str,
        year: int | None,
        quality: str = "",
        source_path: Path | None = None,
        *,
        episode_text: str = "",
        library_root: str | None = None,
        ext: str | None = None,
    ) -> tuple[Path, Path]:
        season, episode = parse_episode(episode_text or (source_path.name if source_path else ""))
        if ext is None:
            ext = source_path.suffix if source_path else ""
        root = self.library_root(library_root)
        if season is not None or episode is not None:
            folder = apply_template(
                self.cfg.series_dir_template or self.cfg.movie_dir_template,
                title=title, year=year, quality=quality, season=season, episode=episode,
                unknown_year=self.cfg.unknown_year,
            )
            dest_dir = root / folder
            filename = apply_template(
                self.cfg.series_file_template or self.cfg.file_name_template,
                title=title, year=year, quality=quality, ext=ext, season=season, episode=episode,
                unknown_year=self.cfg.unknown_year,
            )
        else:
            folder = apply_template(
                self.cfg.movie_dir_template,
                title=title, year=year, quality=quality,
                unknown_year=self.cfg.unknown_year,
            )
            dest_dir = root / folder
            filename = apply_template(
                self.cfg.file_name_template,
                title=title, year=year, quality=quality, ext=ext,
                unknown_year=self.cfg.unknown_year,
            )
        if ext and not filename.lower().endswith(ext.lower()):
            filename = f"{filename}{ext}"
        return dest_dir, dest_dir / filename

    def organize_file(
        self,
        src: Path,
        title: str,
        year: int | None,
        quality: str = "",
        options: dict | None = None,
    ) -> Path:
        src = Path(src)
        if not src.exists() or not src.is_file():
            raise FileNotFoundError(f"待整理文件不存在：{src}")

        opts = options or {}
        enabled = bool(opts.get("enabled", self.cfg.enabled))
        if not enabled:
            return src

        mode = opts.get("mode") or self.cfg.mode
        if mode not in ("move", "copy", "hardlink"):
            mode = self.cfg.mode
        movie_dir_template = opts.get("movie_dir_template") or self.cfg.movie_dir_template
        file_name_template = opts.get("file_name_template") or self.cfg.file_name_template
        series_dir_template = opts.get("series_dir_template") or self.cfg.series_dir_template
        series_file_template = opts.get("series_file_template") or self.cfg.series_file_template
        unknown_year = opts.get("unknown_year") or self.cfg.unknown_year
        library_root = opts.get("library_root")

        season, episode = parse_episode(f"{title} {src.name}")
        root = self.library_root(library_root)
        if season is not None or episode is not None:
            folder = apply_template(
                series_dir_template, title=title, year=year, quality=quality,
                season=season, episode=episode, unknown_year=unknown_year,
            )
            filename = apply_template(
                series_file_template, title=title, year=year, quality=quality,
                ext=src.suffix, season=season, episode=episode, unknown_year=unknown_year,
            )
        else:
            folder = apply_template(
                movie_dir_template, title=title, year=year, quality=quality,
                unknown_year=unknown_year,
            )
            filename = apply_template(
                file_name_template, title=title, year=year, quality=quality,
                ext=src.suffix, unknown_year=unknown_year,
            )
        dest_dir = root / folder
        dest_dir.mkdir(parents=True, exist_ok=True)

        ext = src.suffix
        if ext and not filename.lower().endswith(ext.lower()):
            filename = f"{filename}{ext}"

        dest = dest_dir / filename
        src_resolved = src.resolve()
        if dest.exists():
            try:
                if dest.resolve() == src_resolved:
                    return dest
            except OSError:
                pass
            stem = dest.stem
            i = 1
            while dest.exists():
                dest = dest_dir / f"{stem}.{i}{ext}"
                i += 1

        dest.parent.mkdir(parents=True, exist_ok=True)

        if mode == "copy":
            import shutil

            shutil.copy2(src, dest)
            return dest
        if mode == "hardlink":
            try:
                dest.hardlink_to(src)
                return dest
            except OSError:
                import shutil

                shutil.copy2(src, dest)
                return dest
        import shutil

        shutil.move(str(src), str(dest))
        return dest
