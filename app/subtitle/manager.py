"""字幕服务：下载完成后自动为视频匹配中文字幕。

策略：
1. 关键词候选：片名 → 片名+年份 → 配置里的 extra_keywords（大陆/台湾译名差异）
2. 字幕条目打分：优先 简体/双语、ASS 特效格式、发布组/清晰度关键词命中
3. 逐个候选尝试下载（前 3 个），任一成功即停
4. 解压 → 挑最佳字幕文件 → 编码规整 → 按 `{video}.zh.ass` 改名放到视频同目录
"""
from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import SubtitleConfig
from .extract import SUB_EXTS, extract_archive, find_subtitle_files, normalize_text_encoding
from .subhd import SubHDClient, SubHDEntry, SubHDError

if TYPE_CHECKING:  # pragma: no cover
    from ..llm import LLMClient

# 清晰度/来源关键词：用于和字幕条目标题比对
_HINT_TOKENS = [
    "2160p", "1080p", "720p", "uhd", "4k", "bluray", "blu-ray", "bdremux", "remux",
    "web-dl", "webrip", "hdr", "dovi", "dv", "x265", "x264", "hevc", "atmos", "truehd",
    "imax", "criterion", "sdr", "10bit",
]
_LANG_BONUS = [
    # 大陆用户优先：简英双语 > 简体 > 繁英 > 繁体 > 纯英文
    (r"(简英|中英|简繁|chs&eng|chs_eng|zh&en|中英双语|简体&英文|简体中英)", 10.0),
    (r"(简体|简中|chs|chi|中文|国语|简)", 7.0),
    (r"(繁英|cht&eng|cht_eng|繁中|繁体|cht|big5|繁)", 3.0),
    (r"(双语|bilingual)", 5.0),
    (r"(英语|english|eng\b)", 1.0),
]
_FMT_BONUS = {"ASS": 6.0, "SSA": 4.0, "SRT": 3.0, "SUP": 2.0, "SUB": 1.0}
_SUB_FILE_RANK = {".ass": 4, ".ssa": 3, ".srt": 2, ".sup": 1, ".sub": 0, ".idx": 0, ".vtt": 2}
_RELEASE_GROUP_RE = re.compile(r"(?:^|[.\-_])([A-Za-z][A-Za-z0-9]{1,11})$")


def _title_prefix(stem: str) -> str:
    """取文件名里第一个画质/来源标记之前的部分，作为片名候选。"""
    parts = re.split(r"[.\-_ ]+", stem)
    keep: list[str] = []
    for part in parts:
        low = part.lower()
        if not part:
            continue
        if low in _HINT_TOKENS or re.fullmatch(r"(19|20)\d{2}", part):
            break
        keep.append(part)
        if len(keep) >= 5:
            break
    return " ".join(keep).strip()


@dataclass
class SubtitleResult:
    ok: bool
    message: str = ""
    files: list[str] = field(default_factory=list)
    entry_title: str = ""


def tokens_from_video(video: Path | str) -> list[str]:
    stem = Path(video).stem if isinstance(video, (str, Path)) else str(video)
    low = stem.lower()
    tokens = [t for t in _HINT_TOKENS if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", low)]
    group = _RELEASE_GROUP_RE.search(stem)
    if group:
        token = group.group(1)
        if token.lower() not in tokens and token.lower() not in ("by", "repack", "proper"):
            tokens.append(token.lower())
    return tokens


def _score_entry(
    entry: SubHDEntry,
    tokens: list[str],
    prefer_bilingual: bool,
    prefer_simplified: bool = True,
) -> float:
    title = entry.title or ""
    lang_text = f"{title} {entry.lang or ''}"
    score = 0.0
    simplified = bool(re.search(r"(简体|简中|简英|简繁|chs|\bzh\b)", lang_text, re.I))
    traditional = bool(re.search(r"(繁体|繁中|繁英|cht|big5)", lang_text, re.I))
    for pattern, bonus in _LANG_BONUS:
        if re.search(pattern, lang_text, re.I):
            score += bonus * (1.2 if prefer_bilingual and bonus >= 8.0 else 1.0)
            break
    # 大陆用户优先简体：简繁同时出现（简繁双语）也算简体优先
    if prefer_simplified:
        if simplified:
            score += 6.0
        elif traditional:
            score -= 4.0
    score += _FMT_BONUS.get((entry.fmt or "").upper(), 0.0)
    low = title.lower()
    matched_year = bool(re.search(r"\b(19|20)\d{2}\b", title))
    for token in tokens:
        if token and token in low:
            score += 3.0
        elif token and token in f"{entry.lang or ''}".lower():
            score += 1.0
    if "1080p" in low and "2160p" not in low and "uhd" not in low:
        score -= 1.5
    if entry.year and matched_year and str(entry.year) in title:
        score += 0.5
    # 标题过短/只有片名的条目信息不足，略降权
    if len(title) < 8:
        score -= 1.0
    return score


def _token_hit(entry: SubHDEntry, tokens: list[str]) -> bool:
    text = f"{entry.title} {entry.lang or ''}".lower()
    return any(t and t in text for t in tokens)


def _score_sub_file(path: Path) -> float:
    score = _SUB_FILE_RANK.get(path.suffix.lower(), -1) * 1.0
    name = path.name
    so = name.lower()
    if re.search(r"(简英|中英|双语|简体|chs|chi|zh)", so):
        score += 3.0
    elif re.search(r"(繁|cht)", so):
        score += 1.0
    if re.search(r"(eng|english)", so) and not re.search(r"(简英|中英|双语)", so):
        score -= 2.0
    return score


class SubtitleService:
    def __init__(self, cfg: SubtitleConfig, llm: "LLMClient | None" = None):
        self.cfg = cfg
        self.llm = llm

    # ---------- 对外 ----------
    async def fetch_for_video(
        self,
        video: Path,
        title: str = "",
        year: int | None = None,
        quality: str = "",
    ) -> SubtitleResult:
        """阻塞流程放到线程里跑，避免卡住事件循环。"""
        video = Path(video)
        keywords = self._keyword_candidates(video, title, year)
        if self.cfg.llm_translate and self._need_chinese(keywords):
            zh = await self._llm_chinese_titles(title or video.stem, year)
            if zh:
                keywords = zh + keywords
        return await asyncio.to_thread(self._fetch_sync, video, title, year, quality, keywords)

    @staticmethod
    def _need_chinese(keywords: list[str]) -> bool:
        return not any(re.search(r"[\u4e00-\u9fff]", k) for k in keywords)

    async def _llm_chinese_titles(self, name: str, year: int | None) -> list[str]:
        """SubHD 对英文名匹配很差，用已配置的大模型补中文译名。失败不影响主流程。"""
        if self.llm is None or not getattr(self.llm.cfg, "api_key", ""):
            return []
        hint = f"{name} {year}" if year else name
        system = (
            "你是影视名称助手。给出这部电影的简体中文名（如有大陆译名、台湾译名、常见别名都要）。"
            "只输出 JSON 数组，例如 [\"机器人总动员\"]，不要其它说明。最多 3 个，按常用度排序。"
        )
        try:
            content = await self.llm.chat(
                [{"role": "system", "content": system}, {"role": "user", "content": hint}],
                temperature=0,
            )
        except Exception:  # noqa: BLE001
            return []
        from ..llm import _extract_json_block

        data = _extract_json_block(content)
        out: list[str] = []
        if isinstance(data, list):
            for item in data:
                text = str(item).strip()
                if text and re.search(r"[\u4e00-\u9fff]", text):
                    out.append(text)
        return out[:3]

    # ---------- 内部 ----------
    def _keyword_candidates(self, video: Path, title: str, year: int | None) -> list[str]:
        cands: list[str] = []
        hint = (self.cfg.match_hint or "").strip()
        if hint:
            cands.append(hint)
        base_title = (title or "").strip()
        if base_title:
            cands.append(base_title)
            if year:
                cands.append(f"{base_title} {year}")
        # 从文件名里抠英文名（去掉年份/清晰度/来源等）
        stem = video.stem
        english = re.sub(r"[._]", " ", stem)
        english = re.sub(r"(?<![a-z0-9])(2160p|1080p|720p|bluray|blu-ray|bdremux|remux|web-dl|webrip|hdr|dovi|x265|x264|hevc|atmos|truehd|10bit|uhd|4k)(?![a-z0-9])", " ", english, flags=re.I)
        english = re.sub(r"\b(19|20)\d{2}\b", " ", english)
        english = re.sub(r"\s+", " ", english).strip(" -_.")
        if english:
            cands.append(english)
            parts = english.split()
            if parts:
                cands.append(" ".join(parts[:3]))
        prefix = _title_prefix(stem)
        if prefix:
            cands.append(prefix)
            cands.append(prefix.replace("-", " "))
        for kw in self.cfg.extra_keywords:
            kw = (kw or "").strip()
            if kw:
                cands.append(kw)
        seen: set[str] = set()
        out: list[str] = []
        for c in cands:
            key = c.lower()
            if len(c) >= 2 and key not in seen:
                seen.add(key)
                out.append(c)
        return out

    def _fetch_sync(
        self,
        video: Path,
        title: str,
        year: int | None,
        quality: str,
        keywords: list[str] | None = None,
    ) -> SubtitleResult:
        if not self.cfg.enabled:
            return SubtitleResult(ok=False, message="字幕功能未启用")
        if not video.exists():
            return SubtitleResult(ok=False, message=f"视频文件不存在：{video}")

        tokens = tokens_from_video(video)
        if quality:
            tokens.extend(t for t in _HINT_TOKENS if t in quality.lower())
        client = SubHDClient(timeout=max(10, self.cfg.timeout_seconds))
        errors: list[str] = []

        for keyword in (keywords or self._keyword_candidates(video, title, year)):
            try:
                entries = client.list_by_keyword(keyword, year=year, max_movies=max(1, self.cfg.max_movies))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{keyword}: {exc}")
                continue
            if not entries:
                errors.append(f"{keyword}: 无字幕条目")
                continue

            ranked = sorted(
                entries,
                key=lambda e: _score_entry(e, tokens, self.cfg.prefer_bilingual, self.cfg.prefer_simplified),
                reverse=True,
            )[:3]
            keyword_is_cn = bool(re.search(r"[\u4e00-\u9fff]", keyword))
            skipped = 0
            for entry in ranked:
                score = _score_entry(entry, tokens, self.cfg.prefer_bilingual, self.cfg.prefer_simplified)
                # 英文关键词经常会搜到同系列短片/别名（如用 WALL-E 搜到《电焊工波力》），
                # 此时要求条目里能找到片源特征（2160p/DVT…），否则宁可不配也不配错。
                if not keyword_is_cn and not _token_hit(entry, tokens):
                    skipped += 1
                    continue
                if not keyword_is_cn and score < 2.0:
                    skipped += 1
                    continue
                try:
                    result = self._try_entry(client, entry, video)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{entry.title[:30]}: {exc}")
                    continue
                if result.ok:
                    return result
                errors.append(f"{entry.title[:30]}: {result.message}")
            if skipped:
                errors.append(
                    f"{keyword}: {skipped} 条候选与片源信息不匹配已跳过（可能是同系列短片或别名）"
                )
        tail = ("；".join(errors[-3:])) if errors else "无可用候选"
        return SubtitleResult(ok=False, message=f"未找到可用中文字幕（{tail}）")

    def _try_entry(self, client: SubHDClient, entry: SubHDEntry, video: Path) -> SubtitleResult:
        with tempfile.TemporaryDirectory(prefix="moviedock-sub-") as tmp:
            tmp_dir = Path(tmp)
            try:
                archive = client.fetch_entry(entry.sid, tmp_dir)
                extract_dir = tmp_dir / "out"
                try:
                    extract_archive(archive, extract_dir, self.cfg.extract_tools)
                except RuntimeError as exc:
                    return SubtitleResult(ok=False, message=f"解压失败：{exc}")
                files = find_subtitle_files(extract_dir)
                if not files:
                    return SubtitleResult(ok=False, message="压缩包里没有字幕文件")
                best = max(files, key=_score_sub_file)
                enc = normalize_text_encoding(best)
                name = self.cfg.name_template.format(video=video.stem)
                target = video.parent / f"{name}{best.suffix.lower()}"
                shutil.copyfile(best, target)
                note = f"{entry.title[:40]}（{best.name}，{len(files)} 个字幕文件"
                note += f"，源编码 {enc}）" if enc and enc != "utf-8" else "）"
                return SubtitleResult(ok=True, message=note, files=[str(target)], entry_title=entry.title)
            except SubHDError as exc:
                raise
