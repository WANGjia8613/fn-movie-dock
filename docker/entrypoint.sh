#!/bin/sh
set -e

CONFIG_PATH="${MOVIE_DOCK_CONFIG:-/config/config.yaml}"

if [ ! -f "$CONFIG_PATH" ]; then
  echo "[片坞] 未找到配置，从示例生成: $CONFIG_PATH"
  mkdir -p "$(dirname "$CONFIG_PATH")"
  cp /app/config.example.yaml "$CONFIG_PATH"
fi

# 默认把容器内下载目录写进配置（若用户未改）
# 环境变量优先，见 app/config.py

mkdir -p /downloads /data /config

echo "[片坞] 启动 aria2 RPC..."
aria2c \
  --enable-rpc \
  --rpc-listen-all=true \
  --rpc-listen-port=6800 \
  --rpc-allow-origin-all=true \
  --dir=/downloads/incoming \
  --seed-time=0 \
  --max-concurrent-downloads="${MAX_CONCURRENT:-3}" \
  --continue=true \
  --auto-file-renaming=true \
  --allow-overwrite=false \
  --file-allocation=none \
  --console-log-level=warn \
  ${ARIA2_RPC_SECRET:+--rpc-secret=$ARIA2_RPC_SECRET} \
  >/var/log/aria2.log 2>&1 &

echo "[片坞] 启动 Web 服务..."
cd /app
exec python -m uvicorn app.main:app --host "${SERVER_HOST:-0.0.0.0}" --port "${SERVER_PORT:-8090}"
