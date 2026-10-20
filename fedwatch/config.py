"""读取指标配置。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "indicators.yaml"
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"


@dataclass(frozen=True)
class Indicator:
    key: str
    name: str
    fred_id: str
    transform: str
    scale: float
    decimals: int
    unit: str
    hawkish_sign: int
    weight: float
    revisions: bool
    frequency: str


@dataclass(frozen=True)
class Settings:
    alert_threshold_z: float
    min_history: int
    index_half_life_days: float
    analog_min_count: int
    notify_minor: bool = True
    history_start: str = "2015-01-01"


@dataclass(frozen=True)
class Config:
    indicators: dict[str, Indicator]
    market: dict[str, str]
    settings: Settings


def load_config(path: Path = CONFIG_PATH) -> Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    indicators = {}
    for key, v in raw["indicators"].items():
        if v["transform"] not in {"level", "pct_mom", "diff"}:
            raise ValueError(f"{key}: 未知 transform {v['transform']}")
        if v["hawkish_sign"] not in (1, -1):
            raise ValueError(f"{key}: hawkish_sign 只能是 1 或 -1")
        indicators[key] = Indicator(key=key, **v)
    return Config(
        indicators=indicators,
        market=dict(raw["market"]),
        settings=Settings(**raw["settings"]),
    )
