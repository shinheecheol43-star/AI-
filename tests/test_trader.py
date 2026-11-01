"""자동매매 봇의 주문 흐름 시험 (가짜 거래소 DryRun 으로, 실제 주문 없음)."""
import unittest

import pandas as pd

from smc.bybit import DryRun
from smc.trader import cycle


def snap(rows, asof):
    x = pd.DataFrame(rows)
    x["key"] = x.symbol + "|" + x.src + "|" + x.entry.astype(str)
    return {"x": x, "asof": pd.Timestamp(asof, tz="UTC")}


T0 = pd.Timestamp("2026-11-02 04:00", tz="UTC")


def long_row(stop=78000.0, open_=True, entry=T0):
    return {"symbol": "BTC", "src": "스윙 롱", "side": 1, "entry": entry, "open": open_, "stop": stop, "p0": 80000.0, "stop_pct": 0.025}


class TraderFlow(unittest.TestCase):
    def setUp(self):
        self.ex = DryRun(1000.0)
        self.ex.prices = {"BTCUSDT": 80000.0, "ETHUSDT": 2300.0}
        self.state = {}

    def test_entry_places_market_and_stop(self):
        msgs = cycle(self.ex, self.state, snap([long_row()], "2026-11-02 05:00"))
        lot = next(iter(self.state["lots"].values()))
        # 리스크 0.5% = 5 USDT, 손절폭 2,000 → 0.0025 → 수량 단위 0.001 로 내림 → 0.002
        self.assertAlmostEqual(lot["qty"], 0.002)
        self.assertEqual(self.ex.position_size("BTCUSDT", 1), 0.002)
        self.assertEqual(self.ex.orders[lot["stop_id"]]["trigger"], 78000.0)
        self.assertTrue(any("진입" in m for m in msgs))

    def test_stale_signal_is_not_chased(self):
        cycle(self.ex, self.state, snap([long_row()], "2026-11-02 12:00"))
        self.assertEqual(self.state["lots"], {})
        self.assertEqual(self.ex.positions, {})

    def test_trailing_stop_is_amended_only_upward(self):
        cycle(self.ex, self.state, snap([long_row()], "2026-11-02 05:00"))
        cycle(self.ex, self.state, snap([long_row(stop=79000.0)], "2026-11-02 09:00"))
        lot = next(iter(self.state["lots"].values()))
        self.assertEqual(self.ex.orders[lot["stop_id"]]["trigger"], 79000.0)
        cycle(self.ex, self.state, snap([long_row(stop=78500.0)], "2026-11-02 13:00"))
        self.assertEqual(self.ex.orders[lot["stop_id"]]["trigger"], 79000.0)

    def test_model_exit_closes_position_and_cancels_stop(self):
        cycle(self.ex, self.state, snap([long_row()], "2026-11-02 05:00"))
        stop_id = next(iter(self.state["lots"].values()))["stop_id"]
        cycle(self.ex, self.state, snap([long_row(open_=False)], "2026-11-03 05:00"))
        self.assertEqual(self.state["lots"], {})
        self.assertEqual(self.ex.position_size("BTCUSDT", 1), 0.0)
        self.assertEqual(self.ex.orders[stop_id]["status"], "Cancelled")

    def test_exchange_stop_fill_is_not_reentered(self):
        cycle(self.ex, self.state, snap([long_row()], "2026-11-02 05:00"))
        self.ex.fill_stop(next(iter(self.state["lots"].values()))["stop_id"])
        msgs = cycle(self.ex, self.state, snap([long_row()], "2026-11-02 06:00"))
        self.assertEqual(self.state["lots"], {})
        self.assertTrue(any("손절 실행" in m for m in msgs))
        self.assertEqual(self.ex.position_size("BTCUSDT", 1), 0.0)

    def test_kill_switch_blocks_new_entries(self):
        msgs = cycle(self.ex, self.state, snap([long_row()], "2026-11-02 05:00"), allow_new=False)
        self.assertEqual(self.state["lots"], {})
        self.assertTrue(any("STOP_TRADING" in m for m in msgs))

    def test_leverage_cap(self):
        self.ex.prices["BTCUSDT"] = 80000.0
        row = long_row(stop=79990.0)                   # 손절폭이 아주 좁으면 수량이 커지지만 3배에서 막힘
        cycle(self.ex, self.state, snap([row], "2026-11-02 05:00"))
        lot = next(iter(self.state["lots"].values()))
        self.assertLessEqual(lot["qty"] * 80000.0, 3 * 1000.0 + 1e-6)

    def test_brake_halves_risk(self):
        self.ex.eq = 10000.0
        self.state["peak"] = 13000.0                   # 최고점 대비 −23% → 브레이크
        cycle(self.ex, self.state, snap([long_row(stop=76000.0)], "2026-11-02 05:00"))
        lot = next(iter(self.state["lots"].values()))
        self.assertTrue(self.state["brake"])
        # 리스크 0.5% × 0.5 = 25 USDT, 손절폭 4,000 → 0.00625 → 0.006 (브레이크 없으면 0.012)
        self.assertAlmostEqual(lot["qty"], 0.006)
    def test_paper_stop_fill_books_loss(self):
        cycle(self.ex, self.state, snap([long_row()], "2026-11-02 05:00"))
        lot = next(iter(self.state["lots"].values()))
        self.ex.check_triggers({"BTCUSDT": (77900.0, 80100.0)})        # 저가가 손절가 78,000 아래로
        msgs = cycle(self.ex, self.state, snap([long_row()], "2026-11-02 06:00"))
        rec = self.state["closed"][-1]
        self.assertEqual(rec["exit"], 78000.0)
        # 0.002 × (78,000 − 80,000) = −4, 수수료 약 0.17 → 약 −4.17 USDT
        self.assertAlmostEqual(rec["pnl"], -4.17, places=1)
        self.assertAlmostEqual(self.ex.equity(), 1000 - 4.17, places=1)
        self.assertTrue(any("누적 1건" in m for m in msgs))
        self.assertNotIn(lot["stop_id"], [lt["stop_id"] for lt in self.state["lots"].values()])

    def test_paper_state_survives_restart(self):
        cycle(self.ex, self.state, snap([long_row()], "2026-11-02 05:00"))
        saved = self.ex.dump()
        ex2 = DryRun(1000.0)
        ex2.load(saved)
        ex2.prices = dict(self.ex.prices)
        msgs = cycle(ex2, self.state, snap([long_row(stop=79000.0)], "2026-11-02 09:00"))
        self.assertTrue(any("손절 이동" in m for m in msgs))         # 기록이 사라지지 않고 이어짐
        self.assertEqual(ex2.position_size("BTCUSDT", 1), 0.002)

    def test_model_exit_books_profit(self):
        cycle(self.ex, self.state, snap([long_row()], "2026-11-02 05:00"))
        self.ex.prices["BTCUSDT"] = 84000.0
        cycle(self.ex, self.state, snap([long_row(open_=False)], "2026-11-03 05:00"))
        rec = self.state["closed"][-1]
        self.assertGreater(rec["pnl"], 7.5)                             # 0.002 × 4,000 = 8 − 수수료
        self.assertAlmostEqual(rec["r"], rec["pnl"] / (0.002 * 2000.0), places=2)


if __name__ == "__main__":
    unittest.main()
