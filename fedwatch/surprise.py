"""预期差计算：纯函数，不做任何网络请求，方便测试。

核心公式：
    原始意外 = 实际值 - 一致预期 (+ 前值修正，若启用)
    z        = 原始意外 / 历史意外标准差
    鹰派 z   = z * hawkish_sign      （>0 偏鹰，<0 偏鸽）
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from .config import Indicator


# ---------- 序列变换 ----------

def transform(raw: pd.Series, ind: Indicator, round_values: bool = True) -> pd.Series:
    """把 FRED 原始序列变成公布口径（环比 %、新增人数等）。"""
    if ind.transform == "level":
        out = raw.copy()
    elif ind.transform == "pct_mom":
        out = 100.0 * (raw / raw.shift(1) - 1.0)
    elif ind.transform == "diff":
        out = raw - raw.shift(1)
    else:  # pragma: no cover - 配置加载时已校验
        raise ValueError(ind.transform)
    out = (out * ind.scale).dropna()
    if round_values:
        out = out.round(ind.decimals)
    return out


def revision(old_raw: pd.Series, new_raw: pd.Series, ind: Indicator, periods: Iterable[pd.Timestamp]) -> float:
    """前值修正合计（公布口径）。例如非农前两月合计下修 8 万，返回 -80。

    old_raw 是上次看到的原始序列，new_raw 是本次的。只比较两边都有的期间。
    """
    old_t = transform(old_raw, ind, round_values=False)
    new_t = transform(new_raw, ind, round_values=False)
    total = 0.0
    for p in periods:
        if p in old_t.index and p in new_t.index:
            total += float(new_t[p] - old_t[p])
    return round(total, ind.decimals)


# ---------- 公布日期 ----------

def period_end(period: pd.Timestamp, frequency: str) -> pd.Timestamp:
    if frequency == "monthly":
        return period + pd.offsets.MonthEnd(0)
    if frequency == "quarterly":
        return period + pd.offsets.QuarterEnd(0)
    return period  # weekly：FRED 的日期就是周结束日


def release_date_for(period: pd.Timestamp, frequency: str, release_dates: list[pd.Timestamp]) -> Optional[pd.Timestamp]:
    """该期数据的首次公布日 = 期末之后的第一个公布日。"""
    end = period_end(period, frequency)
    for d in release_dates:  # 已升序
        if d > end:
            return d
    return None


def period_label(period: pd.Timestamp, frequency: str) -> str:
    return period.strftime("%Y-%m") if frequency in ("monthly", "quarterly") else period.strftime("%Y-%m-%d")


# ---------- 意外的标准差 ----------

@dataclass
class StdEstimate:
    value: float
    method: str  # "history"（历史意外） 或 "naive"（序列自身波动，偏保守）
    n: int


def surprise_std(ind: Indicator, past_surprises: Iterable[float], series_t: pd.Series, min_history: int) -> StdEstimate:
    """估计这个指标"一个标准差的意外"有多大。

    优先用该指标过去的真实意外（实际 - 预期）算标准差。
    历史不够时退回"朴素预测误差"：用上一期值当预测的误差标准差。
    朴素误差通常比专业预期误差大，所以算出的 z 偏保守（更不容易误报）。
    """
    floor = 0.5 * 10 ** (-ind.decimals)  # 不能小于公布精度的一半，避免除以极小数
    hist = np.array([x for x in past_surprises if x is not None and not math.isnan(x)], dtype=float)
    if len(hist) >= min_history:
        return StdEstimate(max(float(np.std(hist, ddof=1)), floor), "history", len(hist))
    naive_err = series_t.diff().dropna().tail(60)
    if len(naive_err) < 3:
        return StdEstimate(max(abs(float(series_t.iloc[-1])) * 0.1 if len(series_t) else 1.0, floor), "naive", 0)
    return StdEstimate(max(float(naive_err.std(ddof=1)), floor), "naive", len(naive_err))


# ---------- 单次事件 ----------

@dataclass
class Surprise:
    raw: float       # 实际 - 预期 + 修正
    z: float
    hawk_z: float
    std: StdEstimate


def compute_surprise(ind: Indicator, actual: float, consensus: float, std: StdEstimate, revision_adj: float = 0.0) -> Surprise:
    raw = round(actual - consensus + (revision_adj if ind.revisions else 0.0), ind.decimals + 2)
    z = raw / std.value
    return Surprise(raw=raw, z=round(z, 2) + 0.0, hawk_z=round(z * ind.hawkish_sign, 2) + 0.0, std=std)


def label(hawk_z: float, threshold: float) -> str:
    if hawk_z >= threshold:
        return "鹰派意外"
    if hawk_z <= -threshold:
        return "鸽派意外"
    if abs(hawk_z) >= threshold / 2:
        return "轻度" + ("偏鹰" if hawk_z > 0 else "偏鸽")
    return "符合预期"


# ---------- 市场验证 ----------

def market_confirmation(hawk_z: float, yield_bp: Optional[float], min_bp: float = 2.0) -> str:
    """看 2 年美债有没有朝"意外"的方向走：鹰派意外 → 收益率应上行。"""
    if yield_bp is None or (isinstance(yield_bp, float) and math.isnan(yield_bp)):
        return "待收盘"
    if abs(hawk_z) < 0.5:
        return "-"
    if abs(yield_bp) < min_bp:
        return "市场无反应"
    return "市场确认" if np.sign(yield_bp) == np.sign(hawk_z) else "市场不买账"


# ---------- 合成意外指数 ----------

def composite_index(events: pd.DataFrame, weights: dict[str, float], half_life_days: float,
                    dates: Optional[pd.DatetimeIndex] = None) -> pd.Series:
    """按时间衰减加权的平均鹰派 z。>0 表示近期数据整体强于预期（偏鹰），<0 偏鸽。

    events 需要列：release_date, indicator, hawk_z
    """
    ev = events.dropna(subset=["hawk_z", "release_date"]).copy()
    if ev.empty:
        return pd.Series(dtype=float)
    ev["release_date"] = pd.to_datetime(ev["release_date"])
    ev["w"] = ev["indicator"].map(weights).fillna(1.0)
    if dates is None:
        dates = pd.date_range(ev["release_date"].min(), ev["release_date"].max(), freq="D")
    rd = ev["release_date"].values
    hz = ev["hawk_z"].values.astype(float)
    w = ev["w"].values.astype(float)
    out = []
    for d in dates:
        mask = rd <= np.datetime64(d)
        if not mask.any():
            out.append(np.nan)
            continue
        age = (np.datetime64(d) - rd[mask]).astype("timedelta64[D]").astype(float)
        decay = 0.5 ** (age / half_life_days)
        ww = w[mask] * decay
        out.append(float((ww * hz[mask]).sum() / ww.sum()))
    return pd.Series(out, index=dates, name="surprise_index")


# ---------- 历史同类事件 ----------

@dataclass
class AnalogStats:
    n: int
    yield_bp: float
    spx_pct: float
    ndx_pct: float
    spx_down_rate: float


def analogs(events: pd.DataFrame, hawk_z: float, threshold: float, before: Optional[pd.Timestamp] = None,
            indicator: Optional[str] = None) -> Optional[AnalogStats]:
    """找历史上同方向、同等强度的意外，统计当天 2 年美债和美股的平均表现。

    indicator 给定时只看同一指标；否则看所有指标。
    """
    if abs(hawk_z) < threshold:
        return None
    ev = events.dropna(subset=["hawk_z", "yield_2y_bp", "spx_pct"]).copy()
    if before is not None:
        ev = ev[pd.to_datetime(ev["release_date"]) < before]
    if indicator:
        ev = ev[ev["indicator"] == indicator]
    same = ev[(np.sign(ev["hawk_z"]) == np.sign(hawk_z)) & (ev["hawk_z"].abs() >= threshold)]
    if same.empty:
        return AnalogStats(0, float("nan"), float("nan"), float("nan"), float("nan"))
    return AnalogStats(
        n=len(same),
        yield_bp=round(float(same["yield_2y_bp"].mean()), 1),
        spx_pct=round(float(same["spx_pct"].mean()), 2),
        ndx_pct=round(float(same["ndx_pct"].mean()), 2) if "ndx_pct" in same and same["ndx_pct"].notna().any() else float("nan"),
        spx_down_rate=round(float((same["spx_pct"] < 0).mean()), 2),
    )
