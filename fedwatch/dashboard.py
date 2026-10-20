"""生成静态面板（单个 HTML 文件，可直接放 GitHub Pages）。"""
from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from . import surprise as sp
from .config import Config

TEMPLATE = (Path(__file__).parent / "dashboard_template.html")


def _num(x) -> Optional[float]:
    try:
        v = float(x)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def build_payload(events: pd.DataFrame, cfg: Config, today: Optional[pd.Timestamp] = None) -> dict:
    ev = events.copy()
    ev["release_date"] = pd.to_datetime(ev["release_date"], errors="coerce")
    for c in ["actual", "consensus", "surprise", "z", "hawk_z", "yield_2y_bp", "spx_pct", "ndx_pct"]:
        ev[c] = pd.to_numeric(ev[c], errors="coerce")
    today = today or pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)
    ev = ev[ev["release_date"].isna() | (ev["release_date"] <= today)]
    scored = ev.dropna(subset=["hawk_z", "release_date"]).sort_values("release_date")
    thr = cfg.settings.alert_threshold_z
    weights = {k: i.weight for k, i in cfg.indicators.items()}

    # 合成意外指数：最近 3 年，按日
    idx_points = []
    if not scored.empty:
        start = max(scored["release_date"].min(), today - pd.DateOffset(years=3))
        dates = pd.date_range(start, today, freq="D")
        ci = sp.composite_index(scored, weights, cfg.settings.index_half_life_days, dates)
        idx_points = [[d.strftime("%Y-%m-%d"), round(v, 3)] for d, v in ci.items() if not math.isnan(v)]

    # 每个指标最新一次
    latest = []
    for key, ind in cfg.indicators.items():
        d = scored[scored["indicator"] == key]
        if d.empty:
            continue
        r = d.iloc[-1]
        latest.append({"key": key, "name": ind.name, "period": r["period"],
                       "date": r["release_date"].strftime("%Y-%m-%d"), "hawk_z": r["hawk_z"]})

    # 最近事件表
    recent = []
    for _, r in ev.dropna(subset=["release_date"]).sort_values("release_date", ascending=False).head(25).iterrows():
        ind = cfg.indicators.get(r["indicator"])
        if ind is None:
            continue
        unit = "%" if ind.unit == "%" else ind.unit
        f = lambda v, s=False: None if _num(v) is None else (f"{v:+.{ind.decimals}f}" if s and v != 0 else f"{abs(v) if v == 0 else v:.{ind.decimals}f}") + unit
        recent.append({
            "date": r["release_date"].strftime("%Y-%m-%d"), "name": ind.name, "period": r["period"],
            "actual": f(r["actual"]), "consensus": f(r["consensus"]), "surprise": f(r["surprise"], True),
            "hawk_z": _num(r["hawk_z"]), "label": r["label"] if isinstance(r["label"], str) else "",
            "y2": _num(r["yield_2y_bp"]), "spx": _num(r["spx_pct"]),
            "conf": r["confirmation"] if isinstance(r["confirmation"], str) else "",
        })

    # 散点：鹰派 z vs 2 年美债
    sc = scored.dropna(subset=["yield_2y_bp"]).tail(400)
    scatter = [{"z": round(float(r["hawk_z"]), 2), "bp": float(r["yield_2y_bp"]),
                "name": cfg.indicators[r["indicator"]].name if r["indicator"] in cfg.indicators else r["indicator"],
                "date": r["release_date"].strftime("%Y-%m-%d")} for _, r in sc.iterrows()]
    corr = None
    if len(sc) >= 10:
        corr = round(float(np.corrcoef(sc["hawk_z"], sc["yield_2y_bp"])[0, 1]), 2)

    # 历史同类意外统计（按指标）
    analog_rows = []
    for key, ind in cfg.indicators.items():
        d = scored[(scored["indicator"] == key)].dropna(subset=["yield_2y_bp", "spx_pct"])
        row = {"name": ind.name}
        for side, mask in (("hawk", d["hawk_z"] >= thr), ("dove", d["hawk_z"] <= -thr)):
            s = d[mask]
            row[side] = None if len(s) < cfg.settings.analog_min_count else {
                "n": int(len(s)), "bp": round(float(s["yield_2y_bp"].mean()), 1),
                "spx": round(float(s["spx_pct"].mean()), 2),
                "down": round(float((s["spx_pct"] < 0).mean()), 2)}
        analog_rows.append(row)

    # 指标卡
    last90 = scored[scored["release_date"] >= today - pd.Timedelta(days=90)]
    big = last90[last90["hawk_z"].abs() >= thr]
    bigm = scored[(scored["hawk_z"].abs() >= thr)].dropna(subset=["yield_2y_bp"])
    confirm_rate = None
    if len(bigm) >= 5:
        confirm_rate = round(float((np.sign(bigm["yield_2y_bp"]) == np.sign(bigm["hawk_z"])).mean()), 2)
    last = scored.iloc[-1] if not scored.empty else None
    return {
        "updated": pd.Timestamp.now(tz="Asia/Shanghai").strftime("%Y-%m-%d %H:%M"),
        "threshold": thr,
        "index_now": idx_points[-1][1] if idx_points else None,
        "index_30d_ago": idx_points[-31][1] if len(idx_points) > 31 else None,
        "last_event": None if last is None else {
            "name": cfg.indicators[last["indicator"]].name if last["indicator"] in cfg.indicators else last["indicator"],
            "date": last["release_date"].strftime("%Y-%m-%d"), "hawk_z": float(last["hawk_z"]),
            "label": last["label"]},
        "big90": {"hawk": int((big["hawk_z"] > 0).sum()), "dove": int((big["hawk_z"] < 0).sum())},
        "confirm_rate": confirm_rate, "confirm_n": int(len(bigm)),
        "index": idx_points, "latest": latest, "recent": recent,
        "scatter": scatter, "corr": corr, "analogs": analog_rows,
        "n_events": int(len(scored)),
    }


def build_dashboard(events: pd.DataFrame, cfg: Config, out: Path, demo: bool = False,
                    today: Optional[pd.Timestamp] = None) -> Path:
    payload = build_payload(events, cfg, today)
    payload["demo"] = demo
    data = json.dumps(payload, ensure_ascii=False, default=lambda o: None if o is pd.NA else str(o))
    data = data.replace("</", "<\\/")  # 防止数据里出现 </script>
    page = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", data)
    page = page.replace("__TITLE__", html.escape("Fed Watch 预期差面板" + ("（演示）" if demo else "")))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out
