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

---

## 0.2.1

修掉实测暴露的问题：**窗口先打开、本地服务还没就绪 → 显示「127.0.0.1 拒绝连接」**（首次启动被杀软扫描 1160 个文件时很容易触发）。

- 新增启动页 `app/static/splash.html`：服务没就绪时先显示「片坞正在启动…」，每秒轮询 `/api/health`，就绪自动跳转；90 秒仍未就绪则给出可操作错误（端口占用/杀软拦截/运行 selftest）
- `window.py` 加守候线程：服务就绪后主动把窗口从启动页切到应用页（双保险）；运行中掉线会重新检测
- 启动器：`--startup-timeout`（默认 60s）；`ServerThread` 捕获并记录启动异常（含 traceback）
- **GUI 版日志落盘**：无控制台时把 stdout/stderr 重定向到 `%APPDATA%\MovieDock\logs\app.log`
- desktop_checks 扩到 37 项（启动页/日志/超时路径）

---

## 0.2.2

修实测反馈：**「在候选结果区空白处双击粘贴磁力」根本点不到**（未搜索时结果区是空的、高度 0，入口等于不存在）。

- 搜索栏新增醒目按钮 **「粘贴磁力/直链」**；空态结果区里也放了一个同样的按钮（双入口）
- 手工粘贴时下载链接输入框**可编辑**（候选来源仍只读）；粘贴后**自动从磁力 dn= 解析片名/年份**填好
- `parse_title_year` 重写为"遇压制标记即截断"策略，命名更干净：
  - `WALL-E.2008.2160p.UHD.BDRemux...` → `WALL-E`（原来是 `WALL-E 2008`）
  - `Spider-Man.No.Way.Home.2021.2160p.WEB-DL...` → `Spider-Man No Way Home`
  - 顺手支持点号分词、体积标记（`1.20GB`）、磁力 dn= 推断
- desktop_checks 增至 41 项（含前端入口可见性检查）；unit_checks 增至 39 项

---

## 0.3.0

**内置直连索引源**：Windows 本地模式不再依赖 qBittorrent，点「搜索」就能用。

- `app/search/builtin.py`
  - **TPB / apibay**（海盗湾 JSON API）：境内直连实测可用（200，1.3s），电影/剧集，带做种数
  - **YTS**（JSON API，镜像 yts.mx/rs/lt/am）：小体积、做种多；需代理
  - **DMHY 动漫花园**（RSS，镜像 share.dmhy.org/dmhy.org）：中文标题动画/剧集；需代理
  - 每个源按镜像顺序尝试，任一成功即用；结果按 url 去重；`sources` 可配
- **全局代理开关** `network.proxy`：内置索引源 / 字幕站 / 自定义索引共用（Clash 混合端口即可），
  设置页新增「网络（代理）」输入框；aria2 的下载代理用 `downloader.extra_options: {"all-proxy": ...}`
- **候选评分加入关键词相关度**：修复"搜 wall-e 结果《华尔街之狼》排第一"
  - 词元命中 + 整串（去分隔符）命中加权重：`wall-e`→`walle` 能区分 WALL-E 与 Wall Street
  - 实测 `wall-e`：Criterion 4K REMUX 110 分 > AViATOR 4K 92 > YIFY 1080p(521做种) 86.5 > 华尔街之狼 90.7 降到其后
- 默认检索源改为 `builtin`（qBittorrent 保留但默认关闭，NAS 上可自行开启）
- 版本 0.2.2 → 0.3.0

---

## 0.3.1

修两个实测暴露的问题（用户升级到 0.3.0 后搜索仍为空）：

1. **老配置不迁移 → 新源根本没加载**
   用户在 0.2.x 生成的 `%APPDATA%\MovieDock\config.yaml` 里没有 `builtin` 条目，
   升级后应用仍只用旧的 qBittorrent 源（他机器上没有 qB）→ 搜索永远 0 条。
   现在 `load_config` 会做**配置迁移**：缺 `builtin` 就补上并默认启用，并把结果写回配置文件。
2. **中文关键词在英文索引站上无效**
   TPB/YTS 对中文关键词会返回一堆无关内容（实测搜"机器人总动员"返回 100 条 Avira 破解）。
   现在：
   - **相关度过滤**：标题与关键词无关的结果直接剔除；若全被过滤，返回明确提示而不是垃圾列表
   - 中文查询且全无相关结果时，提示三条可行路径（用英文名 / 填代理启用 DMHY 中文源 / 配大模型自动翻译）
   - **大模型辅助翻译**：配了 API Key 时，中文片名自动翻成英文名后去搜

实测（模拟老配置）：迁移后 `builtin` 已启用并落盘；搜 `wall-e` 出 63 条真实候选（相关度排序正确）；搜中文名返回 0 条 + 可操作提示。

测试：unit_checks 61 项（含迁移/相关度过滤/翻译辅助）

---

## 0.4.0

新增**下载暂停/继续**与**下载历史删除**，并把「演示数据」标注清楚。

- **暂停 / 继续**
  - 任务卡新增「暂停」「继续」按钮；接口 `POST /api/tasks/{id}/pause|resume`
  - 走 aria2 的 pause/unpause；暂停后强制清零速度（aria2 会回报上一刻的速度，界面会显示"暂停中 448KB/s"这种假象）
  - **HTTP 直链**任务继续时改为「重新添加 + `continue=true` 断点续传」：
    实测 aria2 对 HTTP 直链的 unpause 有已知 bug（报 `No URI available.` 并变 error，且要等重试耗尽才报），
    绕开后正常续传（真机验证：暂停在 5.7% → 继续 → 下载完成 → 字节数一致）
- **删除历史**
  - 任务卡「删除」= 只删记录（文件保留）；再确认一次才「连文件一起删」
  - 删除文件**只允许配置目录内**（下载目录 / 资料库目录），越界路径一律不动；删视频时连带同名 `.zh.ass` 等字幕
  - 顶部新增「清空已完成」（同样两段确认）；接口 `DELETE /api/tasks/{id}?delete_files=`、`POST /api/tasks/clear`
- **演示数据**：设置页标注为「演示数据（调试用，假链接）」，并加说明（假链接不能真下载，正常使用保持关闭）
- 新增 `scripts/ci_ops_test.py`：真机链路测试（限速下载 → 暂停 → 继续 → 完成 → 删除记录 → 连文件删除），已接入两个 CI
- 版本 0.3.1 → 0.4.0
