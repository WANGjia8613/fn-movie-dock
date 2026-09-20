# 片坞 Movie Dock 使用说明

飞牛 fnOS（x86_64）上的一体化 Docker 应用：在**同一个中文网页**里完成

**输入片名 → 检索多清晰度候选 → 选择片源 → 应用内下载（磁力/种子/直链）→ 自动整理进电影文件夹 → 显示输出路径**。

> 个人 NAS 自用工具。请只下载你有权获取与存储的内容；使用后果由使用者自行承担。

---

> **本仓库为改进版（0.4.x）**：在原版基础上补上了「内置直连索引源 + 自动中文字幕 + 剧集整理 +
> 候选评分/一键最优 + 任务持久化 + Windows 本地版（WebView2 客户端）」等能力，
> 改动清单见 [CHANGES.md](CHANGES.md)。上游仓库：<https://github.com/WANGjia8613/fn-movie-dock>。
>
> **许可证：MIT**（见 [LICENSE](LICENSE)）—— 可自由使用、修改、再分发（保留版权声明即可）。
> 随包附带的第三方二进制（aria2c / 7-Zip）另有其许可证，见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。

## 目录

1. [功能一览](#1-功能一览)
2. [环境要求](#2-环境要求)
3. [飞牛部署（推荐）](#3-飞牛部署推荐)
4. [首次配置](#4-首次配置)
5. [日常使用](#5-日常使用)
6. [整理规则与路径说明](#6-整理规则与路径说明)
7. [检索源说明](#7-检索源说明)
8. [本地开发](#8-本地开发)
9. [配置参考](#9-配置参考)
10. [故障排查](#10-故障排查)
11. [项目结构](#11-项目结构)

---

## 1. 功能一览

| 功能 | 说明 |
|------|------|
| 中文界面 | 搜索、设置、任务、提示均为中文 |
| 大模型接入 | 自填 OpenAI 兼容 Base URL / API Key / 模型名，可一键测试 |
| 多源检索 | 演示数据、大模型检索、自定义 JSON 索引 API |
| 应用内下载 | 镜像内置 aria2，支持磁力、种子、HTTP 直链 |
| 自动整理 | `{片名} ({年份})/{片名} ({年份}) - {清晰度}.mkv` |
| 路径回显 | 任务完成后显示输出路径 |
| 一站式 | 不必在搜索工具、BT 客户端、文件管理器之间来回切换 |

---

## 2. 环境要求

| 项目 | 要求 |
|------|------|
| 系统 | 飞牛 fnOS（x86_64）或其它可跑 Docker 的 Linux NAS |
| 软件 | Docker + Docker Compose（飞牛应用中心启用 Docker） |
| 网络 | 能访问你配置的大模型接口；BT 下载需外网可达 |
| 浏览器 | Chrome / Edge / Safari 等现代浏览器 |

架构说明：当前交付以 **x86_64** 为准；ARM 设备需自行交叉构建镜像。

---

## 3. 飞牛部署（推荐）

### 3.1 创建目录

在飞牛文件管理或 SSH 中创建（路径可按实际情况改，改后同步 compose）：

```text
/vol1/apps/fn-movie-dock/config
/vol1/apps/fn-movie-dock/data
/vol1/media
```

说明：

| 宿主机路径 | 容器路径 | 用途 |
|------------|----------|------|
| `/vol1/apps/fn-movie-dock/config` | `/config` | 配置与 API Key（保密） |
| `/vol1/media` | `/downloads` | 下载临时目录 + 整理后的电影 |
| `/vol1/apps/fn-movie-dock/data` | `/data` | 预留状态目录 |

推荐把 `/downloads` 挂到 `/vol1/media`，这样整理结果落在：

```text
/vol1/media/movies/片名 (年份)/片名 (年份) - 清晰度.mkv
```

### 3.2 获取代码

**方式 A：从 GitHub 克隆（推荐）**

```bash
cd /vol1/apps
git clone https://github.com/<你的GitHub用户名>/fn-movie-dock.git
cd fn-movie-dock
```

**方式 B：本机打包上传**

将 `D:\fn-projects\movie-dock` 整个目录用 SMB/scp 上传到飞牛，例如 `/vol1/apps/fn-movie-dock-src`。

### 3.3 修改 compose 路径

编辑 `docker-compose.yml` 中的 `volumes`，使其与你的存储空间一致：

```yaml
volumes:
  - /vol1/apps/fn-movie-dock/config:/config
  - /vol1/media:/downloads
  - /vol1/apps/fn-movie-dock/data:/data
```

端口默认 `8090`，冲突时改为例如 `18090:8090`。

**不要**在 compose 里写 `LLM_API_KEY` 等环境变量，除非你希望以环境变量为准（其优先级高于界面保存的配置）。

### 3.4 构建并启动

```bash
cd /vol1/apps/fn-movie-dock
docker compose up -d --build
```

查看状态：

```bash
docker compose ps
docker logs -f movie-dock
```

健康检查通过后，日志中应能看到 Web 服务监听端口。

### 3.5 打开界面

浏览器访问：

```text
http://<飞牛内网IP>:8090
```

若无法访问，在飞牛系统设置中放行对应 TCP 端口。

---

## 4. 首次配置

1. 打开页面后，点右上角 **设置**
2. 在 **大模型** 区域填写：

| 字段 | 示例 |
|------|------|
| Base URL | `https://api.openai.com/v1` 或你的中转/自建地址 |
| API Key | `sk-...`（只保存在 NAS 的 `/config/config.yaml`） |
| 模型名 | `gpt-4o-mini`、`deepseek-chat` 等 |

3. 点 **测试连接**，显示「连接成功」后点 **保存设置**
4. 在 **检索源** 中：
   - 保持 **演示数据** 启用，便于先熟悉界面
   - 启用 **大模型检索**
   - 如有自定义索引，启用 **自定义索引** 并填写接口 URL
5. 确认 **整理规则**（文件夹/文件名模板、移动/复制/硬链接）
6. 页面底部可查看下载根目录是否为 `/downloads`

请求只会发往你填写的 Base URL；应用本身不代理、不上传 Key。

---

## 5. 日常使用

### 5.1 检索

1. 在顶部输入电影/剧集名称（可选年份、清晰度偏好）
2. 可勾选「下载完成后自动整理到电影文件夹」
3. 点 **搜索**
4. 查看候选列表：清晰度、体积、做种数、来源、链接类型

### 5.2 下载

1. 在候选中点 **选择并下载**
2. 在弹窗中确认：
   - 用于整理的片名、年份、清晰度
   - 下载链接（磁力 / 种子 / 直链）
   - 是否自动整理
3. 点 **开始下载**
4. 右侧 **下载任务** 查看进度；完成后卡片会显示 **输出路径**

### 5.3 手动粘贴链接

- 在检索结果区域 **双击**，可粘贴磁力/种子 URL/HTTP 直链
- 适合：已有磁力、大模型未给出链接、或使用外部索引时

### 5.4 与飞牛影视配合（可选）

整理完成后，将飞牛影视的媒体库文件夹指向：

```text
/vol1/media/movies
```

即可用飞牛自带刮削与播放；「找源 → 下载 → 落库」仍在片坞内完成。

---

## 6. 整理规则与路径说明

### 默认规则

```text
{download_root}/movies/{title} ({year})/{title} ({year}) - {quality}{ext}
```

示例（容器内）：

```text
/downloads/movies/沙丘2 (2024)/沙丘2 (2024) - 1080p.mkv
```

对应飞牛（按推荐挂载 `/vol1/media:/downloads`）：

```text
/vol1/media/movies/沙丘2 (2024)/沙丘2 (2024) - 1080p.mkv
```

### 模板占位符

| 占位符 | 含义 |
|--------|------|
| `{title}` | 片名 |
| `{year}` | 年份（缺失时用「未知年份」） |
| `{quality}` / `{resolution}` | 清晰度标签 |
| `{ext}` | 扩展名（不含点） |

### 整理方式

| 模式 | 行为 |
|------|------|
| move（默认） | 移动到电影目录 |
| copy | 复制，保留 incoming 中的文件 |
| hardlink | 硬链接（同分区省空间；失败则回退复制） |

在设置中修改模板后 **保存设置** 即生效；也可在每次下载弹窗里临时确认片名/年份。

---

## 7. 检索源说明

### 7.1 演示数据

内置固定候选，用于验证界面与任务流程。链接通常无法真实下载。

### 7.2 大模型检索

- 使用你配置的 OpenAI 兼容接口
- 适合：理解片名、整理结构化候选、解释差异
- **不保证**每次都能给出真实可用的磁力；结果仅作候选
- 未配置 API Key 时会自动跳过并提示

### 7.3 自定义索引 API

适合你自己维护的索引/元数据服务，接口约定：

**请求**

- GET：查询参数 `q`（或 `query`）、`year`、`quality`
- POST：JSON 提交相同字段

**响应**

JSON 数组，或 `{ "items": [...] }` / `{ "results": [...] }` / `{ "sources": [...] }`

每项字段（兼容多种命名）：

```json
{
  "title": "沙丘2 (2024) 1080p BluRay",
  "url": "magnet:?xt=urn:btih:...",
  "quality": "1080p",
  "resolution": "1080p",
  "size": "8.4GB",
  "seeds": 56,
  "note": "可选说明"
}
```

兼容字段：`name`、`magnet`、`link`、`comment` 等。

在 **设置 → 检索源 → 自定义索引** 中填写名称、URL、GET/POST，启用后保存。

---

## 8. 本地开发

仅在指定项目目录内操作，不污染系统目录。

```powershell
cd D:\fn-projects\movie-dock

# 使用环境自带 Python 创建项目内虚拟环境
& "C:\Users\31571\AppData\Local\Programs\Xiaomi MiMo\resources\runtimes\win32-x64\python\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8090
```

浏览器打开 `http://127.0.0.1:8090`。

本地注意：

- 未运行 aria2 时，HTTP 直链仍可下载；磁力/种子需 Docker 内引擎
- 本地下载目录默认在项目下 `downloads/`（可用环境变量 `DOWNLOAD_ROOT` 覆盖）
- 回归脚本：`python scripts/review_checks.py`
- 冒烟脚本：`python scripts/smoke_local.py`

**不要提交** `config.yaml`（可能含 Key）、`downloads/`、`.venv/`（已在 `.gitignore` 中排除）。公开仓库请只使用 `config.example.yaml`。

---

## 9. 配置参考

### 9.1 配置优先级

1. 环境变量（Docker Compose）
2. `/config/config.yaml`（界面「保存设置」写回这里）
3. 代码内默认值

若 compose 中设置了 `LLM_API_KEY` 等，**界面修改会被环境变量覆盖**；要完全用界面配置，请去掉 compose 中的相关 env。

### 9.2 常用环境变量

| 变量 | 含义 |
|------|------|
| `LLM_BASE_URL` | 大模型接口地址 |
| `LLM_API_KEY` | API Key |
| `LLM_MODEL` | 模型名 |
| `DOWNLOAD_ROOT` | 容器内下载根目录，默认 `/downloads` |
| `ARIA2_RPC_URL` | 默认 `http://127.0.0.1:6800/jsonrpc` |
| `ARIA2_RPC_SECRET` | aria2 RPC 密钥（可选） |
| `SERVER_PORT` | Web 端口，默认 `8090` |
| `MAX_CONCURRENT` | aria2 并发下载数 |

### 9.3 示例配置

见仓库内 [`config.example.yaml`](./config.example.yaml)。部署后复制为 `/config/config.yaml`。

---

## 10. 故障排查

| 现象 | 处理 |
|------|------|
| 打不开网页 | 检查容器是否运行、端口是否放行、IP:端口是否正确 |
| 搜索只有演示数据 | 设置中启用大模型检索或配置自定义索引 |
| 大模型测试失败 | 核对 Base URL（常需 `/v1`）、Key、模型名；用「测试连接」看报错 |
| 界面改了 Key 无效 | 检查 compose 是否写了 `LLM_API_KEY`（env 优先） |
| 磁力一直排队/失败 | 看 `docker logs movie-dock` 与容器内 `/var/log/aria2.log`；确认 RPC 为 `http://127.0.0.1:6800/jsonrpc` |
| 设置重启后丢失 | 升级到 0.1.1+（已修复配置持久化）；确认 `/config` 已挂载可写 |
| 整理路径不对 | 核对模板与 `/downloads` 挂载；界面显示的是容器内路径 |
| 端口占用 | 修改 compose 左侧端口后 `docker compose up -d` |
| 自定义索引无结果 | 用 curl 验证接口；确认 JSON 字段与 URL 可下载 |

### 更新

```bash
cd /vol1/apps/fn-movie-dock
git pull   # 或重新上传代码
docker compose up -d --build
```

### 卸载

```bash
cd /vol1/apps/fn-movie-dock
docker compose down
# 电影文件与配置保留在 volumes 目录，确认后再手动删除
```

---

## 11. 项目结构

```text
fn-movie-dock/
├── README.md                 # 本使用说明
├── Dockerfile
├── docker-compose.yml
├── config.example.yaml       # 配置示例（可提交）
├── requirements.txt
├── app/
│   ├── main.py               # FastAPI 入口
│   ├── config.py             # 配置加载/持久化
│   ├── llm.py                # OpenAI 兼容客户端与结果解析
│   ├── api/routes.py         # HTTP API
│   ├── search/               # 检索 Provider
│   ├── downloader/           # aria2 + HTTP 下载
│   ├── organizer/            # 自动整理
│   └── static/               # 中文前端
├── docker/entrypoint.sh      # 启动 aria2 + Web
├── deploy/fnos-deploy.md     # 飞牛部署补充说明
└── scripts/                  # 本地回归/冒烟脚本
```

---

## API 速查（高级用户）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET/PUT | `/api/config` | 读/写配置 |
| POST | `/api/llm/test` | 测试大模型连通性 |
| POST | `/api/search` | 检索候选 |
| POST | `/api/download` | 创建下载任务 |
| GET | `/api/tasks` | 任务列表 |
| GET | `/api/downloader/status` | aria2 状态 |
| POST | `/api/organize/preview` | 整理路径预览 |

---

## 许可证与声明

- 本项目代码以 **MIT** 许可证发布，见 [LICENSE](LICENSE)；可自由使用、修改、再分发（保留版权与许可声明）
- 发布包中随附的第三方二进制（`aria2c.exe` GPL-2.0+、`7z.exe/7z.dll` LGPL + unRAR 限制）
  各自适用其原许可证，详见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)
- 公开仓库中的示例配置**不含**任何真实 API Key
- 本项目**不提供、不托管任何影视资源**；请遵守当地法律法规与内容版权，
  仅下载你有权获取与存储的内容，使用后果由使用者自行承担
- 通常无法上架飞牛官方应用中心

---

## 反馈

若在飞牛上部署遇到问题，可附上：

1. `docker compose ps` 与 `docker logs movie-dock` 关键片段  
2. 设置页中「测试连接」的报错  
3. 任务卡片上的错误信息  

便于定位是网络、模型接口还是下载引擎问题。

---

## 12. 本改进版新增能力（0.1.2）

### 12.1 qBittorrent 检索源（推荐默认用这个）

原版的检索源里，演示数据是假的、大模型容易编链接。本版新增 `qbittorrent` provider：
直接复用本机 qBittorrent 的搜索插件（yts / bt4g / kickass / limetorrents …），结果是**真实可用**的磁力/种子。

```yaml
search:
  providers:
    - type: qbittorrent
      enabled: true
      name: "qBittorrent 搜索"
      url: "http://127.0.0.1:8085"      # qB WebUI 地址
      options:
        username: "admin"
        password: "******"
        plugins: "yts,yts_am,bt4g,limetorrents,kickass_torrent"   # 留空=全部（容易被慢插件拖住）
        limit: "100"
        search_timeout: "45"
```

要点：
- 需要先在 qBittorrent「搜索」页**安装搜索插件**，否则会提示未检测到插件
- 一个插件卡住会拖慢整次搜索 → 建议固定几个快的；内置默认推荐列表见代码常量 `DEFAULT_PLUGIN_HINT`
- 搜索结束会自动 `stop` + `delete` 搜索任务，不在 qB 里留垃圾

### 12.2 候选评分与「一键最优」

- 后端按 **清晰度 + 做种数 + 特性标签（DoVi/HDR/REMUX/Atmos…）+ 体积合理性** 打分
- 界面候选卡片显示 `评分 / DoVi / HDR / 做种 / 体积` 标签，最高分那条打「推荐」标记
- 搜索框旁「一键最优」按钮：直接用最高分候选打开下载弹窗
- 体积过小的 4K（<6GB）会被明显扣分，避免选到假种/低码率

### 12.3 下载完成后自动配中文字幕

- 来源 SubHD，流程：片名 → 字幕条目 → 下载 → 解压 → 挑最佳 → 改名成 `<视频名>.zh.ass` 放视频同目录
- 选择策略：优先 **简体/双语、ASS 特效**；条目里命中片源特征（2160p/UHD/BDRemux/发布组…）加分
- 防配错：英文关键词搜到的是同系列短片/别名时（例如用 `WALL-E` 搜到《电焊工波力》），
  若条目里找不到任何片源特征就**跳过不配**，而不是配一个错的
- 支持 **.rar / .7z 归档**（容器内已装 `p7zip-full` + `libarchive-tools`，rar5 也能读）
- 字幕文本非 UTF-8（GBK/Big5）会自动转 UTF-8
- 大陆/台湾译名差异：配置 `subtitle.extra_keywords`（如 `["机器人总动员"]`）；
  若配了大模型且候选里全是英文，还会**自动让模型补中文译名**再搜
- 任务卡片显示「字幕已配好 / 未匹配到字幕」，失败可点「重试字幕」

```yaml
subtitle:
  enabled: true
  extra_keywords: []
  prefer_bilingual: true
  name_template: "{video}.zh"
  llm_translate: true
  max_movies: 2
```

### 12.4 整理增强：剧集 / 资料库直落 / 扩展名

- 识别 `S01E02`、`s1e2`、`1x03`、`第5集`、`E07` → 走剧集模板
  （默认 `{title} ({year})/Season {season}` + `{title} ({year}) - S{season}E{episode} - {quality}`）
- 修正原版 preview 硬写 `.mkv` 的问题，**保留原扩展名**（.mp4/.ts/.iso…）
- 新增 `organize.library_root`：整理结果可直接落到已有电影库（如 `/vol2/1000/movie`），
  配合 `mode: hardlink` 可零拷贝入库

### 12.5 下载与任务健壮性

- **每个任务独立子目录** `incoming/<task_id>/`：修掉原版并发任务「按文件名猜该整理谁」的误整理风险
- 整理文件优先级：aria2 回报的准确文件列表 → 任务自己的目录兜底
- **任务状态落盘** `/data/tasks.json`：容器重启后任务列表不丢；重启后丢失的下载任务标记为「已中断」并给出提示
- aria2 参数补强：`seed-time=0`/`seed-ratio=0`（不做种，防 PCDN）、DHT、LPD、BT tracker（`downloader.bt_trackers`）、
  `extra_options` 可透传任意 aria2 参数

### 12.6 新增/变更 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/provider-types` | 检索源类型中文名 |
| POST | `/api/tasks/{task_id}/subtitle` | 重试字幕匹配 |
| GET | `/api/subtitle/candidates?keyword=` | 列出 SubHD 字幕条目（人工核对用） |
| GET | `/api/config` | 新增 `subtitle`、`search_sort_by_score` 字段 |
| POST | `/api/search` | 返回 `tags` / `score` / `best_id` |
| POST | `/api/download` | 新增 `fetch_subtitle` |
| POST | `/api/organize/preview` | 支持 `episode_text` / `ext`，返回 `is_series` |

### 12.7 回归测试

```bash
python scripts/review_checks.py   # 原版回归（22 项）
python scripts/unit_checks.py     # 本版新增功能（31 项）
python scripts/smoke_local.py     # 冒烟（起本地服务跑真实 API）
```
