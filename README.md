# 片坞 Movie Dock

**中文一体化片源检索与下载工具**：输入片名 → 检索多清晰度候选 → 选择片源 → 下载（磁力/种子/直链）→ 自动整理进媒体库 → 自动配中文字幕。

两种形态，同一套内核：

| 形态 | 跑在哪 | 适合 |
|---|---|---|
| **Windows 本地客户端** | 你自己的 PC（WebView2 原生窗口） | 不想装 NAS、就想本地一个软件搞定 |
| **飞牛 NAS / Docker 服务端** | 飞牛 fnOS 或其他 Linux NAS | 7×24 挂着下，家里人共享 |

> ⚠️ 本工具**不提供、不托管任何影视资源**。请遵守当地法律法规与内容版权，仅下载你有权获取与存储的内容；使用后果由使用者自行承担。

---

## 1. 下载与安装

**Windows 客户端（最新版）**
👉 <https://github.com/WANGjia8613/fn-movie-dock/releases>

1. 下 `MovieDock-win64.zip` → 解压 → 双击 `MovieDock.exe`
2. 首次启动会生成配置：`%APPDATA%\MovieDock\config.yaml`，并让你选下载目录
3. 想彻底去掉"未知发布者"提示：右键 `trust-moviedock-cert.ps1` → 使用 PowerShell 运行（导入自签名证书，见 [§11](#11-代码签名)）

**飞牛 NAS / Docker（最新版）**
👉 同版本号**不带 `-win`** 的 Release，例如 `v0.4.2`

```bash
# 方式一：拉镜像（GHCR）— 国内网络可能很慢/拉不动，见下方说明
docker pull ghcr.io/wangjia8613/fn-movie-dock:latest

# 方式二：离线镜像包（推荐国内用户）
#   下载 Release 里的 fn-movie-dock-<版本>-docker-image.tar.gz，传到 NAS 后：
gunzip -c fn-movie-dock-v0.4.2-docker-image.tar.gz | docker load
#   或在飞牛「Docker 应用 → 镜像 → 从文件导入」里选这个文件

# 方式三：源码构建（不依赖任何镜像仓库）
#   把仓库放到 NAS 上，用仓库里的 docker-compose.yml（build: .）
```

然后编辑 Release 里的 `docker-compose.release.yml`（改成本机路径）并启动：

```bash
docker compose -f docker-compose.release.yml up -d
# 浏览器打开 http://NAS-IP:8090
```

> **国内网络提示**：`ghcr.io` 的镜像层下载在国内经常只有几十 B/s（实测），基本拉不完。
> 所以国内用户请优先用**离线镜像包**或**源码构建**（源码构建只需拉基础镜像与 PyPI，实测可达）。

---

## 2. 功能

**检索**
- **内置直连索引源**（不依赖任何外部客户端）：TPB(apibay) / YTS / DMHY 动漫花园，多镜像自动重试
- 可选 **qBittorrent 搜索插件**（若本机有 qB）、**自定义索引 API**、**大模型检索**
- 候选**评分排序**：清晰度 + 做种数 + 特性标签（DoVi/HDR/REMUX/Atmos…）+ 体积合理性 + **关键词相关度**
- 「**一键最优**」直接选最高分候选
- 中文片名可用：配了大模型 API Key 会自动翻成英文再搜；也可填该源支持的代理启用中文源

**下载**
- 内置 **aria2**（磁力 / 种子 / HTTP 直链），默认 `seed-time=0` **不做种**（防 PCDN）
- 任务独立子目录、**任务状态落盘**（重启不丢、自动接管）
- **暂停 / 继续**（HTTP 直链任务自动改走断点续传，绕开 aria2 的已知 bug）
- **删除历史**：只删记录，或连文件一起删（仅限配置目录内，删视频连带同名字幕）
- 手动粘贴磁力/直链（不依赖任何检索源）

**自动整理**
- 电影：`{片名} ({年份})/{片名} ({年份}) - {清晰度}.{ext}`
- 剧集：识别 `S01E02` / `1x03` / `第5集` → `{片名} ({年份})/Season 01/...`
- 支持 `move` / `copy` / **`hardlink`**（同卷零拷贝入库）
- 可指定 `library_root` 直接落到已有媒体库

**自动中文字幕**
- 来源 SubHD：匹配 → 下载 → 解压（**zip / rar / 7z** 全支持）→ 挑最佳 → 重命名为 `<视频名>.zh.ass`
- 优先**简体/双语 + ASS 特效**；`prefer_simplified` 可选简体优先
- 防配错：英文关键词搜到同系列短片/别名时，若条目不含片源特征就跳过，宁缺勿错
- 译名差异可配 `extra_keywords`（如 `["机器人总动员"]`）；配了大模型可自动补中文/英文名

**其它**
- 中文界面、托盘图标、单实例、日志落盘（Windows: `%APPDATA%\MovieDock\logs\app.log`）
- 启动页兜底：服务未就绪不会给你一个"拒绝连接"的死窗口

---

## 3. 检索源怎么配

| 源 | 说明 | 国内可达性（实测） |
|---|---|---|
| `builtin` **内置索引**（默认开启） | tpb=海盗湾(apibay API) / yts / dmhy=动漫花园 | **tpb 直连可用**；yts/dmhy 建议配代理 |
| `qbittorrent` | 复用本机 qBittorrent 的搜索插件 | 需本机跑着 qB（WebUI 8085）并可访问插件站点 |
| `custom_api` | 你自己的 JSON 索引接口（GET/POST） | 取决于你的接口 |
| `llm` | 大模型整理候选 / 中英片名互译 | 需 OpenAI 兼容接口（DeepSeek 等） |
| `demo` | **调试用假数据**（假链接，不能下载） | — |

**代理**：境外索引源与字幕站建议在「设置 → 网络（代理）」填本地代理，例如 Clash 混合端口
`http://127.0.0.1:7890`（Docker 模式可给容器加 `HTTPS_PROXY` 环境变量）。

`config.yaml` 片段：

```yaml
network:
  proxy: ""            # 例 http://127.0.0.1:7890
  timeout_seconds: 20
search:
  providers:
    - type: builtin
      enabled: true
      name: "内置索引"
      options: { sources: "tpb,yts,dmhy", limit: "60" }
    - type: qbittorrent
      enabled: false
      url: "http://127.0.0.1:8085"
      options: { username: "admin", password: "", plugins: "piratebay" }
```

自定义索引接口约定：返回 JSON 数组或 `{items|results|sources: [...]}`，
每项支持 `title/name`、`url/magnet/link`、`quality`、`resolution`、`size`、`seeds`、`note` 等字段。

---

## 4. 整理规则

```
{media_root}/{片名} ({年份})/{片名} ({年份}) - {清晰度}.{ext}
```

- 占位符：`{title}` `{year}` `{quality}` `{resolution}` `{season}` `{episode}` `{ext}`
- 年份缺失时用 `unknown_year`（默认「未知年份」）
- 剧集模板：`{title} ({year})/Season {season}` + `{title} ({year}) - S{season}E{episode} - {quality}`
- `mode`: `move`（默认）/ `copy` / `hardlink`
- `library_root`：留空则落在下载根目录下；填了就整理到该目录（配合 hardlink 可零拷贝入库）

**路径换算（Docker）**：界面显示的是容器内路径，对照你的挂载表换算即可。

| 容器内 | 你的 NAS（示例） |
|---|---|
| `/downloads/incoming/<任务id>/` | `/vol2/1000/movie-md-incoming/incoming/<任务id>/` |
| `/library/片名 (年份)/` | `/vol2/1000/movie/片名 (年份)/` |
| `/config`、`/data` | `/vol1/@appcenter/movie-dock/{config,data}` |

---

## 5. 命令行与自检

打包内含两个可执行文件：

```bash
MovieDock.exe        # GUI（WebView2 窗口）
MovieDockCLI.exe     # 控制台版：排查问题用
```

```bash
MovieDockCLI.exe --selftest                    # 启动→自检→退出（环境/引擎/接口）
MovieDockCLI.exe --headless --port 8090        # 只跑服务，不开窗口
MovieDockCLI.exe --browser                     # 用默认浏览器代替内置窗口
MovieDockCLI.exe --download-dir "D:\Movies"    # 指定下载目录（首次运行写入配置）
MovieDockCLI.exe --startup-timeout 120         # 首次启动慢可调大等待时间
```

配置与日志位置：

| 平台 | 配置 | 日志 |
|---|---|---|
| Windows | `%APPDATA%\MovieDock\config.yaml` | `%APPDATA%\MovieDock\logs\app.log` |
| Docker | `/config/config.yaml` | 容器内 `/data/aria2.log` + `docker logs` |
| Linux 桌面 | `~/.config/movie-dock/config.yaml` | 同目录 `logs/` |

---

## 6. API 速查（高级用户）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查（含版本号） |
| GET/PUT | `/api/config` | 读写配置（保存即热更新） |
| POST | `/api/search` | 检索候选（返回 `tags`/`score`/`best_id`） |
| POST | `/api/download` | 建下载任务（`fetch_subtitle` 控制是否配字幕） |
| GET | `/api/tasks` | 任务列表 |
| POST | `/api/tasks/{id}/pause｜resume` | 暂停 / 继续 |
| DELETE | `/api/tasks/{id}?delete_files=` | 删除任务（可选连文件删除） |
| POST | `/api/tasks/clear` | 批量清理（`scope=completed\|error\|all`） |
| POST | `/api/tasks/{id}/subtitle` | 重试字幕匹配 |
| GET | `/api/subtitle/candidates?keyword=` | 列出 SubHD 字幕条目（人工核对） |
| POST | `/api/organize/preview` | 整理路径预览 |
| GET | `/api/downloader/status` | aria2 状态 |

---

## 7. Docker 部署细节（飞牛为例）

| 宿主路径 | 容器路径 | 用途 |
|---|---|---|
| `/vol1/@appcenter/movie-dock/config` | `/config` | 配置（含 API Key / qB 密码，注意保密） |
| `/vol2/1000/movie-md-incoming` | `/downloads` | 下载临时目录（建议放空间大的存储空间） |
| `/vol1/@appcenter/movie-dock/data` | `/data` | 任务状态（重启不丢） |
| `/vol2/1000/movie` | `/library` | 电影库（可选，配合 `organize.library_root: /library`） |

**权限要点**：飞牛的媒体库目录常受 `trimacl` 限制，只有特定 uid 能写。
容器默认以 `user: "1002:1002"`（应用账号）运行；若你的环境不同，改成能写目标目录的 uid，
或给该目录加 ACL。部署后先测一下：

```bash
docker exec movie-dock sh -c 'touch /library/.w && rm /library/.w && echo 可写'
```

**容器与服务端通信**：aria2 跑在容器内（应用连 `127.0.0.1:6800`，无需额外配置）。
若要连**宿主**上的 qBittorrent（WebUI），用 `extra_hosts: ["host.docker.internal:host-gateway"]`
并把 provider `url` 写成 `http://host.docker.internal:8085`。

---

## 8. 项目结构

```
app/
├── main.py            FastAPI 入口
├── config.py          配置模型（含跨平台落位、老配置迁移）
├── runtime.py         跨平台运行时（工具探测 / aria2 托管 / 目录 / UTF-8）
├── ranking.py         候选评分（清晰度/做种/特性/相关度）
├── api/routes.py      HTTP API
├── search/            builtin(tpb/yts/dmhy) · qbittorrent · custom_api · llm · demo
├── downloader/        aria2 管理（暂停/续传/删除/任务持久化）
├── organizer/         整理规则（电影/剧集/硬链/模板）
├── subtitle/          SubHD 客户端 + 解压兜底 + 条目打分
├── desktop/           桌面启动器（launcher / window / tray）
└── static/            中文界面（index.html / app.js / style.css / splash.html）
scripts/               fetch_vendor · 单测 · 端到端/任务操作测试 · 签名证书生成
packaging/             PyInstaller 规格、图标、自签名证书与信任脚本
.github/workflows/     ci(ubuntu) · windows-build(出 Windows Release) · docker-release(出镜像与离线包)
```

---

## 9. 开发与测试

```bash
python -m venv .venv && ./.venv/bin/pip install -r requirements.txt
python scripts/review_checks.py     # 上游回归
python scripts/unit_checks.py       # 新增功能单测（含内置源解析/迁移/暂停删除）
python scripts/desktop_checks.py    # 桌面与跨平台层
python scripts/ci_download_test.py  # 端到端：本地 HTTP → aria2 下载 → 整理
python scripts/ci_ops_test.py       # 端到端：暂停 / 继续 / 删除历史
python -m app.desktop --headless    # 本地起服务（桌面模式）
```

CI：每次 push 跑 ubuntu 全量测试；打 tag `v*-win` 出 Windows Release；打 tag `v*` 出 Docker 镜像与离线包。

---

## 10. 常见问题

| 现象 | 处理 |
|---|---|
| Windows 打开显示"127.0.0.1 拒绝连接" | 首次启动被杀软扫描拖慢：新版会先显示"片坞正在启动…"并自动跳转；不行就按 F5，或看 `logs/app.log` |
| 搜索没结果 | 确认「设置 → 检索源」里**内置索引**已勾选；中文片名在英文站无效，用英文名或配代理启用 dmhy，或配大模型自动翻译 |
| 内置源连不上 | 配「网络（代理）」；tpb 源不需要代理 |
| 字幕没配上 | 在字幕设置里填 `extra_keywords`（SubHD 常搜不到英文名），下完后可在任务卡点「重试字幕」 |
| Docker 拉不动镜像 | 用离线镜像包或源码构建（见 §1） |
| 整理时报权限错误 | 容器 `user:` 改成能写目标目录的 uid，或给目录加 ACL |
| 任务重启后不见了 | 新版会把任务落盘到 `/data/tasks.json` 并自动接管；若 aria2 会话丢失，任务会标为"已中断" |

---

## 11. 代码签名

- Windows 包里的两个 exe 已用项目**自签名证书**签名（SHA256 + 时间戳），SHA1 指纹
  `92A20205A84C867586BD8E1671D7B2B9A31D2BCC`
- 想彻底去掉"未知发布者"提示：右键 `trust-moviedock-cert.ps1` → 使用 PowerShell 运行
  （导入"受信任的根"与"受信任的发布者"），之后 `Get-AuthenticodeSignature .\MovieDock.exe` 应显示 `Valid`
- **预期管理**：自签名能消除"未知发布者"，但 **SmartScreen 的下载信誉提示**需要商业代码签名证书（OV/EV）
  或 Azure Artifact Signing 之类的公众信任方案；不想折腾就右键 zip → 属性 → 勾选"解除锁定"
- 维护者换证书：`scripts/make_signing_cert.sh`（生成后把 pfx/口令/指纹写入 GitHub Secrets）

---

## 12. 许可证与声明

- 本项目代码以 **MIT** 许可证发布，见 [LICENSE](LICENSE)：可自由使用、修改、再分发（保留版权与许可声明）
- 发布包中随附的第三方二进制各自适用其原许可证：
  `aria2c.exe`（GPL-2.0-or-later）、`7z.exe/7z.dll`（LGPL-2.1+，RAR 部分受 unRAR 限制），
  详见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)
- 公开仓库中的示例配置**不含**任何真实 API Key
- 本项目**不提供、不托管任何影视资源**；请遵守当地法律法规与内容版权，使用后果由使用者自行承担
- 通常无法上架飞牛官方应用中心

## 反馈

提 Issue 时建议附上：系统/版本号、`MovieDockCLI.exe --selftest` 输出（或 `logs/app.log` 关键片段）、
复现步骤与截图。检索源问题请说明用哪个源、关键词、以及是否配了代理。
