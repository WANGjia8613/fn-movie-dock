from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import load_config
from .downloader import DownloadManager
from .search import load_providers

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    try:
        root = cfg.download_root()
        root.mkdir(parents=True, exist_ok=True)
        cfg.incoming_dir().mkdir(parents=True, exist_ok=True)
    except OSError:
        fallback = Path(__file__).resolve().parent.parent / "downloads"
        fallback.mkdir(parents=True, exist_ok=True)
        cfg.paths.download_root = str(fallback)
        cfg.incoming_dir().mkdir(parents=True, exist_ok=True)

    app.state.config = cfg
    app.state.download_manager = DownloadManager(cfg)
    app.state.search_providers = load_providers(cfg)
    app.state.download_manager.start_background()
    yield
    await app.state.download_manager.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="片坞 Movie Dock",
        description="飞牛 NAS 一体化片源检索与下载",
        version="0.1.1",
        lifespan=lifespan,
    )
    app.include_router(router)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index():
        index_path = STATIC_DIR / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path), media_type="text/html; charset=utf-8")
        return {"message": "片坞 API 已启动，但未找到前端静态文件"}

    return app


app = create_app()


def main() -> None:
    import uvicorn

    cfg = load_config()
    host = os.environ.get("SERVER_HOST") or cfg.server.host
    port = int(os.environ.get("SERVER_PORT") or cfg.server.port)
    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
