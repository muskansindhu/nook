from __future__ import annotations

import os
import tomllib
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir
from pydantic import BaseModel, ConfigDict, Field

from nook.constants import (
    APP_NAME, DEFAULT_LIMIT, DEFAULT_MAX_AUTO_DOWNLOAD, DEFAULT_MAX_CONCURRENT_DOWNLOADS, SOURCE_IDS,
)



class ConfigError(Exception):
    pass


def config_path() -> Path:
    return Path(os.environ.get("NOOK_CONFIG", Path(user_config_dir(APP_NAME)) / "config.toml"))


def default_db_path() -> Path:
    return Path(user_data_dir(APP_NAME)) / "nook.db"


class Config(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    db_path: Path = Field(default_factory=default_db_path)
    default_limit: int = DEFAULT_LIMIT
    auto_mark_read: bool = True
    max_auto_download: int = DEFAULT_MAX_AUTO_DOWNLOAD
    max_concurrent_downloads: int = DEFAULT_MAX_CONCURRENT_DOWNLOADS
    enabled: dict[str, bool] = Field(default_factory=lambda: {s: True for s in SOURCE_IDS})

    @property
    def daily_dev_token(self) -> str | None:
        return os.environ.get("DAILY_DEV_TOKEN") or None


def load_config() -> Config:
    path = config_path()
    cfg = Config()
    if env_db := os.environ.get("NOOK_DB"):
        cfg.db_path = Path(env_db).expanduser()
    if not path.exists():
        return cfg
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Invalid TOML in {path}: {e}") from e
    app, cache = data.get("app", {}), data.get("cache", {})
    try:
        cfg.default_limit = int(app.get("default_limit", cfg.default_limit))
        cfg.auto_mark_read = bool(app.get("auto_mark_read", cfg.auto_mark_read))
        cfg.max_auto_download = int(cache.get("max_auto_download_per_sync", cfg.max_auto_download))
        cfg.max_concurrent_downloads = int(cache.get("max_concurrent_downloads", cfg.max_concurrent_downloads))
    except (TypeError, ValueError) as e:
        raise ConfigError(f"Bad value in {path}: {e}") from e
    if "database" in data and "path" in data["database"] and not os.environ.get("NOOK_DB"):
        cfg.db_path = Path(str(data["database"]["path"])).expanduser()
    for sid, sconf in data.get("sources", {}).items():
        if sid not in SOURCE_IDS:
            raise ConfigError(f"Unknown source '{sid}' in {path}")
        cfg.enabled[sid] = bool(sconf.get("enabled", True))
    return cfg
