#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""准备随包二进制（vendor/<platform>/）：aria2c、7-Zip。

用途：CI（windows-latest）构建前拉取依赖二进制；也支持本地预取检查。
所有 URL 都是官方发布地址，不镜像不可信来源。

用法：
    python scripts/fetch_vendor.py                     # 按当前平台
    python scripts/fetch_vendor.py --platform win64    # 指定平台（可在 Linux 上预取 Windows 版本）
    python scripts/fetch_vendor.py --dir vendor --force
"""
from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 固定版本，避免上游更新导致构建漂移
ARIA2_VERSION = "1.37.0"
ARIA2_URL = (
    f"https://github.com/aria2/aria2/releases/download/release-{ARIA2_VERSION}/"
    f"aria2-{ARIA2_VERSION}-win-64bit-build1.zip"
)
SEVENZIP_VERSION = "2500"  # 7-Zip 25.00
SEVENZIP_URL = f"https://www.7-zip.org/a/7z{SEVENZIP_VERSION}-x64.exe"

# 7-Zip 安装包解开后需要保留的文件（7z.exe + 7z.dll 才能读 rar）
SEVENZIP_KEEP = ("7z.exe", "7z.dll", "License.txt", "readme.txt", "History.txt")


def download(url: str, dest: Path, force: bool = False) -> Path:
    if dest.exists() and not force:
        print(f"  已存在，跳过：{dest.name}（{dest.stat().st_size} B）")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  下载：{url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as resp, tmp.open("wb") as f:  # noqa: S310
        shutil.copyfileobj(resp, f)
    tmp.replace(dest)
    print(f"  → {dest}（{dest.stat().st_size} B）")
    return dest


def _seven_zip_binary() -> str | None:
    """找一个能解压 7-Zip 安装包的 7z 可执行文件（本机 7z / vendor 里的）。"""
    from app.runtime import seven_zip_binary

    return seven_zip_binary()


def fetch_aria2_win(out_dir: Path, force: bool = False) -> list[str]:
    target = out_dir / "aria2c.exe"
    if target.exists() and not force:
        print(f"  aria2c.exe 已存在：{target}（{target.stat().st_size} B）")
        return [str(target)]
    zip_path = out_dir / "_aria2.zip"
    download(ARIA2_URL, zip_path, force=True)
    with zipfile.ZipFile(zip_path) as z:
        names = [n for n in z.namelist() if n.lower().endswith("aria2c.exe")]
        if not names:
            raise RuntimeError("压缩包里没有 aria2c.exe")
        with z.open(names[0]) as src, target.open("wb") as f:
            shutil.copyfileobj(src, f)
    zip_path.unlink(missing_ok=True)
    print(f"  → {target}（{target.stat().st_size} B）")
    return [str(target)]


def fetch_sevenzip_win(out_dir: Path, force: bool = False) -> list[str]:
    """从官方安装包中提取 7z.exe + 7z.dll（含 rar 支持）。"""
    if (out_dir / "7z.exe").exists() and not force:
        print(f"  7z.exe 已存在：{out_dir / '7z.exe'}")
        return [str(out_dir / p) for p in SEVENZIP_KEEP if (out_dir / p).exists()]
    tool = _seven_zip_binary()
    if not tool:
        raise RuntimeError("本机找不到 7z/7zz，无法解包 7-Zip 安装程序（CI 的 windows-latest 自带 7-Zip）")
    installer = out_dir / f"_7z{SEVENZIP_VERSION}-x64.exe"
    download(SEVENZIP_URL, installer, force=True)
    tmp = out_dir / "_7z_extract"
    tmp.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(  # noqa: S603
        [tool, "x", "-y", f"-o{tmp}", str(installer)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"解包 7-Zip 失败：{(proc.stdout or '')[-400:]}{(proc.stderr or '')[-400:]}")
    found: list[str] = []
    for name in SEVENZIP_KEEP:
        for cand in list(tmp.rglob(name)):
            shutil.copy2(cand, out_dir / name)
            found.append(str(out_dir / name))
            break
    shutil.rmtree(tmp, ignore_errors=True)
    installer.unlink(missing_ok=True)
    if not (out_dir / "7z.exe").exists():
        raise RuntimeError("解包后没找到 7z.exe")
    print(f"  → {out_dir / '7z.exe'}（{(out_dir / '7z.exe').stat().st_size} B）"
          f" / 7z.dll（{(out_dir / '7z.dll').stat().st_size if (out_dir / '7z.dll').exists() else 0} B）")
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description="准备随包二进制")
    ap.add_argument("--platform", default="auto", choices=["auto", "win64", "linux64", "macos"])
    ap.add_argument("--dir", default=str(ROOT / "vendor"))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    platform = args.platform
    if platform == "auto":
        if sys.platform.startswith("win"):
            platform = "win64"
        elif sys.platform == "darwin":
            platform = "macos"
        else:
            platform = "linux64"

    out_dir = Path(args.dir) / platform
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[vendor] 目标目录：{out_dir}")

    if platform == "win64":
        fetch_aria2_win(out_dir, args.force)
        fetch_sevenzip_win(out_dir, args.force)
    else:
        # Linux/macOS 直接用系统包管理器安装的二进制，不随包分发
        from app.runtime import seven_zip_binary, aria2_binary

        print(f"  {platform} 不需要随包二进制；本机 aria2c={aria2_binary()} 7z={seven_zip_binary()}")
    print("[vendor] 完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
