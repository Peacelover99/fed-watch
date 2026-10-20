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
    print(f"处理 {rep.processed} 条；推送 {len(rep.alerts)} 条")
    for e in rep.errors:
        print("  错误:", e)
    if rep.errors and rep.processed == 0:
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
    # 所有指标都失败才算失败，让 Actions 标红
    return 1 if rep.errors and rep.processed == 0 else 0


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
    chs = notify.channels()
    if not chs:
        print("没有配置任何推送渠道，请设置环境变量（见 README）")
        return 1
    res = notify.send("✅ Fed Watch 推送测试", "如果你看到这条消息，说明推送渠道配置成功。")
    print(res)
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
