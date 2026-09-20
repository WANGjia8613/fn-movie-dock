#!/bin/sh
set -e

CONFIG_PATH="${MOVIE_DOCK_CONFIG:-/config/config.yaml}"

if [ ! -f "$CONFIG_PATH" ]; then
  echo "[片坞] 未找到配置，从示例生成: $CONFIG_PATH"
  mkdir -p "$(dirname "$CONFIG_PATH")"
  cp /app/config.example.yaml "$CONFIG_PATH"
fi

mkdir -p /downloads /downloads/incoming /data /config
# 日志写进挂载卷（用 user: 1002 跑容器时 /var/log 不可写）
ARIA2_LOG="${ARIA2_LOG:-/data/aria2.log}"

echo "[片坞] 启动 aria2 RPC..."
ARIA2_ARGS="
  --enable-rpc
  --rpc-listen-all=true
  --rpc-listen-port=6800
  --rpc-allow-origin-all=true
  --dir=/downloads/incoming
  --seed-time=0
  --seed-ratio=0.0
  --max-concurrent-downloads=${MAX_CONCURRENT:-3}
  --continue=true
  --auto-file-renaming=true
  --allow-overwrite=false
  --file-allocation=none
  --max-connection-per-server=16
  --split=16
  --disk-cache=64M
  --enable-dht=true
  --bt-enable-lpd=true
  --bt-save-metadata=true
  --bt-max-peers=64
  --follow-torrent=true
  --console-log-level=warn
  --summary-interval=0
"

# 可选：全局 tracker 列表（逗号分隔），也能在配置文件里按任务下发
if [ -n "${BT_TRACKERS:-}" ]; then
  ARIA2_ARGS="$ARIA2_ARGS --bt-tracker=${BT_TRACKERS}"
fi

# 可选：RPC 密钥（同时记得在配置里填 downloader.aria2.rpc_secret）
if [ -n "${ARIA2_RPC_SECRET:-}" ]; then
  ARIA2_ARGS="$ARIA2_ARGS --rpc-secret=${ARIA2_RPC_SECRET}"
fi

# shellcheck disable=SC2086
aria2c $ARIA2_ARGS >"$ARIA2_LOG" 2>&1 &

echo "[片坞] 启动 Web 服务..."
cd /app
exec python -m uvicorn app.main:app --host "${SERVER_HOST:-0.0.0.0}" --port "${SERVER_PORT:-8090}"
