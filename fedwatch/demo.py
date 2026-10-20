"""离线演示：生成模拟数据，跑通整条流程（不需要网络和 API key）。

模拟数据仅用于展示功能，数值不代表真实经济数据。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Config


def _first_friday(month_start: pd.Timestamp) -> pd.Timestamp:
    d = month_start
    while d.weekday() != 4:
        d += pd.Timedelta(days=1)
    return d


def _bday(d: pd.Timestamp) -> pd.Timestamp:
    while d.weekday() >= 5:
        d += pd.Timedelta(days=1)
    return d


class DemoSource:
    """模拟 FRED：指标序列 + 公布日期 + 带"意外冲击"的市场序列。"""

    # (月内公布日规则)
    RELEASE_RULE = {
        "CPILFESL": lambda m: _bday(m + pd.DateOffset(months=1, days=11)),
        "CPIAUCSL": lambda m: _bday(m + pd.DateOffset(months=1, days=11)),
        "PCEPILFE": lambda m: _bday(m + pd.DateOffset(months=1, days=27)),
        "PAYEMS": lambda m: _first_friday(m + pd.DateOffset(months=1)),
        "UNRATE": lambda m: _first_friday(m + pd.DateOffset(months=1)),
        "RSAFS": lambda m: _bday(m + pd.DateOffset(months=1, days=14)),
    }

    def __init__(self, cfg: Config, end: str = "2026-10-16", seed: int = 7):
        self.cfg = cfg
        rng = np.random.default_rng(seed)
        self.series_map: dict[str, pd.Series] = {}
        self.release_map: dict[str, list[pd.Timestamp]] = {}
        self.consensus_rows: list[dict] = []
        end_ts = pd.Timestamp(end)
        months = pd.date_range("2017-01-01", end_ts - pd.DateOffset(months=1), freq="MS")
        shocks: dict[pd.Timestamp, float] = {}

        # 每个指标：先生成"公布口径"的值，再反推原始水平序列
        spec = {  # fred_id: (均值, 波动, 意外标准差)
            "CPILFESL": (0.28, 0.08, 0.08), "CPIAUCSL": (0.25, 0.15, 0.10),
            "PCEPILFE": (0.24, 0.07, 0.06), "PAYEMS": (170, 90, 70),
            "UNRATE": (4.0, 0.0, 0.10), "RSAFS": (0.35, 0.6, 0.45),
        }
        for ind in cfg.indicators.values():
            fid = ind.fred_id
            if fid == "ICSA":
                continue
            mu, vol, s_sd = spec[fid]
            if ind.transform == "level":  # 失业率：缓慢游走
                vals = mu + np.cumsum(rng.normal(0, 0.06, len(months)))
                vals = np.clip(vals, 3.4, 6.0)
            else:
                vals = mu + vol * rng.standard_normal(len(months))
            vals = np.round(vals, ind.decimals)
            if ind.transform == "pct_mom":
                level = 100 * np.cumprod(1 + vals / 100)
                raw = np.concatenate([[100.0], level])
            elif ind.transform == "diff":
                raw = np.concatenate([[150000.0], 150000.0 + np.cumsum(vals)])
            else:
                raw = np.concatenate([[vals[0]], vals])
            idx = pd.DatetimeIndex([months[0] - pd.DateOffset(months=1)]).append(months)
            self.series_map[fid] = pd.Series(raw, index=idx, name=fid)

            rel = [self.RELEASE_RULE[fid](m) for m in months]
            self.release_map[fid] = sorted(rel)
            surprises = np.round(rng.normal(0, s_sd, len(months)), ind.decimals)
            for m, v, s, rd in zip(months, vals, surprises, rel):
                self.consensus_rows.append({
                    "indicator": ind.key, "period": m.strftime("%Y-%m"),
                    "consensus": round(float(v - s), ind.decimals), "source": "模拟", "note": "",
                })
                shocks[rd] = shocks.get(rd, 0.0) + ind.weight * ind.hawkish_sign * s / s_sd / 3

        # 初请：周度
        if "ICSA" in [i.fred_id for i in cfg.indicators.values()]:
            ind = next(i for i in cfg.indicators.values() if i.fred_id == "ICSA")
            weeks = pd.date_range("2017-01-07", end_ts - pd.Timedelta(days=6), freq="W-SAT")
            lvl = np.clip(225 + np.cumsum(rng.normal(0, 4, len(weeks))), 190, 320)
            surprises = np.round(rng.normal(0, 10, len(weeks)))
            actual_k = np.round(lvl)
            self.series_map["ICSA"] = pd.Series(actual_k * 1000, index=weeks, name="ICSA")
            rel = [w + pd.Timedelta(days=5) for w in weeks]
            self.release_map["ICSA"] = rel
            for w, a, s, rd in zip(weeks, actual_k, surprises, rel):
                self.consensus_rows.append({
                    "indicator": "claims", "period": w.strftime("%Y-%m-%d"),
                    "consensus": float(a - s), "source": "模拟", "note": "",
                })
                shocks[rd] = shocks.get(rd, 0.0) + ind.weight * ind.hawkish_sign * s / 10 / 3

        # 市场：随机游走 + 公布日对意外的反应（鹰派 → 收益率升、股市跌）
        days = pd.bdate_range("2016-12-01", end_ts)
        shock = np.array([shocks.get(d, 0.0) for d in days])
        dy = rng.normal(0, 0.035, len(days)) + 0.05 * shock
        self.series_map["DGS2"] = pd.Series(np.clip(2.0 + np.cumsum(dy), 0.1, 6), index=days, name="DGS2")
        r_spx = rng.normal(0.0004, 0.009, len(days)) - 0.004 * shock
        self.series_map["SP500"] = pd.Series(2300 * np.cumprod(1 + r_spx), index=days, name="SP500")
        r_ndx = 1.3 * r_spx + rng.normal(0, 0.004, len(days))
        self.series_map["NASDAQCOM"] = pd.Series(5500 * np.cumprod(1 + r_ndx), index=days, name="NASDAQCOM")

    def series(self, series_id: str, start: str = "2000-01-01") -> pd.Series:
        s = self.series_map[series_id]
        return s[s.index >= pd.Timestamp(start)]

    def release_dates(self, series_id: str) -> list[pd.Timestamp]:
        return self.release_map.get(series_id, [])

    def consensus_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.consensus_rows)
