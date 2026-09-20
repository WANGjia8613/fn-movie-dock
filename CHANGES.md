# 改动清单（上游 v0.1.1 → 本版 0.1.2）

上游：<https://github.com/WANGjia8613/fn-movie-dock>（v0.1.1，无 LICENSE 文件）
本版：**仅供个人自用**，请勿公开分发（上游声明"个人学习与自用"，无开源许可证）。

改动基线在 git 里：`upstream: fn-movie-dock v0.1.1 (WANGjia8613) baseline`。

---

## 1. 检索源：补上"真实可用"的那条路

| 文件 | 改动 |
|------|------|
| `app/search/qbittorrent.py` | **新增**：复用 qBittorrent `/api/v2/search` 的插件生态（yts/bt4g/kickass…），结果转成候选；自动停止/删除搜索任务；登录失败降级匿名；插件缺失/超时给出可操作提示 |
| `app/search/__init__.py` | 注册新 provider + `provider_type_labels()` |
| `app/config.py` | `ProviderConfig` 新增 `options: dict`（provider 专属参数）；`SearchConfig` 新增 `sort_by_score` |
| `app/ranking.py` | **新增**：HDR/DoVi/REMUX/Atmos… 标签识别 + 候选评分/排序/最优挑选 |

## 2. 字幕（上游完全没有）

| 文件 | 改动 |
|------|------|
| `app/subtitle/subhd.py` | **新增**：SubHD 客户端（搜索影片→条目→prepare→down→下载归档）；多影片候选合并；电影/年份优先排序；条目解析补上格式与语言 |
| `app/subtitle/extract.py` | **新增**：zip（含 GBK 文件名还原）→ 7z/7zz/bsdtar/unrar/unar 兜底解压；字幕文本编码规整为 UTF-8 |
| `app/subtitle/manager.py` | **新增**：关键词候选（片名/年份/英文名/发布组/extra_keywords）、条目打分、最多试 3 条、挑最佳字幕文件、按 `{video}.zh.ass` 改名落盘；英文关键词防配错（同系列短片/别名跳过）；可选"大模型补中文译名" |
| `app/config.py` | 新增 `SubtitleConfig`（enabled/extra_keywords/prefer_bilingual/name_template/extract_tools/llm_translate/max_movies…） |

## 3. 整理增强

| 文件 | 改动 |
|------|------|
| `app/organizer/organize.py` | 新增 `parse_episode()`（S01E02 / s1e2 / 1x03 / 第5集 / E07）与 `episode_label()`；剧集模板；`library_root`（可直接落已有电影库）；`movies_subdir`；修正只认 `.mkv` 的问题；模板里的 `/` 逐段 sanitize（否则剧集目录层级会被吃掉） |
| `app/organizer/__init__.py` | 导出新函数 |

## 4. 下载与任务健壮性

| 文件 | 改动 |
|------|------|
| `app/downloader/manager.py` | 每任务独立子目录 `incoming/<task_id>/`；任务状态落盘 `state_dir()/tasks.json`（重启不丢，丢失的下载标记 interrupted）；整理改用 aria2 回报的准确文件列表；下载完成 → 整理 → 字幕 的收尾链（任一步失败都不判任务失败）；aria2 参数增强（seed-time=0/seed-ratio=0、DHT、LPD、bt-tracker、extra_options）；`retry_subtitle()` |
| `app/config.py` | `PathsConfig.state_dir`；`DownloaderConfig.per_task_dir / extra_options / bt_trackers`；`state_dir()` 多级兜底 |

## 5. 前端

| 文件 | 改动 |
|------|------|
| `app/static/index.html` | 检索区加「一键最优」+「完成后自动匹配中文字幕」；设置页新增剧集模板、资料库目录、字幕区块；下载弹窗加字幕开关 |
| `app/static/app.js` | 候选卡片展示评分/特性标签/推荐标记；任务卡片展示剧集号、字幕状态与"重试字幕"；配置读写覆盖新字段；qBittorrent provider 的账号/插件表单 |
| `app/static/style.css` | 新增推荐/特性标签/字幕状态等样式 |

## 6. 部署与文档

| 文件 | 改动 |
|------|------|
| `Dockerfile` | 增加 `p7zip-full`、`libarchive-tools`（rar/7z 字幕包解压） |
| `docker/entrypoint.sh` | **修掉原版 `--rpc-secret` 写坏的 bug**；aria2 参数补强；支持 `BT_TRACKERS` |
| `docker-compose.yml` | 新增 `STATE_DIR`、`BT_TRACKERS` 说明；可选挂载已有电影库到 `/library` |
| `config.example.yaml` | 覆盖全部新增配置项 |
| `README.md` | 新增第 12 章「本改进版新增能力」 |
| `scripts/unit_checks.py` | **新增** 31 项回归（剧集解析/整理/评分/qB 映射/字幕打分/解压/持久化/配置往返） |

---

## 验证结果（本地，无容器）

环境：venv（pypi 直连），Python 3.11。

```
scripts/review_checks.py   TOTAL=22 FAIL=0
scripts/unit_checks.py     TOTAL=31 FAIL=0
scripts/smoke_local.py     真实起服务跑通 health/search/config/downloader/organize/download/tasks
```

真实链路验证（联网，SubHD）：

- `WALL-E.2008.2160p.UHD.BDRemux.HDR.DoVi.P8.Hybrid.by.DVT.mkv`
  → 无中文关键词时**安全失败**（拒绝用《电焊工波力》的 1080p 字幕冒充）
  → 配置 `extra_keywords: [机器人总动员]` 时**成功**，落地
  `WALL-E.2008.2160p.UHD.BDRemux.HDR.DoVi.P8.Hybrid.by.DVT.zh.ass`（简英双语 ASS，4K 适配版）

> 说明：aria2 与 Docker 未在本机跑通（OpenClaw 进程不在 docker 组 / 无本机 aria2 服务），
> 因此"磁力实际下载"这一步需要在飞牛上部署后验证；上面所有逻辑层与字幕真实链路均已实测。

## 已知限制 / 后续可做

- 剧集整理按"单个视频文件"处理，多集种子（整季包）只会整理主文件，其余留在 incoming
- 字幕默认只挑 1 个文件落盘（简繁/多轨不分别落地）
- `/api/subtitle/candidates` 只是列出条目，未做"手动指定 sid 下载"的 UI
- 未做访问鉴权（沿用上游行为）：**不要把这个 8090 直接暴露公网**

---

## 0.2.0（Windows 本地版）

目标：**完全不依赖 Linux/NAS**，在 Windows 上本地完成「搜索 → 下载 → 整理 → 配字幕」。

### 新增：跨平台运行时层 `app/runtime.py`
- 外部工具探测统一化：**随包 vendor → PATH → 常见安装路径**（Windows 自动找 `C:\Program Files\7-Zip\7z.exe`，兼容 `7z/7zz/7za`、`unrar/UnRAR`、`bsdtar`、`unar`）
- 配置/状态目录按平台落位：Windows `%APPDATA%\MovieDock`，Linux `~/.config/movie-dock`，可用 `MOVIE_DOCK_HOME` 覆盖
- aria2 进程托管：统一参数（`seed-time=0` 不做种、RPC 仅回环、DHT/LPD、tracker），拉起后轮询 RPC 就绪
- UTF-8 控制台、环境自检信息、浏览器兜底

### 新增：桌面启动器 `app/desktop/`
- `MovieDock.exe`：启动即用 —— 准备配置 → 拉起 aria2c → 起本地服务（127.0.0.1，随机避让端口）→ 打开 **WebView2 原生窗口**；没有 WebView2/pywebview 时自动退回默认浏览器
- `MovieDockCLI.exe`：`--headless`（只跑服务）、`--selftest`（启动→自检→退出，CI 用）、`--browser`、`--no-tray`、`--download-dir`
- 系统托盘：打开界面 / 打开下载目录 / 复制地址 / 退出
- 单实例：已在运行则直接打开已有实例，不重复起进程
- 退出清理 aria2 子进程；`aria2.auto_start` 配置项区分桌面模式（True）与 Docker 模式（False，由 entrypoint 拉起）

### 新增：打包与 CI
- `packaging/moviedock.spec`：PyInstaller onedir，一次产出 GUI + CLI 两个 exe，附带 `app/static`、`config.example.yaml`、`vendor/win64/*`，含自绘图标 `packaging/moviedock.ico`
- `scripts/fetch_vendor.py`：拉取官方 `aria2c.exe`（1.37.0）与 `7z.exe/7z.dll`（7-Zip 25.00，**含 rar 支持**）到 `vendor/win64/`
- `scripts/ci_download_test.py`：端到端链路测试（本地 HTTP 文件 → aria2 下载 → 整理 → 校验字节/命名），Windows 与 Linux 都能跑
- `scripts/desktop_checks.py`：29 项桌面/跨平台层自检
- `.github/workflows/ci.yml`（ubuntu）与 `.github/workflows/windows-build.yml`（windows-latest：单测 → 自检 → 端到端下载 → PyInstaller 打包 → exe 冒烟 → 产物/Release）

### 改动
- `subtitle/extract.py` 的工具探测改走 `runtime.find_tool`（Windows 上自动用随包 `7z.exe`，支持 rar）
- `config.py`：配置文件路径按平台落位；`downloader.aria2` 新增 `auto_start` / `binary` / `port`
- Docker 行为不变（`auto_start=False`，保持由 entrypoint 拉起 aria2）
