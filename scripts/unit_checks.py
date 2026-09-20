# -*- coding: utf-8 -*-
"""新增功能的本地单元回归（不联网，纯逻辑层）。

覆盖：剧集识别 / 整理增强 / 候选评分 / qBittorrent 结果映射 /
字幕条目打分与关键词 / 归档解压 / 任务状态持久化。
"""
from __future__ import annotations

import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="moviedock-unit-"))
os.environ["MOVIE_DOCK_CONFIG"] = str(TMP / "config.yaml")

from app.runtime import ensure_utf8

ensure_utf8()

from app.config import OrganizeConfig, ProviderConfig, load_config, save_app_config  # noqa: E402
from app.downloader.manager import DownloadManager, DownloadTask  # noqa: E402
from app.models import SourceItem  # noqa: E402
from app.organizer import Organizer, episode_label, parse_episode  # noqa: E402
from app.ranking import best_source, detect_tags, sort_by_score  # noqa: E402
from app.search.qbittorrent import QBittorrentProvider  # noqa: E402
from app.subtitle.extract import extract_archive, find_subtitle_files  # noqa: E402
from app.subtitle.manager import SubtitleService, tokens_from_video  # noqa: E402
from app.subtitle.subhd import SubHDEntry  # noqa: E402

results: list[tuple[str, str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, "PASS" if cond else "FAIL", str(detail)))


# ---------- 1) 剧集识别 ----------
cases = {
    "Show.S01E02.1080p.WEB-DL": (1, 2),
    "show.s1e2": (1, 2),
    "Show.1x03.720p": (1, 3),
    "剧集名称.第5集.HD": (1, 5),
    "Show.E07.2160p": (1, 7),
    "WALL-E.2008.2160p.UHD.BDRemux.HDR.DoVi.P8.Hybrid.by.DVT": (None, None),
}
ok = True
detail = []
for text, expect in cases.items():
    got = parse_episode(text)
    detail.append(f"{text}->{got}")
    if got != expect:
        ok = False
check("parse_episode", ok, "; ".join(detail))
check("episode_label", episode_label(1, 2) == "S01E02" and episode_label(None, None) == "",
      f"{episode_label(1, 2)}/{episode_label(None, None)}")

# ---------- 2) 整理增强：扩展名保留 / 剧集模板 / library_root ----------
with tempfile.TemporaryDirectory() as td:
    td_path = Path(td)
    src = td_path / "raw" / "Show.S01E02.2160p.WEB-DL.mp4"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"x" * 32)
    org = Organizer(OrganizeConfig(enabled=True, mode="copy"), td_path / "dl")
    final = org.organize_file(src, title="示例剧集", year=2024, quality="2160p",
                              options={"enabled": True, "mode": "copy"})
    check("organize_series_path", "Season 01" in str(final) and final.name.endswith(".mp4"), str(final))
    check("organize_series_name", "S01E02" in final.name, final.name)
    check("organize_series_nested", "/Season 01/" in str(final).replace("\\", "/"), str(final))

    # 电影 + 自定义资料库目录（模拟 /vol2/1000/movie）
    movie = td_path / "raw" / "WALL-E.2008.2160p.BDRemux.mkv"
    movie.write_bytes(b"y" * 32)
    lib = td_path / "library"
    final2 = org.organize_file(movie, title="WALL-E", year=2008, quality="2160p",
                               options={"enabled": True, "mode": "copy", "library_root": str(lib)})
    check("organize_library_root", str(final2).startswith(str(lib / "WALL-E (2008)")), str(final2))

    # 预览路径带扩展名（旧版硬写 .mkv）
    dest_dir, dest = org.build_paths(title="沙丘2", year=2024, quality="1080p", ext=".mp4")
    check("preview_ext", dest.name == "沙丘2 (2024) - 1080p.mp4", dest.name)

# ---------- 3) 候选评分与排序 ----------
wall_e_4k = SourceItem(
    id="a", title="WALL-E.2008.2160p.UHD.BDRemux.HDR.DoVi.P8.Hybrid.by.DVT", quality="2160p",
    resolution="2160p", size="38.2 GB", seeds=19, url="magnet:?xt=urn:btih:aaa", url_type="magnet")
wall_e_1080 = SourceItem(
    id="b", title="WALL-E.2008.1080p.BluRay.x264.TrueHD.7.1.Atmos-SWTYBLZ", quality="1080p",
    resolution="1080p", size="12 GB", seeds=180, url="magnet:?xt=urn:btih:bbb", url_type="magnet")
fake_4k = SourceItem(
    id="c", title="WALL-E.2008.2160p.WEB-DL.x265", quality="2160p", resolution="2160p",
    size="1.2 GB", seeds=3, url="magnet:?xt=urn:btih:ccc", url_type="magnet")
ranked = sort_by_score([wall_e_1080, fake_4k, wall_e_4k], prefer_resolution="2160p")
check("ranking_top_is_4k_remux", ranked[0].id == "a", [f"{i.id}:{i.score}" for i in ranked])
check("ranking_penalizes_tiny_4k", ranked[-1].id == "c", [f"{i.id}:{i.score}" for i in ranked])
check("ranking_best_source", (best_source(ranked) or ranked[0]).id == "a", "best")
tags = detect_tags("WALL-E.2008.2160p.UHD.BDRemux.HDR.DoVi.P8.Hybrid.by.DVT")
check("detect_tags", "DoVi" in tags and "HDR" in tags and "BDRemux" in tags, str(tags))

# ---------- 4) qBittorrent 结果映射 ----------
pc = ProviderConfig(type="qbittorrent", enabled=True, name="qB", url="http://127.0.0.1:8085",
                    options={"username": "admin", "password": "x", "plugins": "yts,bt4g"})
qbt = QBittorrentProvider(pc)
item = qbt._to_item({
    "fileName": "沙丘2.Dune.Part.Two.2024.2160p.BluRay.REMUX.DoVi.HDR.mkv",
    "fileUrl": "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567",
    "fileSize": 12 * 1024**3,
    "nbSeeders": 56,
    "nbLeechers": 8,
    "siteUrl": "bt4g",
    "pubDate": "2024-05-01T00:00:00Z",
}, 0)
check("qbt_map_quality", item.quality == "4K" and item.resolution == "2160p", f"{item.resolution}/{item.quality}")
check("qbt_map_size_seeds", item.size.startswith("12.00 GB") and item.seeds == 56, f"{item.size}/{item.seeds}")
check("qbt_map_type", item.url_type == "magnet", item.url_type)

# ---------- 5) 字幕：关键词 / 打分 / 命名 ----------
cfg = load_config(TMP / "config.yaml")
cfg.subtitle.extra_keywords = ["机器人总动员", "瓦力"]
service = SubtitleService(cfg.subtitle)
video = ROOT / "downloads" / "WALL-E.2008.2160p.UHD.BDRemux.HDR.DoVi.P8.Hybrid.by.DVT.mkv"
kw = service._keyword_candidates(video, "", 2008)
check("subtitle_keywords_extra", "机器人总动员" in kw and "瓦力" in kw, str(kw[:4]))
check("subtitle_keywords_english", any("WALL E" in k for k in kw), str(kw[:5]))
tokens = tokens_from_video(video)
check("subtitle_tokens", "2160p" in tokens and "uhd" in tokens and "dvt" in tokens, str(tokens))

from app.subtitle.manager import _score_entry, _score_sub_file  # noqa: E402

ass_bilingual = SubHDEntry(sid="1", title="WALL-E.2008.2160p.UHD.BluRay.4K适配HDR 简英双语", fmt="ASS")
srt_only = SubHDEntry(sid="2", title="WALL-E.2008.1080p.BluRay", fmt="SRT")
check("subtitle_entry_prefers_ass_bilingual",
      _score_entry(ass_bilingual, tokens, True) > _score_entry(srt_only, tokens, True),
      f"{_score_entry(ass_bilingual, tokens, True)} vs {_score_entry(srt_only, tokens, True)}")
check("subtitle_file_rank", _score_sub_file(Path("x.zh.ass")) > _score_sub_file(Path("x.eng.srt")), "ass>.eng.srt")

# 同一发布版本下，简体版应优先于繁体版（真机反馈：繁英被选中过）
ass_simp = SubHDEntry(sid="3", title="WALL-E.2008.1080p.BluRay.x264 简英双语", fmt="ASS", lang="双语 简体 英语")
ass_trad = SubHDEntry(sid="4", title="WALL-E.2008.1080p.BluRay.x264.DTS-WiKi.cht&eng", fmt="ASS", lang="双语 繁体 英语")
check("subtitle_simplified_preferred",
      _score_entry(ass_simp, tokens, True, True) > _score_entry(ass_trad, tokens, True, True),
      f"简={_score_entry(ass_simp, tokens, True, True)} 繁={_score_entry(ass_trad, tokens, True, True)}")
name = cfg.subtitle.name_template.format(video=video.stem)
check("subtitle_name_template", name.endswith(".zh") and "DVT" in name, name)

# ---------- 6) 归档解压（zip 含中文名 / rar 兜底） ----------
with tempfile.TemporaryDirectory() as td:
    td_path = Path(td)
    arch = td_path / "sub.zip"
    with zipfile.ZipFile(arch, "w") as z:
        z.writestr("机器人总动员.WALL.E.2008.2160p.zh.ass", "[Script Info]\nTitle: t\n")
    out = td_path / "out"
    files = extract_archive(arch, out)
    check("extract_zip", len(find_subtitle_files(out)) == 1, str([f.name for f in files]))

    # rar 场景：本机若有 7z/bsdtar 才能解，这里只验证“失败会给出明确报错”或解压成功
    rar = td_path / "broken.rar"
    rar.write_bytes(b"Rar!\x1a\x07\x00" + b"\x00" * 64)
    try:
        extract_archive(rar, td_path / "out2")
        check("extract_rar_path", True, "解压成功（工具可用）")
    except Exception as exc:  # noqa: BLE001
        check("extract_rar_path", "解压失败" in str(exc) or "7z" in str(exc) or "bsdtar" in str(exc), str(exc)[:80])

# ---------- 7) 任务状态持久化 + per-task 目录 + aria2 选项 ----------
cfg = load_config(TMP / "config.yaml")
cfg.paths.download_root = str(TMP / "dl")
cfg.paths.state_dir = str(TMP / "data")
cfg.subtitle.enabled = False
cfg.downloader.bt_trackers = "udp://tracker.example:1337/announce"
save_app_config(cfg)
cfg = load_config(TMP / "config.yaml")

mgr = DownloadManager(cfg)
mgr.tasks["active1"] = DownloadTask(task_id="active1", title="进行中", url="magnet:?xt=urn:btih:1",
                                    status="active", gid="g1", created_at="2026-01-01T00:00:00+08:00")
mgr.tasks["done1"] = DownloadTask(task_id="done1", title="已完成", url="magnet:?xt=urn:btih:2",
                                  status="complete", created_at="2026-01-02T00:00:00+08:00",
                                  organized_path=str(TMP / "dl" / "movies" / "x.mkv"),
                                  subtitle_status="done", subtitle_path="/x/x.zh.ass",
                                  subtitle_note="测试字幕")
mgr._dirty = True
mgr._persist(force=True)

mgr2 = DownloadManager(cfg)
check("persist_keeps_complete", (mgr2.get("done1") or DownloadTask(task_id="?")).status == "complete",
      str(getattr(mgr2.get("done1"), "status", None)))
check("persist_marks_interrupted", getattr(mgr2.get("active1"), "status", "") == "interrupted",
      str(getattr(mgr2.get("active1"), "status", "")))
check("persist_subtitle_fields", getattr(mgr2.get("done1"), "subtitle_path", "") == "/x/x.zh.ass",
      str(getattr(mgr2.get("done1"), "subtitle_path", "")))

task = DownloadTask(task_id="dir1", title="t", url="magnet:?xt=urn:btih:3")
opts = mgr2._aria2_options(task)
check("aria2_no_seed", opts.get("seed-time") == "0" and opts.get("seed-ratio") == "0.0", str(opts.get("seed-time")))
check("aria2_tracker", opts.get("bt-tracker", "").startswith("udp://tracker.example"), str(opts.get("bt-tracker")))
check("aria2_per_task_dir", str(opts["dir"]).endswith("dir1") and "incoming" in str(opts["dir"]), str(opts["dir"]))

# ---------- 8) 配置往返（新增字段不丢） ----------
custom = next(p for p in cfg.search.providers if p.type == "custom_api")
custom.options = {"foo": "bar"}
cfg.organize.library_root = "/vol2/1000/movie"
cfg.subtitle.match_hint = "4K适配HDR"
save_app_config(cfg)
cfg_reload = load_config(TMP / "config.yaml")
check("config_options_roundtrip",
      next(p for p in cfg_reload.search.providers if p.type == "custom_api").options.get("foo") == "bar",
      str([p.options for p in cfg_reload.search.providers if p.type == "custom_api"]))
check("config_library_root", cfg_reload.organize.library_root == "/vol2/1000/movie", cfg_reload.organize.library_root)
check("config_subtitle_hint", cfg_reload.subtitle.match_hint == "4K适配HDR", cfg_reload.subtitle.match_hint)

# ---------- 9) 磁力 followedBy 接管 + 占位文件防整理（真机发现的 bug） ----------
import asyncio  # noqa: E402


class _FakeAria2:
    """按顺序返回预设状态，模拟 aria2 RPC。"""

    def __init__(self, states: dict):
        self.states = states
        self.calls: list[str] = []

    async def tell_status(self, gid: str) -> dict:
        self.calls.append(gid)
        return self.states.get(gid, {})


with tempfile.TemporaryDirectory() as td:
    td_path = Path(td)
    cfg2 = load_config(TMP / "config.yaml")
    cfg2.paths.download_root = str(td_path / "dl")
    cfg2.paths.state_dir = str(td_path / "data")
    cfg2.subtitle.enabled = False
    cfg2.organize.library_root = ""  # 清掉上一节写入的资料库目录，避免写到无权限路径
    save_app_config(cfg2)
    cfg2 = load_config(TMP / "config.yaml")
    mgr3 = DownloadManager(cfg2)

    # A) 磁力：元数据下载完成 → 切换到 followedBy 的真实 GID，不得当成完成
    task_dir = td_path / "dl" / "incoming" / "mag1"
    task_dir.mkdir(parents=True, exist_ok=True)
    real_file = task_dir / "WALL-E.mp4"
    real_file.write_bytes(b"x" * 1000)
    meta_torrent = task_dir / "6687a51b.torrent"
    meta_torrent.write_bytes(b"y" * 13288)
    fake = _FakeAria2({
        "meta1": {"status": "complete", "followedBy": ["real1"], "totalLength": "13288",
                  "completedLength": "13288", "files": [{"path": str(meta_torrent), "length": "13288"}]},
        "real1": {"status": "active", "totalLength": "1000000", "completedLength": "1000",
                  "downloadSpeed": "500", "files": [{"path": str(real_file), "length": "1000000"}]},
        "real2": {"status": "complete", "totalLength": "1000", "completedLength": "1000",
                  "files": [{"path": str(real_file), "length": "1000"}]},
    })
    mgr3.aria2 = fake  # type: ignore[assignment]
    t_mag = DownloadTask(task_id="mag1", title="WALL-E", url="magnet:?xt=urn:btih:aaa",
                         status="active", gid="meta1", engine="aria2",
                         organize_opts={"enabled": True, "mode": "copy"},
                         created_at="2026-01-03T00:00:00+08:00")
    mgr3.tasks = {"mag1": t_mag}
    asyncio.run(mgr3._poll_once())
    check("magnet_followedby_adopt", t_mag.gid == "real1" and t_mag.status == "active",
          f"gid={t_mag.gid} status={t_mag.status}")
    check("magnet_not_finalized_early", not t_mag.organized_path and real_file.exists(),
          f"organized={t_mag.organized_path}")

    # B) 文件还没写完（总长对不上）→ 不得整理；写完后再轮询才收尾
    t2 = DownloadTask(task_id="mag2", title="WALL-E", url="magnet:?xt=urn:btih:bbb",
                      status="active", gid="real2", engine="aria2",
                      organize_opts={"enabled": True, "mode": "copy"},
                      created_at="2026-01-04T00:00:00+08:00")
    mgr3.tasks = {"mag2": t2}
    real_file.write_bytes(b"z" * 500)   # 只写了一半
    fake.states["real2"]["files"][0]["length"] = "1000"
    asyncio.run(mgr3._poll_once())
    check("incomplete_file_not_organized", t2.status == "active" and not t2.organized_path,
          f"status={t2.status} organized={t2.organized_path}")

    real_file.write_bytes(b"z" * 1000)  # 写完了
    asyncio.run(mgr3._poll_once())
    check("complete_after_full_size", t2.status == "complete" and bool(t2.organized_path),
          f"status={t2.status} organized={t2.organized_path}")
    check("torrent_metadata_excluded",
          all(p.suffix.lower() != ".torrent" for p in mgr3._collect_output_files(t2, [str(meta_torrent)])),
          str([p.name for p in mgr3._collect_output_files(t2, [str(meta_torrent)])]))

# ---------- 10) 磁力 dn= 推断片名（粘贴下载路径） ----------
from app.downloader.manager import _title_from_url  # noqa: E402

magnet = ("magnet:?xt=urn:btih:6687A51BB38802620E13542D9C50235039F939D1"
          "&dn=WALL-E+%282008%29+1080p+BrRip+x264+-+1.20GB+-+YIFY")
title, year = _title_from_url(magnet)
check("magnet_dn_title", title == "WALL-E" and year == 2008, f"{title}/{year}")
title2, year2 = _title_from_url("https://example.com/Some.Movie.2019.1080p.mkv")
check("url_fallback_title", bool(title2), f"{title2}/{year2}")

# ---------- 11) 内置直连索引源（不依赖 qBittorrent） ----------
import asyncio as _aio  # noqa: E402
import json  # noqa: E402

from app.search.builtin import BuiltinProvider, DMHYSource, TPBSource, YTSSource  # noqa: E402
from app.search.common import build_magnet, human_size, int_or_none  # noqa: E402

check("common_human_size", human_size(1293736264).startswith("1.21 GB") or "GB" in human_size(1293736264),
      human_size(1293736264))
check("common_int_or_none", int_or_none("52") == 52 and int_or_none("x") is None, "ok")
mag = build_magnet("6687A51BB38802620E13542D9C50235039F939D1", "WALL-E 2008")
check("common_magnet", mag.startswith("magnet:?xt=urn:btih:6687") and "&dn=WALL-E%202008" in mag and "&tr=" in mag, mag[:60])

# TPB / apibay JSON
tpb_payload = json.dumps([
    {"id": "1", "name": "WALL-E (2008) [1080p]",
     "info_hash": "6687A51BB38802620E13542D9C50235039F939D1", "leechers": "8", "seeders": "52",
     "num_files": "3", "size": "1293736264", "category": "207"},
    {"id": "0", "name": "No results returned", "info_hash": "0000000000000000000000000000000000000000",
     "seeders": "0", "leechers": "0", "size": "0"},
])
tpb_items = TPBSource().parse(tpb_payload, "https://apibay.org")
check("tpb_parse", len(tpb_items) == 1 and tpb_items[0].quality == "1080p" and tpb_items[0].seeds == 52,
      f"{len(tpb_items)} 条 / {tpb_items[0].seeds if tpb_items else '-'}")
check("tpb_magnet", tpb_items and tpb_items[0].url.startswith("magnet:?xt=urn:btih:6687"), "ok")

# YTS JSON
yts_payload = json.dumps({"status": "ok", "data": {"movies": [{
    "title": "Wall-E", "title_long": "Wall-E (2008)", "year": 2008,
    "torrents": [{"hash": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "quality": "1080p", "type": "bluray",
                 "size_bytes": 1293736264, "seeds": 100, "peers": 10, "video_codec": "x264"}],
}]}})
yts_items = YTSSource().parse(yts_payload, "https://yts.mx")
check("yts_parse", len(yts_items) == 1 and yts_items[0].seeds == 100 and "Wall-E (2008)" in yts_items[0].title,
      yts_items[0].title if yts_items else "empty")

# DMHY RSS
dmhy_payload = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><item>
  <title>[DMG][WALL-E][1080p][BDRip]</title>
  <enclosure url="magnet:?xt=urn:btih:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB" length="1" type="application/x-bittorrent" />
  <description>大小：1.2GB</description>
  <pubDate>Sat, 20 Sep 2026 10:00:00 +0800</pubDate>
</item></channel></rss>"""
dmhy_items = DMHYSource().parse(dmhy_payload, "https://share.dmhy.org")
check("dmhy_parse", len(dmhy_items) == 1 and dmhy_items[0].url.startswith("magnet:") and dmhy_items[0].quality == "1080p",
      f"{len(dmhy_items)} 条")
check("dmhy_size", dmhy_items and dmhy_items[0].size == "1.2 GB", dmhy_items[0].size if dmhy_items else "-")

# Provider：源选择 / 代理优先级 / 去重
from app.config import ProviderConfig  # noqa: E402

pc = ProviderConfig(type="builtin", enabled=True, name="内置索引",
                    options={"sources": "tpb,notexist", "proxy": "http://127.0.0.1:7891"})
prov = BuiltinProvider(pc, global_proxy="http://127.0.0.1:7890", global_timeout=20)
check("builtin_source_filter", [s.key for s in prov.sources] == ["tpb"], [s.key for s in prov.sources])
check("builtin_proxy_precedence", prov.proxy == "http://127.0.0.1:7891", prov.proxy)
prov2 = BuiltinProvider(ProviderConfig(type="builtin", enabled=True, options={}), global_proxy="http://127.0.0.1:7890")
check("builtin_global_proxy", prov2.proxy == "http://127.0.0.1:7890", prov2.proxy)
check("builtin_default_sources", [s.key for s in prov2.sources] == ["tpb", "yts", "dmhy"], [s.key for s in prov2.sources])


class _FakeSource:
    key = "fake"
    label = "假源"
    endpoints = ["http://x"]
    limit = 10

    async def search(self, client, query, source_name):  # noqa: ANN001
        from app.models import SourceItem as _SI

        return [
            _SI(id="a", title=f"{query} A", quality="1080p", url="magnet:?xt=urn:btih:same", url_type="magnet"),
            _SI(id="b", title=f"{query} B", quality="2160p", url="magnet:?xt=urn:btih:dup", url_type="magnet"),
        ], ""


from app.models import SearchRequest  # noqa: E402

prov3 = BuiltinProvider(ProviderConfig(type="builtin", enabled=True, options={}))
prov3.sources = [_FakeSource()]
res_items, res_warn = _aio.run(prov3.search(SearchRequest(query="wall-e")))
check("builtin_merge_dedupe", len(res_items) == 2, f"{len(res_items)} 条")


# 相关度过滤：无关结果必须剔除（真机发现 TPB 对中文关键词返回垃圾）
class _GarbageSource:
    key = "garbage"
    label = "垃圾源"
    endpoints = ["http://x"]
    limit = 10

    async def search(self, client, query, source_name):  # noqa: ANN001
        from app.models import SourceItem as _SI

        return [
            _SI(id="g1", title="Avira System Speedup Pro + Crack", quality="未知",
                url="magnet:?xt=urn:btih:junk1", url_type="magnet"),
            _SI(id="g2", title="Some Other Unrelated Movie 1999", quality="1080p",
                url="magnet:?xt=urn:btih:junk2", url_type="magnet"),
            _SI(id="g3", title="WALL-E 2008 1080p BluRay", quality="1080p",
                url="magnet:?xt=urn:btih:good3", url_type="magnet"),
        ], ""


prov4 = BuiltinProvider(ProviderConfig(type="builtin", enabled=True, options={}))
prov4.sources = [_GarbageSource()]
items4, _w4 = _aio.run(prov4.search(SearchRequest(query="wall-e")))
check("builtin_relevance_filter", len(items4) == 1 and items4[0].id == "g3", [i.id for i in items4])

prov5 = BuiltinProvider(ProviderConfig(type="builtin", enabled=True, options={}))
prov5.sources = [_GarbageSource()]
items5, warn5 = _aio.run(prov5.search(SearchRequest(query="机器人总动员", year=2008)))
check("builtin_cjk_all_garbage_dropped", len(items5) == 0, f"{len(items5)} 条")
check("builtin_cjk_hint", any("中文关键词" in w for w in warn5), str(warn5)[:120])


# 大模型翻译辅助：中文名 → 英文名后再搜
class _FakeLLM:
    class cfg:  # noqa: N801
        api_key = "sk-test"

    async def chat(self, messages, temperature=0):  # noqa: ANN001, ARG002
        return "WALL-E"


class _HintRecorder:
    key = "rec"
    label = "记录源"
    endpoints = ["http://x"]
    limit = 10

    def __init__(self):
        self.seen: list[str] = []

    async def search(self, client, query, source_name):  # noqa: ANN001
        from app.models import SourceItem as _SI

        self.seen.append(query)
        if query.upper() == "WALL-E":
            return [_SI(id="r1", title="WALL-E 2008 1080p", quality="1080p",
                        url="magnet:?xt=urn:btih:good", url_type="magnet")], ""
        return [], "无结果"


rec = _HintRecorder()
prov6 = BuiltinProvider(ProviderConfig(type="builtin", enabled=True, options={}), llm=_FakeLLM())
prov6.sources = [rec]
items6, _w6 = _aio.run(prov6.search(SearchRequest(query="机器人总动员", year=2008)))
check("builtin_llm_translate_used", "WALL-E" in rec.seen and len(items6) == 1, str(rec.seen))

# ---------- 12) 老配置自动迁移（0.2.x 没有 builtin，升级后必须补上） ----------
import yaml as _yaml  # noqa: E402

mig_dir = Path(tempfile.mkdtemp(prefix="moviedock-migrate-"))
old_cfg_path = mig_dir / "config.yaml"
old_cfg_path.write_text(
    _yaml.safe_dump(
        {
            "paths": {"download_root": str(mig_dir / "dl"), "state_dir": str(mig_dir / "data")},
            "search": {
                "providers": [
                    {"type": "demo", "enabled": False, "name": "演示数据"},
                    {"type": "llm", "enabled": False, "name": "大模型检索"},
                    {"type": "qbittorrent", "enabled": True, "name": "qBittorrent 搜索",
                     "url": "http://127.0.0.1:8085",
                     "options": {"username": "admin", "password": "", "plugins": "yts,bt4g"}},
                    {"type": "custom_api", "enabled": False, "name": "自定义索引"},
                ]
            },
        },
        allow_unicode=True,
        sort_keys=False,
    ),
    encoding="utf-8",
)
os.environ["MOVIE_DOCK_CONFIG"] = str(old_cfg_path)
migrated = load_config(old_cfg_path)
types = [p.type for p in migrated.search.providers]
check("migrate_builtin_injected", "builtin" in types, str(types))
check("migrate_builtin_enabled",
      next(p for p in migrated.search.providers if p.type == "builtin").enabled is True,
      "enabled")
check("migrate_builtin_first", types[0] == "builtin", str(types[:2]))
check("migrate_keeps_old_providers", "qbittorrent" in types, str(types))
back = _yaml.safe_load(old_cfg_path.read_text(encoding="utf-8"))
check("migrate_persisted",
      any(p.get("type") == "builtin" for p in back["search"]["providers"]),
      "写入配置")
os.environ["MOVIE_DOCK_CONFIG"] = str(TMP / "config.yaml")

# ---------- 输出 ----------
print("=" * 68)
failed = 0
for name, status, detail in results:
    print(f"[{status}] {name} :: {detail}")
    if status == "FAIL":
        failed += 1
print("=" * 68)
print(f"TOTAL={len(results)} FAIL={failed}")
sys.exit(1 if failed else 0)
