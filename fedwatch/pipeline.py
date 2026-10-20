"""主流程：抓数据 → 算预期差 → 补市场反应 → 推送。

数据源只要实现 series(id, start) 和 release_dates(id) 两个方法即可（真实用 FredClient，演示用 DemoSource）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol

import pandas as pd

from . import market as mkt
from . import surprise as sp
from .config import Config, Indicator
from .store import EventStore, find_consensus, load_snapshot, save_snapshot


class Source(Protocol):
    def series(self, series_id: str, start: str = ...) -> pd.Series: ...
    def release_dates(self, series_id: str) -> list[pd.Timestamp]: ...


Sender = Callable[[str, str], dict]


@dataclass
class RunReport:
    processed: int = 0
    alerts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    missing_consensus: list[str] = field(default_factory=list)


def _isnum(x) -> bool:
    try:
        return x is not None and not pd.isna(x) and not (isinstance(x, float) and math.isnan(x))
    except (TypeError, ValueError):
        return False


def _fmt(v: float, ind: Indicator, signed: bool = False) -> str:
    s = f"{v:+.{ind.decimals}f}" if signed else f"{v:.{ind.decimals}f}"
    return s + ("%" if ind.unit == "%" else ind.unit)


# ---------- 推送文案 ----------

def format_alert(ind: Indicator, row: dict, cfg: Config, events: pd.DataFrame) -> tuple[str, str]:
    thr = cfg.settings.alert_threshold_z
    hz = float(row["hawk_z"])
    big = abs(hz) >= thr
    icon = ("🔴" if hz > 0 else "🟢") if big else "⚪"
    title = f"{icon} {ind.name} {row['label']} {hz:+.1f}σ"

    lines = [
        f"**{ind.name}**（{row['period']}）",
        f"实际 {_fmt(row['actual'], ind)}，预期 {_fmt(row['consensus'], ind)}"
        + (f"（来源：{row['consensus_source']}）" if row.get("consensus_source") else ""),
    ]
    if ind.revisions and _isnum(row.get("revision")) and row["revision"] != 0:
        lines.append(f"前值修正合计 {_fmt(row['revision'], ind, signed=True)}，已计入意外")
    lines.append(f"意外 {_fmt(row['surprise'], ind, signed=True)} = **{row['z']:+.2f}σ** → 鹰派 z **{hz:+.2f}**")
    if row.get("std_method") == "naive":
        lines.append("（该指标历史预期记录不足，标准差用序列自身波动估算，z 值偏保守）")

    rd = row.get("release_date")
    before = pd.Timestamp(rd) if isinstance(rd, str) else None
    same = sp.analogs(events, hz, thr, before=before, indicator=ind.key)
    allk = sp.analogs(events, hz, thr, before=before)
    for tag, st in (("同指标", same), ("所有指标", allk)):
        if st is not None and st.n >= cfg.settings.analog_min_count:
            lines.append(
                f"历史{tag}同类意外 {st.n} 次：2年美债平均 {st.yield_bp:+.1f}bp，"
                f"标普 {st.spx_pct:+.2f}%（下跌概率 {st.spx_down_rate:.0%}）"
                + (f"，纳指 {st.ndx_pct:+.2f}%" if not math.isnan(st.ndx_pct) else "")
            )
            break
    else:
        if big:
            lines.append("历史同类事件样本不足，暂无统计（录入的预期越多，这里越有用）")
    lines.append("市场反应会在收盘后补上并更新面板。")
    lines.append("_仅供参考，不构成投资建议_")
    return title, "\n\n".join(lines)


def format_market_followup(ind: Indicator, row: dict) -> tuple[str, str]:
    title = f"📊 {ind.name} 收盘反应：{row['confirmation']}"
    body = (
        f"**{ind.name}**（{row['period']}）鹰派 z {float(row['hawk_z']):+.2f}\n\n"
        f"2年美债 {float(row['yield_2y_bp']):+.1f}bp，标普 {float(row['spx_pct']):+.2f}%"
        + (f"，纳指 {float(row['ndx_pct']):+.2f}%" if _isnum(row.get("ndx_pct")) else "")
        + f"\n\n判断：**{row['confirmation']}**"
        + ("\n\n市场反应与数据意外方向相反，可能已提前定价，或市场更关注其他因素。" if row["confirmation"] == "市场不买账" else "")
    )
    return title, body


# ---------- 主流程 ----------

def process_indicator(ind: Indicator, src: Source, store: EventStore, cons: pd.DataFrame, cfg: Config,
                      today: pd.Timestamp, lookback: int, send: Optional[Sender], report: RunReport,
                      save_snapshots: bool = True) -> None:
    raw = src.series(ind.fred_id, start=cfg.settings.history_start)
    if raw.empty:
        report.errors.append(f"{ind.key}: 没有数据")
        return
    t = sp.transform(raw, ind)
    rdates = src.release_dates(ind.fred_id)
    old_raw = load_snapshot(ind.fred_id) if save_snapshots else None

    periods = list(t.index[-lookback:])
    latest = t.index[-1]
    for p in periods:
        label = sp.period_label(p, ind.frequency)
        existing = store.get(ind.key, label)
        c = find_consensus(cons, ind.key, label)
        # 实际值以"首次公布值"为准：手工填了就用手工值；否则沿用第一次抓到的值，
        # 避免下个月数据被修正后，历史意外被悄悄改掉
        if c is not None and c.get("actual") is not None:
            actual = c["actual"]
        elif existing is not None and _isnum(existing.get("actual")):
            actual = float(existing["actual"])
        else:
            actual = float(t[p])

        # 公布日：有 API key 时用官方日期；否则只有"和上次快照相比新出现的数据"才算今天公布。
        # 第一次运行（还没有快照）只做初始化，不把已有数据误当成今天的新数据。
        rel = sp.release_date_for(p, ind.frequency, rdates) if rdates else None
        is_new = old_raw is not None and p not in old_raw.index
        if rel is None:
            if existing is not None and isinstance(existing.get("release_date"), str):
                rel = pd.Timestamp(existing["release_date"])
            elif p == latest and is_new:
                rel = today
        fresh = rel is not None and (today - rel).days <= 3 and rel <= today

        # 前值修正：只在新数据公布时、且有上次快照时可算
        rev = 0.0
        if c is not None and c.get("revision") is not None:
            rev = c["revision"]
        elif ind.revisions and is_new and old_raw is not None:
            prior = [x for x in t.index if x < p][-2:]
            rev = sp.revision(old_raw, raw, ind, prior)
        elif existing is not None and _isnum(existing.get("revision")):
            rev = float(existing["revision"])

        row = {
            "indicator": ind.key, "name": ind.name, "period": label,
            "release_date": rel.strftime("%Y-%m-%d") if rel is not None else pd.NA,
            "detected_at": existing["detected_at"] if existing else today.strftime("%Y-%m-%d"),
            "actual": actual, "revision": rev,
        }

        if c is None:
            row.update({"consensus": pd.NA, "label": "未录入预期"})
            if fresh and (existing is None or str(existing.get("alerted")) != "missing_notified"):
                report.missing_consensus.append(f"{ind.name} {label}")
                row["alerted"] = "missing_notified"
        else:
            past = store.past_surprises(ind.key, label)
            std = sp.surprise_std(ind, past, t[t.index < p], cfg.settings.min_history)
            s = sp.compute_surprise(ind, actual, c["consensus"], std, rev)
            row.update({
                "consensus": c["consensus"], "consensus_source": c["source"], "surprise": s.raw,
                "std": round(std.value, 4), "std_method": std.method,
                "z": s.z, "hawk_z": s.hawk_z, "label": sp.label(s.hawk_z, cfg.settings.alert_threshold_z),
            })

        already = existing is not None and str(existing.get("alerted")) in ("True", "true", "1", "sent")
        store.upsert(row)
        report.processed += 1

        if c is not None and not already:
            if fresh:
                big = abs(row["hawk_z"]) >= cfg.settings.alert_threshold_z
                if (big or cfg.settings.notify_minor) and send is not None:
                    title, body = format_alert(ind, store.get(ind.key, label), cfg, store.df)
                    send(title, body)
                    report.alerts.append(title)
                store.upsert({"indicator": ind.key, "period": label, "alerted": "sent"})
            else:
                store.upsert({"indicator": ind.key, "period": label, "alerted": "backfill"})

    if save_snapshots:
        save_snapshot(raw)


def refresh_market(store: EventStore, src: Source, cfg: Config, send: Optional[Sender], report: RunReport) -> None:
    """为还没有市场反应的事件补上 2 年美债和股指当日变动。"""
    df = store.df
    need = df[df["release_date"].notna() & df["yield_2y_bp"].isna()]
    if need.empty:
        return
    start = (pd.to_datetime(need["release_date"]).min() - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    m = cfg.market
    y2 = src.series(m["yield_2y"], start=start)
    spx = src.series(m["sp500"], start=start)
    ndx = src.series(m["nasdaq"], start=start)
    for idx, r in need.iterrows():
        day = pd.Timestamp(r["release_date"])
        bp = mkt.yield_change_bp(y2, day)
        if bp is None:
            continue
        upd = {
            "indicator": r["indicator"], "period": r["period"], "yield_2y_bp": bp,
            "spx_pct": mkt.pct_change(spx, day), "ndx_pct": mkt.pct_change(ndx, day),
        }
        hz = r["hawk_z"]
        upd["confirmation"] = sp.market_confirmation(float(hz), bp) if _isnum(hz) else "-"
        store.upsert(upd)
        # 刚推送过的大意外，收盘后补一条"市场是否认同"
        if send is not None and str(r.get("alerted")) == "sent" and _isnum(hz) \
                and abs(float(hz)) >= cfg.settings.alert_threshold_z:
            ind = cfg.indicators.get(r["indicator"])
            if ind:
                title, body = format_market_followup(ind, store.get(r["indicator"], r["period"]))
                send(title, body)
                report.alerts.append(title)


def run(src: Source, cfg: Config, store: EventStore, cons: pd.DataFrame, today: pd.Timestamp,
        lookback: int = 3, send: Optional[Sender] = None, save_snapshots: bool = True) -> RunReport:
    report = RunReport()
    for ind in cfg.indicators.values():
        try:
            process_indicator(ind, src, store, cons, cfg, today, lookback, send, report, save_snapshots)
        except Exception as e:  # noqa: BLE001 - 单个指标失败不影响其他
            report.errors.append(f"{ind.key}: {e}")
            print(f"[错误] {ind.key}: {e}")
    try:
        refresh_market(store, src, cfg, send, report)
    except Exception as e:  # noqa: BLE001
        report.errors.append(f"market: {e}")
        print(f"[错误] 市场数据: {e}")
    if report.missing_consensus and send is not None:
        send("⚠️ 有新数据但未录入预期",
             "以下数据已公布，但 data/consensus.csv 里没有对应预期值，无法计算意外：\n\n- "
             + "\n- ".join(report.missing_consensus))
    return report
