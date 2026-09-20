"""检索源共用的小工具。"""
from __future__ import annotations

from urllib.parse import quote


def human_size(value: object) -> str:
    """字节数 → '12.34 GB'（失败返回空串）。"""
    try:
        n = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024
        i += 1
    return f"{n:.2f} {units[i]}"


def classify_url(url: str) -> str:
    low = (url or "").strip().lower()
    if low.startswith("magnet:"):
        return "magnet"
    if ".torrent" in low:
        return "torrent"
    if low.startswith("http://") or low.startswith("https://"):
        return "http"
    return "unknown"


def build_magnet(info_hash: str, name: str = "", trackers: list[str] | None = None) -> str:
    h = (info_hash or "").strip()
    if not h:
        return ""
    url = f"magnet:?xt=urn:btih:{h}"
    if name:
        url += f"&dn={quote(name)}"
    for tr in trackers or [
        "udp://tracker.opentrackr.org:1337/announce",
        "udp://open.tracker.cl:1337/announce",
        "udp://tracker.openbittorrent.com:6969/announce",
        "udp://exodus.desync.com:6969/announce",
    ]:
        url += f"&tr={quote(tr, safe='')}"
    return url


def int_or_none(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
