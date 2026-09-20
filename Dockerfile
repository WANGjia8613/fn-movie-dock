# 片坞 Movie Dock — 面向飞牛 fnOS (x86_64) 的 Docker 镜像
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MOVIE_DOCK_CONFIG=/config/config.yaml \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=8090

# aria2：容器内 BT/磁力/HTTP 下载引擎
RUN apt-get update \
    && apt-get install -y --no-install-recommends aria2 ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY config.example.yaml /app/config.example.yaml
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && mkdir -p /config /data /downloads

VOLUME ["/config", "/downloads", "/data"]
EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8090/api/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
