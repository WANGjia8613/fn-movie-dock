from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8090


class LLMConfig(BaseModel):
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout_seconds: int = 60


class PathsConfig(BaseModel):
    download_root: str = "/downloads"


class ProviderConfig(BaseModel):
    type: str
    enabled: bool = False
    name: str = ""
    url: str = ""
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)


class SearchConfig(BaseModel):
    providers: list[ProviderConfig] = Field(default_factory=list)


class OrganizeConfig(BaseModel):
    enabled: bool = True
    movie_dir_template: str = "{title} ({year})"
    file_name_template: str = "{title} ({year}) - {quality}"
    mode: Literal["move", "copy", "hardlink"] = "move"
    unknown_year: str = "未知年份"


class Aria2Config(BaseModel):
    rpc_url: str = "http://127.0.0.1:6800/jsonrpc"
    rpc_secret: str = ""


class DownloaderConfig(BaseModel):
    engine: str = "aria2"
    aria2: Aria2Config = Field(default_factory=Aria2Config)
    max_concurrent: int = 3
    category_dir: str = "incoming"


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    organize: OrganizeConfig = Field(default_factory=OrganizeConfig)
    downloader: DownloaderConfig = Field(default_factory=DownloaderConfig)

    def download_root(self) -> Path:
        return Path(self.paths.download_root).expanduser().resolve()

    def incoming_dir(self) -> Path:
        return self.download_root() / self.downloader.category_dir


def _config_file_path() -> Path:
    env = os.environ.get("MOVIE_DOCK_CONFIG")
    if env:
        return Path(env)
    local = Path(__file__).resolve().parent.parent / "config.yaml"
    if local.exists():
        return local
    docker_path = Path("/config/config.yaml")
    if docker_path.parent.exists():
        return docker_path
    return Path(__file__).resolve().parent.parent / "config.yaml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


_DEFAULT_DATA: dict[str, Any] = {
    "server": {"host": "0.0.0.0", "port": 8090},
    "llm": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini",
        "timeout_seconds": 60,
    },
    "paths": {"download_root": "/downloads"},
    "search": {
        "providers": [
            {"type": "demo", "enabled": True, "name": "演示数据"},
            {"type": "llm", "enabled": True, "name": "大模型检索"},
            {
                "type": "custom_api",
                "enabled": False,
                "name": "自定义索引",
                "url": "",
                "method": "GET",
                "headers": {},
            },
        ]
    },
    "organize": {
        "enabled": True,
        "movie_dir_template": "{title} ({year})",
        "file_name_template": "{title} ({year}) - {quality}",
        "mode": "move",
        "unknown_year": "未知年份",
    },
    "downloader": {
        "engine": "aria2",
        "aria2": {"rpc_url": "http://127.0.0.1:6800/jsonrpc", "rpc_secret": ""},
        "max_concurrent": 3,
        "category_dir": "incoming",
    },
}


def _ensure_provider_types(cfg: AppConfig) -> AppConfig:
    """保证界面始终能编辑到演示/大模型/自定义索引三类源。"""
    required = [
        ProviderConfig(type="demo", enabled=False, name="演示数据"),
        ProviderConfig(type="llm", enabled=False, name="大模型检索"),
        ProviderConfig(
            type="custom_api",
            enabled=False,
            name="自定义索引",
            url="",
            method="GET",
            headers={},
        ),
    ]
    existing = {p.type for p in cfg.search.providers}
    if len(existing) >= len(required) and {"demo", "llm", "custom_api"} <= existing:
        return cfg
    merged = list(cfg.search.providers)
    for item in required:
        if item.type not in existing:
            merged.append(item)
    cfg.search = SearchConfig(providers=merged)
    return cfg


def load_config(path: Path | None = None) -> AppConfig:
    cfg_path = path or _config_file_path()
    # 深拷贝，避免环境变量覆盖写穿 _DEFAULT_DATA
    data = copy.deepcopy(_DEFAULT_DATA)
    if cfg_path.exists():
        with cfg_path.open("r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        if isinstance(loaded, dict):
            data = _deep_merge(data, loaded)

    # 本地开发：若配置里仍是容器路径且不可用，回退到项目目录
    raw_root = str(data.get("paths", {}).get("download_root") or "")
    if raw_root in ("/downloads", "", None):
        if os.name == "nt" or not Path("/downloads").parent.exists():
            data.setdefault("paths", {})["download_root"] = str(
                Path(__file__).resolve().parent.parent / "downloads"
            )

    env_overrides = {
        "LLM_BASE_URL": ("llm", "base_url"),
        "LLM_API_KEY": ("llm", "api_key"),
        "LLM_MODEL": ("llm", "model"),
        "DOWNLOAD_ROOT": ("paths", "download_root"),
        "ARIA2_RPC_URL": ("downloader", "aria2", "rpc_url"),
        "ARIA2_RPC_SECRET": ("downloader", "aria2", "rpc_secret"),
        "SERVER_PORT": ("server", "port"),
    }
    for env_key, path_keys in env_overrides.items():
        raw = os.environ.get(env_key)
        if raw is None or raw == "":
            continue
        cursor: Any = data
        for k in path_keys[:-1]:
            if not isinstance(cursor.get(k), dict):
                cursor[k] = {}
            cursor = cursor[k]
        leaf = path_keys[-1]
        if leaf == "port":
            try:
                cursor[leaf] = int(raw)
            except ValueError:
                continue
        else:
            cursor[leaf] = raw
    return _ensure_provider_types(AppConfig.model_validate(data))


def _read_yaml_dict(cfg_path: Path) -> dict[str, Any]:
    if not cfg_path.exists():
        return {}
    with cfg_path.open("r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f) or {}
    return loaded if isinstance(loaded, dict) else {}


def save_app_config(cfg: AppConfig) -> Path:
    """把当前内存中的可持久化配置完整写回配置文件。"""
    cfg_path = _config_file_path()
    existing = _read_yaml_dict(cfg_path)
    existing["llm"] = cfg.llm.model_dump()
    existing["paths"] = cfg.paths.model_dump()
    existing["organize"] = cfg.organize.model_dump()
    existing["search"] = cfg.search.model_dump()
    existing["downloader"] = cfg.downloader.model_dump()
    existing["server"] = cfg.server.model_dump()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with cfg_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(existing, f, allow_unicode=True, sort_keys=False)
    return cfg_path


def save_runtime_llm(llm: LLMConfig, paths: PathsConfig | None = None) -> Path:
    """兼容旧接口：仅更新 LLM（及可选 paths）。"""
    cfg_path = _config_file_path()
    existing = _read_yaml_dict(cfg_path)
    existing["llm"] = llm.model_dump()
    if paths is not None:
        existing["paths"] = paths.model_dump()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with cfg_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(existing, f, allow_unicode=True, sort_keys=False)
    return cfg_path
