from __future__ import annotations

import re

from .models import SourceItem

# 画质 / 特性标签识别：用于候选打分与前端展示
_TAGS: list[tuple[str, str]] = [
    (r"(?<![a-z0-9])(dolby[\s._-]?vision|dovi|\bdv\b)(?![a-z0-9])", "DoVi"),
    (r"(?<![a-z0-9])(hdr10\+|hdr10plus)(?![a-z0-9])", "HDR10+"),
    (r"(?<![a-z0-9])(hdr)(?![a-z0-9])", "HDR"),
    (r"(?<![a-z0-9])(remux)(?![a-z0-9])", "REMUX"),
    (r"(?<![a-z0-9])(bdremux)(?![a-z0-9])", "BDRemux"),
    (r"(?<![a-z0-9])(blu-?ray|bdrip)(?![a-z0-9])", "BluRay"),
    (r"(?<![a-z0-9])(web-?dl)(?![a-z0-9])", "WEB-DL"),
    (r"(?<![a-z0-9])(webrip)(?![a-z0-9])", "WEBRip"),
    (r"(?<![a-z0-9])(atmos)(?![a-z0-9])", "Atmos"),
    (r"(?<![a-z0-9])(truehd|dts-hd|dts[\s._-]?hd)(?![a-z0-9])", "无损音轨"),
    (r"(?<![a-z0-9])(10bit)(?![a-z0-9])", "10bit"),
    (r"(?<![a-z0-9])(x265|h\.?265|hevc)(?![a-z0-9])", "HEVC"),
    (r"(?<![a-z0-9])(x264|h\.?264|avc)(?![a-z0-9])", "H.264"),
    (r"(?<![a-z0-9])(imax)(?![a-z0-9])", "IMAX"),
    (r"(?<![a-z0-9])(repack|proper)(?![a-z0-9])", "修正版"),
    (r"(简繁|简英|中英|双语|chs|cht|zh)", "可能带中字"),
]

_RES_RANK = {"2160p": 40.0, "1080p": 22.0, "720p": 10.0, "480p": 2.0, "": 8.0}
_TAG_BONUS = {
    "DoVi": 6.0,
    "HDR10+": 5.0,
    "HDR": 5.0,
    "REMUX": 4.0,
    "BDRemux": 3.0,
    "BluRay": 2.0,
    "WEB-DL": 1.0,
    "WEBRip": 0.5,
    "Atmos": 1.5,
    "无损音轨": 1.5,
    "IMAX": 1.5,
    "可能带中字": 3.0,
}


def detect_tags(text: str) -> list[str]:
    low = (text or "").lower()
    tags: list[str] = []
    for pattern, label in _TAGS:
        if label in tags:
            continue
        if re.search(pattern, low, re.I):
            tags.append(label)
    return tags


def _size_to_gb(size: str) -> float:
    """把 '18.2 GB' / '900 MB' / '1.2TB' 归一成 GB（失败返回 0）。"""
    m = re.search(r"([\d.]+)\s*(tb|gb|gib|mb|mib|kb|kib|b)?", str(size or ""), re.I)
    if not m:
        return 0.0
    try:
        value = float(m.group(1))
    except (TypeError, ValueError):
        return 0.0
    unit = (m.group(2) or "gb").lower()
    factor = {"tb": 1024.0, "gb": 1.0, "gib": 1.0737, "mb": 1 / 1024, "mib": 1 / 1024,
              "kb": 1 / 1024 / 1024, "kib": 1 / 1024 / 1024, "b": 1 / 1024**3}
    return value * factor.get(unit, 1.0)


def _compact(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (text or "").lower())


def _query_tokens(query: str) -> list[str]:
    parts = re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", (query or "").lower())
    return [p for p in parts if len(p) >= 2]


def score_source(item: SourceItem, prefer_resolution: str = "", query: str = "", year: int | None = None) -> float:
    """给候选打分：清晰度为主，做种数次之，特性标签/体积做加分与合理性约束。"""
    resolution = (item.resolution or item.quality or "").lower()
    score = 0.0
    for key, rank in _RES_RANK.items():
        if key and key in resolution:
            score += rank
            break
    else:
        score += _RES_RANK[""]

    if prefer_resolution and prefer_resolution.lower() in resolution:
        score += 10.0

    seeds = item.seeds if isinstance(item.seeds, int) else None
    if seeds is not None:
        # 做种数按对数给分，封顶 20
        score += min(20.0, max(0.0, (seeds**0.5) * 1.6))
    else:
        score += 3.0

    tags = item.tags or detect_tags(f"{item.title} {item.note}")
    for tag in tags:
        score += _TAG_BONUS.get(tag, 0.0)

    gb = _size_to_gb(item.size)
    if gb:
        # 体积过小（4K/1080p 却只有几 GB）多半是低码率或假种，明显扣分；过大（>90GB）略扣
        if resolution.startswith("2160") and gb < 6:
            score -= 14.0
        elif resolution.startswith("2160") and gb < 10:
            score -= 6.0
        if gb > 90:
            score -= 4.0
        score += min(3.0, gb / 40.0)

    if item.url_type == "magnet":
        score += 1.5
    elif item.url_type == "torrent":
        score += 1.0

    # 关键词相关度：索引站常返回“沾边”的结果（搜 wall-e 也会出华尔街之狼）
    title_low = (item.title or "").lower()
    tokens = _query_tokens(query)
    if tokens:
        hits = sum(1 for t in tokens if t in title_low)
        ratio = hits / len(tokens)
        if ratio >= 1.0:
            score += 18.0
        elif ratio > 0:
            score += 12.0 * ratio
        else:
            score -= 12.0
    # 整串（去掉分隔符）命中：wall-e → walle，能把 WALL-E 与 Wall Street 区分开
    compact_query = _compact(query)
    if len(compact_query) >= 4 and compact_query in _compact(item.title):
        score += 25.0
    if year and str(year) in (item.title or ""):
        score += 3.0

    return round(score, 2)


def annotate_scores(
    items: list[SourceItem], prefer_resolution: str = "", query: str = "", year: int | None = None
) -> list[SourceItem]:
    for it in items:
        if not it.tags:
            it.tags = detect_tags(f"{it.title} {it.note}")
        it.score = score_source(it, prefer_resolution=prefer_resolution, query=query, year=year)
    return items


def sort_by_score(
    items: list[SourceItem], prefer_resolution: str = "", query: str = "", year: int | None = None
) -> list[SourceItem]:
    annotate_scores(items, prefer_resolution=prefer_resolution, query=query, year=year)
    return sorted(items, key=lambda i: i.score, reverse=True)


def best_source(
    items: list[SourceItem], prefer_resolution: str = "", query: str = "", year: int | None = None
) -> SourceItem | None:
    ranked = sort_by_score(
        [i for i in items if i.url], prefer_resolution=prefer_resolution, query=query, year=year
    )
    return ranked[0] if ranked else None
