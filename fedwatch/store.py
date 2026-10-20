"""用 CSV 存储（方便在 GitHub 上直接查看 diff，也不需要数据库）。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from .config import DATA_DIR

EVENT_COLUMNS = [
    "indicator", "name", "period", "release_date", "detected_at",
    "actual", "consensus", "consensus_source", "revision", "surprise",
    "std", "std_method", "z", "hawk_z", "label",
    "yield_2y_bp", "spx_pct", "ndx_pct", "confirmation", "alerted",
]


# ---------- 一致预期 ----------

def load_consensus(path: Path = DATA_DIR / "consensus.csv") -> pd.DataFrame:
    """读取手工录入的一致预期。period 统一成 YYYY-MM 或 YYYY-MM-DD 字符串。"""
    if not path.exists():
        return pd.DataFrame(columns=["indicator", "period", "consensus", "source", "note"])
    df = pd.read_csv(path, comment="#", dtype={"period": str, "indicator": str})
    df = df.dropna(subset=["indicator", "period", "consensus"])
    df["indicator"] = df["indicator"].str.strip()
    df["period"] = df["period"].str.strip()
    df["consensus"] = pd.to_numeric(df["consensus"], errors="coerce")
    return df.dropna(subset=["consensus"])


def find_consensus(cons: pd.DataFrame, indicator: str, period_label: str) -> Optional[tuple[float, str]]:
    row = cons[(cons["indicator"] == indicator) & (cons["period"] == period_label)]
    if row.empty:
        return None
    r = row.iloc[-1]
    src = r.get("source")
    return float(r["consensus"]), (str(src) if isinstance(src, str) else "")


# ---------- 事件表 ----------

class EventStore:
    def __init__(self, path: Path = DATA_DIR / "events.csv"):
        self.path = path
        if path.exists():
            self.df = pd.read_csv(path, dtype={"period": str})
            for c in EVENT_COLUMNS:
                if c not in self.df.columns:
                    self.df[c] = pd.NA
            self.df = self.df[EVENT_COLUMNS]
        else:
            self.df = pd.DataFrame(columns=EVENT_COLUMNS)

    def get(self, indicator: str, period: str) -> Optional[dict]:
        m = (self.df["indicator"] == indicator) & (self.df["period"] == period)
        if not m.any():
            return None
        return self.df[m].iloc[-1].to_dict()

    def upsert(self, row: dict) -> None:
        m = (self.df["indicator"] == row["indicator"]) & (self.df["period"] == row["period"])
        if m.any():
            idx = self.df[m].index[-1]
            for k, v in row.items():
                self.df.at[idx, k] = v
        else:
            full = {c: row.get(c, pd.NA) for c in EVENT_COLUMNS}
            new = pd.DataFrame([full], columns=EVENT_COLUMNS)
            self.df = new if self.df.empty else pd.concat([self.df, new], ignore_index=True)

    def past_surprises(self, indicator: str, before_period: str) -> list[float]:
        d = self.df[(self.df["indicator"] == indicator) & (self.df["period"] < before_period)]
        return pd.to_numeric(d["surprise"], errors="coerce").dropna().tolist()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        out = self.df.sort_values(["release_date", "indicator"], na_position="last")
        out.to_csv(self.path, index=False)


# ---------- 原始序列快照（用于计算前值修正） ----------

def snapshot_path(series_id: str) -> Path:
    return DATA_DIR / "snapshots" / f"{series_id}.csv"


def load_snapshot(series_id: str) -> Optional[pd.Series]:
    p = snapshot_path(series_id)
    if not p.exists():
        return None
    df = pd.read_csv(p, parse_dates=["date"])
    return pd.Series(df["value"].values, index=df["date"], name=series_id)


def save_snapshot(series: pd.Series, keep: int = 36) -> None:
    p = snapshot_path(str(series.name))
    p.parent.mkdir(parents=True, exist_ok=True)
    s = series.tail(keep)
    pd.DataFrame({"date": s.index.strftime("%Y-%m-%d"), "value": s.values}).to_csv(p, index=False)
