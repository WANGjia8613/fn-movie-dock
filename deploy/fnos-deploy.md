# 飞牛 fnOS 部署指南（片坞 Movie Dock）

与主文档 [README.md](../README.md) 配套，侧重飞牛侧操作。完整使用说明以 README 为准。

适用：飞牛 fnOS，**x86_64**，Docker 后台 + Web 界面。

---

## 一、准备目录

```text
/vol1/apps/fn-movie-dock/config
/vol1/apps/fn-movie-dock/data
/vol1/media
```

| 宿主机 | 容器 | 用途 |
|--------|------|------|
| `/vol1/apps/fn-movie-dock/config` | `/config` | 配置与 API Key |
| `/vol1/media` | `/downloads` | 下载与整理结果 |
| `/vol1/apps/fn-movie-dock/data` | `/data` | 状态预留 |

存储空间不是 `vol1` 时，请同步修改 `docker-compose.yml`。

---

## 二、获取代码

### 方式 A：GitHub 克隆（推荐）

```bash
cd /vol1/apps
git clone https://github.com/<你的GitHub用户名>/fn-movie-dock.git
cd fn-movie-dock
```

### 方式 B：本机上传

将仓库目录用 SMB 或 `scp` 上传到飞牛，例如 `/vol1/apps/fn-movie-dock`。

---

## 三、修改并启动

1. 编辑 `docker-compose.yml` 的 volumes 与端口  
2. 启动：

```bash
cd /vol1/apps/fn-movie-dock
docker compose up -d --build
docker compose ps
docker logs -f movie-dock
```

若本机没有 Docker 构建环境，可在有 Docker 的机器上：

```bash
docker build -t movie-dock:0.1.1 .
docker save movie-dock:0.1.1 -o movie-dock.tar
```

再拷到飞牛 `docker load -i movie-dock.tar`，compose 中将 `build: .` 改为 `image: movie-dock:0.1.1`。

---

## 四、初始化

1. 浏览器打开 `http://NAS-IP:8090`
2. **设置** → 填写 Base URL / API Key / 模型名 → **测试连接** → **保存设置**
3. 配置写入：`/vol1/apps/fn-movie-dock/config/config.yaml`
4. 先启用「演示数据」点一次搜索，确认界面与任务流程正常

**不要**在公开场合提交含 Key 的 `config.yaml`；仓库内只保留 `config.example.yaml`。

---

## 五、路径换算

推荐挂载：`/vol1/media:/downloads`

| 界面显示（容器内） | 飞牛文件管理 |
|--------------------|--------------|
| `/downloads/incoming/...` | `/vol1/media/incoming/...` |
| `/downloads/movies/沙丘2 (2024)/....mkv` | `/vol1/media/movies/沙丘2 (2024)/....mkv` |

可选：飞牛影视媒体库指向 `/vol1/media/movies`。

---

## 六、更新 / 卸载

```bash
# 更新
cd /vol1/apps/fn-movie-dock
git pull
docker compose up -d --build

# 卸载（不会自动删你的电影文件）
docker compose down
```

---

## 七、常见问题

| 问题 | 处理 |
|------|------|
| `docker: command not found` | 飞牛应用中心启用 Docker |
| 构建慢/失败 | 异地 build 后 save/load；或检查 NAS 网络 |
| 磁力无速度 | 网络与资源站可达性；看 aria2 日志 `docker logs movie-dock` |
| 配置改了不生效 | 检查 compose 是否写了 LLM_* 环境变量（env 优先） |

更完整的使用与排错见 [README.md](../README.md)。
