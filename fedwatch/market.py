"""公布当天的市场反应：2 年美债变动（bp）、标普 / 纳指涨跌（%）。

美国经济数据多在美东 8:30 开盘前公布，所以"当天收盘 vs 前一日收盘"基本就是对这条数据的反应
（同一天如有其他重大事件会混在一起，统计时要心里有数）。
"""
from __future__ import annotations

from typing import Optional

import pandas as pd


def _day_change(s: pd.Series, day: pd.Timestamp) -> Optional[tuple[float, float]]:
    """返回 (当日值, 前一交易日值)。公布日不是交易日时用之后第一个交易日。"""
    if s is None or s.empty:
        return None
    after = s[s.index >= day]
    before = s[s.index < day]
    if after.empty or before.empty:
        return None
    first_day = after.index[0]
    if (first_day - day).days > 4:  # 数据还没更新到这一天
        return None
    return float(after.iloc[0]), float(before.iloc[-1])


def yield_change_bp(yields: pd.Series, day: pd.Timestamp) -> Optional[float]:
    v = _day_change(yields, day)
    return None if v is None else round((v[0] - v[1]) * 100, 1)


def pct_change(prices: pd.Series, day: pd.Timestamp) -> Optional[float]:
    v = _day_change(prices, day)
    return None if v is None else round((v[0] / v[1] - 1) * 100, 2)
