"""탐지기와 체결 로직이 강의 규칙대로 동작하는지 확인하는 작은 테스트.  python -m unittest"""
import unittest

import pandas as pd

from smc.backtest import BTConfig, trade_zone
from smc.detectors import Params, find_fakeouts, find_fvgs, find_order_blocks


def frame(rows):
    """rows: (open, high, low, close) 목록 → 1시간 간격 DataFrame."""
    t = pd.date_range("2024-01-01", periods=len(rows), freq="1h", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df.insert(0, "time", t)
    df["volume"] = 1.0
    return df


# ATR이 0이 되지 않도록 앞에 깔아 두는 평범한 캔들
BASE = [(100, 101, 99, 100.5), (100.5, 101.5, 99.5, 100)] * 10


class TestFVG(unittest.TestCase):
    def test_bullish_fvg(self):
        rows = BASE + [(100, 100.6, 99.8, 100.4),   # 1번: 고가 100.6
                       (100.4, 106, 100.3, 105.8),  # 2번: 몸통 긴 양봉
                       (105.8, 106.5, 105.2, 105.6)]  # 3번: 저가 105.2 > 100.6 → 빈 공간
        z = [z for z in find_fvgs(frame(rows)) if z.confirm == len(rows) - 1]
        self.assertEqual(len(z), 1)
        self.assertEqual((z[0].side, z[0].bottom, z[0].top, z[0].stop), (1, 100.6, 105.2, 99.8))

    def test_no_fvg_when_candles_similar(self):
        # 강의 Q&A: 3개 캔들 크기가 비슷하면 FVG가 아니다
        rows = BASE + [(100, 103, 99.9, 102.9), (102.9, 106, 102.8, 105.9), (105.9, 109, 105.8, 108.9)]
        self.assertFalse([z for z in find_fvgs(frame(rows)) if z.confirm == len(rows) - 1])


class TestOrderBlock(unittest.TestCase):
    def test_bullish_ob(self):
        rows = BASE + [(101, 101.2, 99.6, 100),   # 음봉 (몸통 1)
                       (100, 104, 99.8, 103.8)]   # 양봉 몸통 3.8 ≥ 2배, 종가가 음봉 고가 위
        z = [z for z in find_order_blocks(frame(rows)) if z.confirm == len(rows) - 1]
        self.assertEqual(len(z), 1)
        self.assertEqual((z[0].side, z[0].top, z[0].bottom, z[0].stop), (1, 101, 100, 99.6))

    def test_trade_hits_target(self):
        rows = BASE + [(101, 101.2, 99.6, 100), (100, 104, 99.8, 103.8),
                       (103.8, 105, 103, 104.5),   # 파동 고점 105
                       (104.5, 104.6, 100.8, 101),  # 존 윗변 101에 닿음 → 진입
                       (101, 103, 100.5, 102.5),
                       (102.5, 105.5, 102, 105.2)]  # 105 돌파 → 익절
        df = frame(rows)
        z = [z for z in find_order_blocks(df) if z.confirm == len(BASE) + 1][0]
        tr = trade_zone(df, z, BTConfig(fee=0))
        self.assertEqual((tr.entry, tr.target, tr.outcome), (101, 105, "tp"))
        self.assertAlmostEqual(tr.r, (105 - 101) / (101 - 99.6))

    def test_same_bar_stop_and_target_counts_as_stop(self):
        rows = BASE + [(101, 101.2, 99.6, 100), (100, 104, 99.8, 103.8),
                       (103.8, 105, 103, 104.5),
                       (104.5, 104.6, 100.8, 101),
                       (101, 106, 99, 102)]  # 한 캔들에 손절(99.6)과 익절(105) 둘 다
        df = frame(rows)
        z = [z for z in find_order_blocks(df) if z.confirm == len(BASE) + 1][0]
        self.assertEqual(trade_zone(df, z, BTConfig(fee=0)).outcome, "sl")


class TestFakeOut(unittest.TestCase):
    def test_support_sweep_and_reclaim(self):
        k = Params().pivot_k
        down = [(110 - i, 110.5 - i, 109 - i, 109.5 - i) for i in range(8)]       # 저점 102까지 하락
        up = [(103 + i, 104 + i, 102.5 + i, 103.8 + i) for i in range(k + 3)]     # 반등 → 스윙 고점 생성
        back = [(110 - i, 110.4 - i, 108.6 - i, 108.8 - i) for i in range(6)]     # 다시 내려옴
        sweep = [(104, 104.2, 101, 101.5),   # 지지선 102 아래로 이탈
                 (101.5, 103.5, 101.2, 103.2)]  # 종가로 복귀 → 매수 신호
        rows = BASE + down + up + back + sweep
        f = [f for f in find_fakeouts(frame(rows)) if f.confirm == len(rows) - 1]
        self.assertEqual(len(f), 1)
        self.assertEqual((f[0].side, f[0].level, f[0].stop, f[0].entry), (1, 102, 101, 103.2))
        self.assertTrue(f[0].trap)


if __name__ == "__main__":
    unittest.main()
