# 第三方组件声明（Third-Party Notices）

片坞 Movie Dock 本体代码以 **MIT** 许可证发布（见 [LICENSE](LICENSE)）。
但发布包（`MovieDock-win64.zip`）中**随附了第三方可执行文件**，它们各有自己的许可证，
使用与再分发这些文件时需遵守相应条款。

## 1. aria2（`vendor/win64/aria2c.exe`）

- 项目：aria2 — <https://aria2.github.io/> / <https://github.com/aria2/aria2>
- 版本：1.37.0（windows 64-bit 官方构建）
- 许可证：**GNU GPL v2 或更高版本**（GPL-2.0-or-later），另含 OpenSSL 例外条款
- 说明：本文档随包分发时需附带其 `COPYING`（构建流程会自动放入 `aria2-COPYING.txt`）。
  如需 aria2 源码，见上游发布页；本项目仅以未修改的官方二进制形式随附。

## 2. 7-Zip（`vendor/win64/7z.exe`、`7z.dll`）

- 项目：7-Zip — <https://www.7-zip.org/>
- 版本：25.00（官方 x64 安装包中提取）
- 许可证：**GNU LGPL v2.1+**，其中 RAR 支持部分受 **unRAR license restriction** 约束：
  - 不得用其还原/重建 RAR 压缩算法用于创建 RAR 兼容压缩器
  - 随包会附上官方 `License.txt`（文件名 `7-Zip-License.txt`）
- 用途：仅用于解压用户下载到的字幕归档（zip/rar/7z）。

## 3. Python 运行时的依赖

随包已把 Python 及其依赖（FastAPI / uvicorn / httpx / pydantic / PyYAML 等）一起打包。
这些组件均为 MIT / BSD / Apache-2.0 等宽松许可证，详见各自项目主页；
其中 **PyInstaller**（打包工具，GPL with bootloader exception）不改变本项目代码的许可证。

## 4. 免责声明

本项目只是一个下载/整理工具，**不提供、不托管任何影视资源**。
请遵守当地法律法规与内容版权，仅下载你有权获取与存储的内容；使用后果由使用者自行承担。
