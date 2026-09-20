"""字幕压缩包解压 + 文本编码规整。

SubHD 的下载包可能是 zip，也可能是 rar（踩过坑：rar 用 zipfile 打开会抛
BadZipFile），所以这里按 zip → 7z → bsdtar → unrar → unar 依次兜底。
工具探测统一走 app.runtime（随包 vendor 目录 → PATH → 常见安装路径，
Windows 上会自动找 C:\\Program Files\\7-Zip\\7z.exe 或随包 7z.exe）。
"""
from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

from ..runtime import find_tool

SUB_EXTS = (".ass", ".srt", ".ssa", ".sup", ".sub", ".idx", ".vtt")


def _tool_path(tool: str) -> str | None:
    return find_tool(tool)


def _fix_zip_name(info: zipfile.ZipInfo) -> str:
    """zip 里非 UTF-8 标记的中文文件名会变成乱码，这里尝试按 GBK 还原。"""
    name = info.filename
    if info.flag_bits & 0x800:
        return name
    try:
        return name.encode("cp437").decode("gbk")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def _extract_zip(archive: Path, out_dir: Path) -> bool:
    if not zipfile.is_zipfile(archive):
        return False
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            fixed = _fix_zip_name(info)
            target = out_dir / fixed
            # 防止路径穿越
            try:
                target.resolve().relative_to(out_dir.resolve())
            except ValueError:
                continue
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    return True


def _run_tool(tool: str, archive: Path, out_dir: Path) -> tuple[bool, str]:
    name = Path(tool).name.lower().removesuffix(".exe")
    if name in ("7z", "7zz", "7za"):
        cmd = [tool, "x", "-y", f"-o{out_dir}", str(archive)]
    elif name in ("bsdtar", "tar"):
        cmd = [tool, "-xf", str(archive), "-C", str(out_dir)]
    elif name in ("unrar", "unrar-free"):
        cmd = [tool, "x", "-y", str(archive), str(out_dir) + ("/" if not str(out_dir).endswith("/") else "")]
    elif name == "unar":
        cmd = [tool, "-o", str(out_dir), str(archive)]
    else:
        return False, f"不支持的工具：{tool}"
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    ok = proc.returncode == 0
    return ok, (proc.stdout or "") + (proc.stderr or "")


def extract_archive(archive: Path, out_dir: Path, tools: list[str] | None = None) -> list[Path]:
    """解压归档，返回所有落盘文件（递归）。失败抛 RuntimeError。"""
    archive = Path(archive)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not archive.exists():
        raise RuntimeError(f"归档不存在：{archive}")

    if _extract_zip(archive, out_dir):
        return sorted(p for p in out_dir.rglob("*") if p.is_file())

    errors: list[str] = []
    for tool in (tools or ["7z", "7zz", "bsdtar", "unrar", "unar"]):
        path = _tool_path(tool)
        if not path:
            continue
        ok, output = _run_tool(path, archive, out_dir)
        files = sorted(p for p in out_dir.rglob("*") if p.is_file())
        if ok and files:
            return files
        errors.append(f"{tool}: {output.strip()[:200] or '无输出'}")
    raise RuntimeError(
        "解压失败（非 zip 且外部工具不可用）：" + ("；".join(errors) if errors else "未找到 7z/bsdtar/unrar")
    )


def find_subtitle_files(root: Path) -> list[Path]:
    root = Path(root)
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in SUB_EXTS and not p.name.startswith(".")
    )


def normalize_text_encoding(path: Path) -> str:
    """把非 UTF-8 的字幕文本转成 UTF-8，返回使用的编码名。"""
    if path.suffix.lower() not in (".ass", ".srt", ".ssa", ".vtt"):
        return ""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8"):
        try:
            text = raw.decode(enc)
            if enc != "utf-8":
                path.write_text(text, encoding="utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            continue
    for enc in ("gb18030", "big5", "cp1252"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        path.write_text(text, encoding="utf-8")
        return enc
    return ""
