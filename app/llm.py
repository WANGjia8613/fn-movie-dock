from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import LLMConfig
from .models import LLMConfigIn, LLMTestResponse, SourceItem


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg

    @classmethod
    def from_in(cls, data: LLMConfigIn) -> "LLMClient":
        return cls(
            LLMConfig(
                base_url=data.base_url.rstrip("/"),
                api_key=data.api_key,
                model=data.model,
                timeout_seconds=max(5, int(data.timeout_seconds or 60)),
            )
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            headers["Authorization"] = f"Bearer {self.cfg.api_key}"
        return headers

    def _url(self, path: str) -> str:
        base = (self.cfg.base_url or "").strip().rstrip("/")
        if not base:
            raise LLMError("Base URL 不能为空")
        # 已填完整 chat/completions
        if base.endswith("/chat/completions"):
            return base
        # 已含 /v1（含 /openai/v1 等）
        if base.endswith("/v1"):
            return f"{base}{path}"
        if base.endswith("/v1/"):
            return f"{base.rstrip('/')}{path}"
        # 中转只给域名时补 /v1
        if path.startswith("/chat"):
            return f"{base}/v1{path}"
        return f"{base}{path}"

    async def chat(self, messages: list[dict[str, str]], temperature: float = 0.3) -> str:
        if not self.cfg.api_key:
            raise LLMError("尚未配置 API Key，请先在「设置」中填写")
        if not self.cfg.model:
            raise LLMError("尚未配置模型名")
        url = self._url("/chat/completions")
        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": temperature,
        }
        try:
            async with httpx.AsyncClient(timeout=self.cfg.timeout_seconds) as client:
                resp = await client.post(url, headers=self._headers(), json=payload)
        except httpx.HTTPError as exc:
            raise LLMError(f"无法连接大模型接口：{exc}") from exc
        if resp.status_code >= 400:
            body = resp.text[:500]
            raise LLMError(f"大模型接口返回 {resp.status_code}：{body}")
        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise LLMError("大模型返回的不是 JSON") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"大模型响应结构异常：{data}") from exc
        if content is None:
            return ""
        if isinstance(content, list):
            # 部分兼容接口返回 content parts
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("text"):
                    parts.append(str(part["text"]))
                elif isinstance(part, str):
                    parts.append(part)
            return "".join(parts)
        return str(content)

    async def test(self) -> LLMTestResponse:
        try:
            content = await self.chat(
                [
                    {"role": "system", "content": "你是连通性测试助手，只回复：OK"},
                    {"role": "user", "content": "ping"},
                ],
                temperature=0,
            )
            return LLMTestResponse(
                ok=True,
                message="连接成功",
                model=self.cfg.model,
                detail=content[:200],
            )
        except LLMError as exc:
            return LLMTestResponse(ok=False, message=str(exc), model=self.cfg.model)
        except Exception as exc:  # noqa: BLE001
            return LLMTestResponse(ok=False, message=f"未知错误：{exc}", model=self.cfg.model)


MAGNET_RE = re.compile(r"magnet:\?xt=urn:btih:[A-Za-z0-9]{32,40}[^\s\"'<>]*", re.I)
URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
# 使用边界，避免 HDR/UHD/Blu-ray 等误判为 720p
QUALITY_PATTERNS = [
    (r"(?<![a-z0-9])(2160p|4k|uhd)(?![a-z0-9])", "2160p", "4K"),
    (r"(?<![a-z0-9])(1080p|fhd)(?![a-z0-9])", "1080p", "1080p"),
    (r"(?<![a-z0-9])(720p)(?![a-z0-9])", "720p", "720p"),
    (r"(?<![a-z0-9])(480p)(?![a-z0-9])", "480p", "480p"),
]


def detect_quality(text: str) -> tuple[str, str]:
    low = (text or "").lower()
    for pattern, resolution, quality in QUALITY_PATTERNS:
        if re.search(pattern, low, re.I):
            return resolution, quality
    return "", "未知"


def _stable_id(prefix: str, url: str) -> str:
    digest = hashlib.md5(url.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def _classify_url(url: str) -> str:
    low = (url or "").strip().lower()
    if low.startswith("magnet:"):
        return "magnet"
    path = urlparse(low).path if low.startswith("http") else low
    if path.endswith(".torrent") or ".torrent?" in low:
        return "torrent"
    if low.startswith("http://") or low.startswith("https://"):
        return "http"
    return "unknown"


def _extract_json_block(text: str) -> Any:
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


def _scan_raw_links(content: str, provider_name: str, seen: set[str]) -> list[SourceItem]:
    results: list[SourceItem] = []
    for match in MAGNET_RE.findall(content or ""):
        url = match.strip()
        if not url or url in seen:
            continue
        seen.add(url)
        resolution, quality = detect_quality(url)
        results.append(
            SourceItem(
                id=_stable_id("llm-raw", url),
                title=f"模型提及的磁力链接 {len(results)+1}",
                quality=quality,
                resolution=resolution,
                source=provider_name,
                url=url,
                url_type="magnet",
                note="从大模型回复中提取，请自行确认是否可用",
            )
        )
    for match in URL_RE.findall(content or ""):
        url = match.rstrip(").,;]")
        low = url.lower()
        if not url or url in seen:
            continue
        if "api." in low or "openai" in low or "localhost" in low or "127.0.0.1" in low:
            continue
        if not any(x in low for x in (".torrent", "magnet", "download")):
            continue
        seen.add(url)
        resolution, quality = detect_quality(url)
        results.append(
            SourceItem(
                id=_stable_id("llm-url", url),
                title=f"模型提及的链接 {len(results)+1}",
                quality=quality,
                resolution=resolution,
                source=provider_name,
                url=url,
                url_type="torrent" if low.endswith(".torrent") else "http",
                note="从大模型回复中提取，请自行确认是否可用",
            )
        )
    return results


def parse_llm_sources(content: str, provider_name: str = "大模型检索") -> list[SourceItem]:
    content = content or ""
    data = _extract_json_block(content)
    items: list[Any] = []
    if isinstance(data, dict):
        items = data.get("items") or data.get("sources") or data.get("results") or []
        if not isinstance(items, list):
            items = []
    elif isinstance(data, list):
        items = data

    results: list[SourceItem] = []
    seen: set[str] = set()
    for idx, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or raw.get("magnet") or raw.get("link") or "").strip()
        title = str(raw.get("title") or raw.get("name") or url or f"结果{idx+1}").strip()
        if not url:
            continue
        if url in seen:
            continue
        seen.add(url)
        url_type = _classify_url(url)  # type: ignore[arg-type]
        if url_type == "unknown":
            url_type = "http" if url.lower().startswith("http") else "unknown"
        resolution, quality = detect_quality(f"{title} {url} {raw.get('quality','')}")
        if raw.get("quality"):
            quality = str(raw.get("quality"))
        if raw.get("resolution"):
            resolution = str(raw.get("resolution"))
        try:
            seeds_val = int(raw["seeds"]) if raw.get("seeds") is not None else None
        except (TypeError, ValueError):
            seeds_val = None
        try:
            peers_val = int(raw["peers"]) if raw.get("peers") is not None else None
        except (TypeError, ValueError):
            peers_val = None
        results.append(
            SourceItem(
                id=_stable_id("llm", url),
                title=title[:200],
                quality=quality,
                resolution=resolution,
                size=str(raw.get("size") or ""),
                seeds=seeds_val,
                peers=peers_val,
                source=provider_name,
                url=url,
                url_type=url_type,  # type: ignore[arg-type]
                note=str(raw.get("note") or raw.get("comment") or ""),
                raw=raw,
            )
        )

    if not results:
        results.extend(_scan_raw_links(content, provider_name, seen))
    return results


async def llm_find_sources(
    client: LLMClient,
    query: str,
    year: int | None = None,
    quality: str | None = None,
) -> tuple[list[SourceItem], list[str]]:
    """用用户配置的大模型整理/检索候选片源。

    模型可能幻觉出不可用链接，结果仅作候选；下载仍走真实下载器。
    """
    warnings: list[str] = []
    if not client.cfg.api_key:
        return [], ["未配置大模型 API Key，已跳过「大模型检索」"]

    hint = query if not year else f"{query} {year}"
    if quality:
        hint += f" 希望{quality}"
    system = (
        "你是影视资源检索助手。用户会提供电影/剧集名称。"
        "请尽量给出不同清晰度的可下载片源候选（磁力链接、种子或直链）。"
        "只输出 JSON 数组，不要其它说明。每项字段："
        "title, url, quality, resolution, size, seeds, note。"
        "若无法确认真实链接，url 可为空字符串；不要编造无法使用的 btih。"
        "优先输出你较有把握、格式完整的 magnet 或 http 链接。"
    )
    user = f"检索：{hint}\n请返回 JSON 数组。"
    try:
        content = await client.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
        )
    except LLMError as exc:
        return [], [str(exc)]

    try:
        items = parse_llm_sources(content)
    except Exception as exc:  # noqa: BLE001
        return [], [f"解析大模型结果失败：{exc}"]

    if not items:
        warnings.append(
            "大模型已调用，但未解析出可用候选链接。可配置「自定义索引 API」，或在下载页手动粘贴磁力/直链。"
        )
    else:
        warnings.append("大模型结果仅作候选，链接有效性以实际下载为准。")
    return items, warnings
