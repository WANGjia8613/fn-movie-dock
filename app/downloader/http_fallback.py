from __future__ import annotations

import re
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

import httpx

ProgressCb = Callable[[int, int, float], None]


def _filename_from_url(url: str, preferred: str = "") -> str:
    path = unquote(urlparse(url).path)
    name = Path(path).name
    if name:
        return name
    if preferred:
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", preferred).strip() or "download.bin"
        return safe
    return "download.bin"


async def download_http_to(
    url: str,
    dest_dir: Path,
    preferred_name: str = "",
    on_progress: ProgressCb | None = None,
) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = _filename_from_url(url, preferred_name)
    dest = dest_dir / name
    if dest.exists():
        stem = dest.stem
        ext = dest.suffix
        i = 1
        while dest.exists():
            dest = dest_dir / f"{stem}.{i}{ext}"
            i += 1

    done = 0
    total = 0
    last = 0.0
    last_t = 0.0
    import time

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=300.0), follow_redirects=True) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            cl = resp.headers.get("content-length")
            if cl and cl.isdigit():
                total = int(cl)
            start = time.time()
            with dest.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=1024 * 256):
                    f.write(chunk)
                    done += len(chunk)
                    now = time.time()
                    elapsed = now - start
                    speed = done / elapsed if elapsed > 0 else 0
                    if on_progress and (now - last_t > 0.5 or (total and done >= total)):
                        on_progress(done, total, speed)
                        last_t = now
                        last = speed
    if on_progress:
        on_progress(done, total or done, last)
    return dest
