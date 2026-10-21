"""命令行入口：python -m fedwatch <命令>

  run        抓取最新数据，计算预期差，推送提醒，更新面板（GitHub Actions 定时跑的就是它）
  backfill   用 consensus.csv 里的历史预期回填事件（不推送），积累历史统计
  dashboard  只重新生成面板 docs/index.html
  demo       用模拟数据离线跑一遍，生成 docs/demo.html
  test-notify  发一条测试消息，检查推送渠道是否配置正确
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

from . import notify
from .config import DATA_DIR, DOCS_DIR, load_config
from .dashboard import build_dashboard
from .pipeline import run
from .store import EventStore, load_consensus


def _today_et() -> pd.Timestamp:
    return pd.Timestamp.now(tz="America/New_York").normalize().tz_localize(None)


def _print_report(rep) -> None:
    import os
    print(f"处理 {rep.processed} 条；推送 {len(rep.alerts)} 条")
    for e in rep.errors:
        print("  错误:", e)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        # 错误显示在 Actions 运行页面的 Annotations 里，不用点进日志
        level = "warning" if rep.only_transient else "error"
        if rep.only_transient:
            print("::warning title=Fed Watch::FRED 暂时不可用，本轮跳过，下一轮会自动重试（数据不会丢）")
        for e in rep.errors:
            print(f"::{level} title=Fed Watch::{e}")
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(f"### Fed Watch\n\n处理 {rep.processed} 条，推送 {len(rep.alerts)} 条\n\n")
                for a in rep.alerts:
                    f.write(f"- {a}\n")
                if rep.errors:
                    f.write("\n**错误**\n\n" + "".join(f"- {e}\n" for e in rep.errors))
    if rep.only_transient:
        print("（FRED 暂时不可用，下一轮会自动重试）")
    elif rep.errors and rep.processed == 0:
        print("（全部失败，请检查网络或 FRED_API_KEY）")
    elif rep.errors:
        print("（部分指标失败，其余已正常处理）")


def cmd_run(args) -> int:
    from .fred import FredClient
    cfg = load_config()
    store = EventStore()
    rep = run(FredClient(), cfg, store, load_consensus(), _today_et(), lookback=args.lookback,
              send=None if args.dry_run else notify.send)
    store.save()
    build_dashboard(store.df, cfg, DOCS_DIR / "index.html")
    _print_report(rep)
    _outage_watch(rep, None if args.dry_run else notify.send)
    # FRED 临时故障不算失败（下一轮自动重试，避免 GitHub 反复发失败邮件）；
    # 配置或代码问题导致全部失败时才让 Actions 标红
    if rep.errors and rep.processed == 0 and not rep.only_transient:
        return 1
    return 0


def _outage_watch(rep, send) -> None:
    """FRED 连续故障超过 3 小时，推送一次提醒；恢复后再推送一次。状态存在 data/state.json。"""
    import json
    path = DATA_DIR / "state.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError:
        state = {}
    now = pd.Timestamp.now(tz="UTC")
    down = rep.processed == 0 and rep.only_transient
    since = state.get("fred_down_since")
    changed = False
    if down:
        if not since:
            state["fred_down_since"], changed = now.isoformat(), True
        elif not state.get("fred_down_notified") and now - pd.Timestamp(since) > pd.Timedelta(hours=3):
            if send:
                send("⚠️ FRED 数据源连续故障",
                     f"自 {pd.Timestamp(since).tz_convert('Asia/Shanghai'):%m-%d %H:%M}（北京时间）起无法获取数据，"
                     "期间公布的数据暂时无法提醒。恢复后会自动补算并推送。")
            state["fred_down_notified"], changed = True, True
    elif since and rep.processed > 0:
        if state.get("fred_down_notified") and send:
            send("✅ FRED 数据源已恢复", "已恢复正常抓取，故障期间公布的数据会按正常流程补算。")
        state, changed = {k: v for k, v in state.items() if not k.startswith("fred_down")}, True
    if changed:
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_backfill(args) -> int:
    from .fred import FredClient
    cfg = load_config()
    store = EventStore()
    rep = run(FredClient(), cfg, store, load_consensus(), _today_et(), lookback=args.periods, send=None)
    store.save()
    build_dashboard(store.df, cfg, DOCS_DIR / "index.html")
    _print_report(rep)
    return 0


def cmd_dashboard(args) -> int:
    cfg = load_config()
    out = build_dashboard(EventStore().df, cfg, DOCS_DIR / "index.html")
    print("面板已生成:", out)
    return 0


def cmd_demo(args) -> int:
    from .demo import DemoSource
    cfg = load_config()
    src = DemoSource(cfg, end=args.end)
    tmp = Path(tempfile.mkdtemp())
    store = EventStore(tmp / "events.csv")
    cons = src.consensus_frame()
    today = pd.Timestamp(args.end)
    # 先回填历史（不推送），再模拟"今天"的运行（会推送到控制台）
    run(src, cfg, store, cons, today - pd.Timedelta(days=30), lookback=500, send=None, save_snapshots=False)
    rep = run(src, cfg, store, cons, today, lookback=3, send=notify.send if args.notify else _console,
              save_snapshots=False)
    store.save()
    out = build_dashboard(store.df, cfg, DOCS_DIR / "demo.html", demo=True, today=today)
    print(f"\n演示事件表: {store.path}\n演示面板: {out}")
    _print_report(rep)
    return 0


def _console(title: str, body: str) -> dict:
    print(f"\n===== [演示推送] {title} =====\n{body}\n")
    return {"console": "ok"}


def cmd_test_notify(args) -> int:
    import os
    gha = os.environ.get("GITHUB_ACTIONS") == "true"
    chs = notify.channels()
    if not chs:
        msg = "没有配置任何推送渠道：请在仓库 Settings → Secrets 添加 SERVERCHAN_KEY 等（见 README）"
        print(f"::error title=推送测试::{msg}" if gha else msg)
        return 1
    # 用最近一次真实事件生成一条样例提醒，让你看到正式推送的样子
    from .pipeline import format_alert
    cfg = load_config()
    df = EventStore().df
    scored = df.dropna(subset=["hawk_z"]).sort_values("release_date")
    if not scored.empty:
        r = scored.iloc[-1].to_dict()
        ind = cfg.indicators[r["indicator"]]
        title, body = format_alert(ind, r, cfg, df)
        res = notify.send("[样例] " + title, "以下是用最近一次数据生成的样例，并非实时提醒。\n\n" + body)
    else:
        res = notify.send("✅ Fed Watch 推送测试", "如果你看到这条消息，说明推送渠道配置成功。")
    for ch, v in res.items():
        line = f"{ch}: {v}"
        if gha:
            print(f"::{'notice' if v == 'ok' else 'error'} title=推送测试::{line}")
        print(line)
    return 0 if all(v == "ok" for v in res.values()) else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="fedwatch", description="美联储预期差监控")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="抓取最新数据并推送")
    r.add_argument("--lookback", type=int, default=3, help="每个指标检查最近几期（默认 3）")
    r.add_argument("--dry-run", action="store_true", help="只打印，不推送")
    r.set_defaults(fn=cmd_run)
    b = sub.add_parser("backfill", help="回填历史事件（不推送）")
    b.add_argument("--periods", type=int, default=120, help="每个指标回填多少期")
    b.set_defaults(fn=cmd_backfill)
    sub.add_parser("dashboard", help="重新生成面板").set_defaults(fn=cmd_dashboard)
    d = sub.add_parser("demo", help="模拟数据离线演示")
    d.add_argument("--end", default="2026-10-16")
    d.add_argument("--notify", action="store_true", help="演示推送也发到真实渠道")
    d.set_defaults(fn=cmd_demo)
    sub.add_parser("test-notify", help="测试推送渠道").set_defaults(fn=cmd_test_notify)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
