from __future__ import annotations

from nook.adapters.dailydev import DailyDev
from nook.adapters.devto import DevTo
from nook.adapters.hackernews import HackerNews
from nook.adapters.tdd import DailyDiff
from nook.config import Config


def build_adapters(cfg: Config) -> dict:
    all_ = {
        "hn": HackerNews(),
        "tdd": DailyDiff(),
        "devto": DevTo(),
        "dailydev": DailyDev(cfg.daily_dev_token),
    }
    return {k: v for k, v in all_.items() if cfg.enabled.get(k, True)}
