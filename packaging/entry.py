#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包入口（PyInstaller）。

PyInstaller 会把入口脚本当顶层 __main__ 执行，所以入口必须用绝对导入
（不能直接拿 app/desktop/launcher.py 当入口，那里是相对导入）。
"""
from __future__ import annotations

import multiprocessing
import os
import sys

# 源码模式下保证仓库根在 sys.path（打包后由 PyInstaller 处理）
if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.desktop.launcher import main  # noqa: E402

if __name__ == "__main__":
    # 冻结环境下若将来用到多进程（PyInstaller 需要）
    multiprocessing.freeze_support()
    sys.exit(main())
