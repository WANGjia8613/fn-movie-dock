from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..config import OrganizeConfig


_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WS = re.compile(r"\s+")


def sanitize_name(name: str, fallback: str = "未知影片") -> str:
    name = (name or "").strip()
    name = _INVALID.sub("", name)
    name = _WS.sub(" ", name).strip(" .")
    return name or fallback


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
    text = re.sub(
        r"\b(2160p|1080p|720p|480p|4k|uhd|bluray|blu-ray|web-?dl|webrip|hdtv|x264|x265|hevc|hdr|remux)\b",
        "",
        text,
        flags=re.I,
    )
    text = _WS.sub(" ", text).strip(" -_·.")
    return sanitize_name(text), year


def apply_template(
    template: str,
    *,
    title: str,
    year: int | None,
    quality: str = "",
    ext: str = "",
    unknown_year: str = "未知年份",
) -> str:
    mapping = {
        "title": sanitize_name(title),
        "year": str(year) if year else unknown_year,
        "quality": sanitize_name(quality or "未知", "未知"),
        "resolution": sanitize_name(quality or "未知", "未知"),
        "ext": (ext or "").lstrip("."),
    }
    out = template or ""
    for key, value in mapping.items():
        out = out.replace("{" + key + "}", value)
    # 文件名模板可能含扩展名，sanitize 不应去掉后缀里的点
    if ext:
        suffix = ext if ext.startswith(".") else f".{ext}"
        if out.lower().endswith(suffix.lower()):
            stem = out[: -len(suffix)]
            return f"{sanitize_name(stem, '未命名')}{suffix}"
    return sanitize_name(out)


class Organizer:
    def __init__(self, cfg: OrganizeConfig, download_root: Path):
        self.cfg = cfg
        self.download_root = download_root

    def build_paths(
        self,
        title: str,
        year: int | None,
        quality: str = "",
        source_path: Path | None = None,
    ) -> tuple[Path, Path]:
        folder = apply_template(
            self.cfg.movie_dir_template,
            title=title,
            year=year,
            quality=quality,
            unknown_year=self.cfg.unknown_year,
        )
        dest_dir = self.download_root / "movies" / folder
        ext = source_path.suffix if source_path else ""
        filename = apply_template(
            self.cfg.file_name_template,
            title=title,
            year=year,
            quality=quality,
            ext=ext,
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
        unknown_year = opts.get("unknown_year") or self.cfg.unknown_year

        folder = apply_template(
            movie_dir_template,
            title=title,
            year=year,
            quality=quality,
            unknown_year=unknown_year,
        )
        dest_dir = self.download_root / "movies" / folder
        dest_dir.mkdir(parents=True, exist_ok=True)

        ext = src.suffix
        filename = apply_template(
            file_name_template,
            title=title,
            year=year,
            quality=quality,
            ext=ext,
            unknown_year=unknown_year,
        )
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
