from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

SOURCE_IDS = ("hn", "tdd", "devto", "dailydev")

DEFAULT_TOML = """\
[app]
default_limit = 30
auto_mark_read = true

[cache]
max_auto_download_per_sync = 25
max_concurrent_downloads = 4

[sources.hn]
enabled = true
[sources.tdd]
enabled = true
[sources.devto]
enabled = true
[sources.dailydev]
enabled = true
# Token comes from the DAILY_DEV_TOKEN environment variable, never this file.
"""


class ConfigError(Exception):
    pass


def config_path() -> Path:
    return Path(os.environ.get("NOOK_CONFIG", Path(user_config_dir("nook")) / "config.toml"))


def default_db_path() -> Path:
    return Path(user_data_dir("nook")) / "nook.db"


@dataclass
class Config:
    db_path: Path = field(default_factory=default_db_path)
    default_limit: int = 30
    auto_mark_read: bool = True
    max_auto_download: int = 25
    max_concurrent_downloads: int = 4
    enabled: dict[str, bool] = field(default_factory=lambda: {s: True for s in SOURCE_IDS})

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
