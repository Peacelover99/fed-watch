import unittest

import pandas as pd

from fedwatch import market as mkt
from fedwatch import surprise as sp
from fedwatch.config import load_config


class SurpriseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config()
        cls.cpi = cls.cfg.indicators["core_cpi"]
        cls.nfp = cls.cfg.indicators["nfp"]
        cls.unrate = cls.cfg.indicators["unrate"]

    def test_pct_mom_transform_rounds(self):
        raw = pd.Series([100.0, 100.349, 100.5], index=pd.date_range("2026-01-01", periods=3, freq="MS"))
        t = sp.transform(raw, self.cpi)
        self.assertEqual(list(t.values), [0.3, 0.2])

    def test_hawkish_sign(self):
        std = sp.StdEstimate(0.1, "history", 10)
        s = sp.compute_surprise(self.cpi, 0.5, 0.3, std)
        self.assertAlmostEqual(s.z, 2.0)
        self.assertAlmostEqual(s.hawk_z, 2.0)
        # 失业率高于预期 = 偏鸽
        s2 = sp.compute_surprise(self.unrate, 4.3, 4.1, sp.StdEstimate(0.1, "history", 10))
        self.assertLess(s2.hawk_z, 0)

    def test_revision_counts_for_payrolls(self):
        idx = pd.date_range("2026-06-01", periods=4, freq="MS")
        old = pd.Series([1000, 1100, 1200], index=idx[:3], dtype=float)       # 7月+100, 8月+100
        new = pd.Series([1000, 1050, 1150, 1300], index=idx, dtype=float)     # 7月+50, 8月+100, 9月+150
        rev = sp.revision(old, new, self.nfp, idx[1:3])
        self.assertEqual(rev, -50)
        s = sp.compute_surprise(self.nfp, 150, 150, sp.StdEstimate(50, "history", 10), rev)
        self.assertEqual(s.raw, -50)  # 符合预期但前值下修 → 偏弱

    def test_std_fallback_and_floor(self):
        t = pd.Series([0.3] * 20, index=pd.date_range("2024-01-01", periods=20, freq="MS"))
        est = sp.surprise_std(self.cpi, [], t, min_history=6)
        self.assertEqual(est.method, "naive")
        self.assertGreaterEqual(est.value, 0.05)  # 精度下限
        est2 = sp.surprise_std(self.cpi, [0.1, -0.1, 0.0, 0.1, -0.1, 0.0], t, min_history=6)
        self.assertEqual(est2.method, "history")

    def test_release_date_mapping(self):
        rd = [pd.Timestamp(d) for d in ["2026-09-11", "2026-10-14", "2026-11-12"]]
        self.assertEqual(sp.release_date_for(pd.Timestamp("2026-09-01"), "monthly", rd), pd.Timestamp("2026-10-14"))
        self.assertIsNone(sp.release_date_for(pd.Timestamp("2026-11-01"), "monthly", rd))

    def test_market_confirmation(self):
        self.assertEqual(sp.market_confirmation(2.0, 8.0), "市场确认")
        self.assertEqual(sp.market_confirmation(2.0, -8.0), "市场不买账")
        self.assertEqual(sp.market_confirmation(2.0, 1.0), "市场无反应")
        self.assertEqual(sp.market_confirmation(2.0, None), "待收盘")

    def test_market_change(self):
        days = pd.bdate_range("2026-10-12", periods=4)
        y = pd.Series([3.50, 3.60, 3.55, 3.70], index=days)
        self.assertEqual(mkt.yield_change_bp(y, days[1]), 10.0)
        self.assertIsNone(mkt.yield_change_bp(y, days[-1] + pd.Timedelta(days=10)))

    def test_composite_index_decay(self):
        ev = pd.DataFrame({
            "release_date": ["2026-01-01", "2026-03-01"], "indicator": ["core_cpi", "core_cpi"], "hawk_z": [2.0, -2.0]})
        ci = sp.composite_index(ev, {"core_cpi": 1}, 30, pd.DatetimeIndex(["2026-01-01", "2026-03-01"]))
        self.assertAlmostEqual(ci.iloc[0], 2.0)
        self.assertLess(ci.iloc[1], 0)  # 新事件权重更大

    def test_analogs(self):
        ev = pd.DataFrame({
            "release_date": ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"],
            "indicator": ["cpi"] * 4, "hawk_z": [2.0, 1.8, -2.0, 2.5],
            "yield_2y_bp": [10, 6, -8, 12], "spx_pct": [-1.0, 0.5, 1.0, -2.0], "ndx_pct": [-1.5, 0.2, 1.2, -3.0]})
        st = sp.analogs(ev, 2.2, 1.5, before=pd.Timestamp("2026-04-01"))
        self.assertEqual(st.n, 2)
        self.assertEqual(st.yield_bp, 8.0)
        self.assertIsNone(sp.analogs(ev, 0.5, 1.5))


class DemoPipelineTest(unittest.TestCase):
    def test_demo_runs_end_to_end(self):
        import tempfile
        from pathlib import Path
        from fedwatch.demo import DemoSource
        from fedwatch.pipeline import run
        from fedwatch.store import EventStore
        from fedwatch.dashboard import build_dashboard

        cfg = load_config()
        src = DemoSource(cfg, end="2026-10-16")
        tmp = Path(tempfile.mkdtemp())
        store = EventStore(tmp / "events.csv")
        sent = []
        run(src, cfg, store, src.consensus_frame(), pd.Timestamp("2026-09-16"), lookback=500, send=None, save_snapshots=False)
        rep = run(src, cfg, store, src.consensus_frame(), pd.Timestamp("2026-10-16"), lookback=3,
                  send=lambda t, b: sent.append(t) or {}, save_snapshots=False)
        self.assertFalse(rep.errors)
        self.assertTrue(sent)
        # 再跑一次不应重复推送
        sent.clear()
        run(src, cfg, store, src.consensus_frame(), pd.Timestamp("2026-10-16"), lookback=3,
            send=lambda t, b: sent.append(t) or {}, save_snapshots=False)
        self.assertEqual(sent, [])
        out = build_dashboard(store.df, cfg, tmp / "d.html", demo=True, today=pd.Timestamp("2026-10-16"))
        self.assertIn("预期差", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
