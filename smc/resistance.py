"""저항에서 막힐 때 짧게 숏: 전고점 거짓 돌파(강의 5장)와 채널 상단 거부(강의 4장).

규칙(검증 전에 고정)
  A. 거짓 돌파 숏 : 확정 스윙 고점(좌우 5캔들)을 꼬리로 넘었다가 그 아래에서 종가 마감 → 종가 진입
                    손절 = 넘었던 꼬리 끝, 익절 = 가장 가까운 확정 스윙 저점
  B. 채널 상단 숏 : 직전 100캔들 종가 회귀선 ± 2표준편차 채널. 고가가 상단에 닿고 음봉으로 상단 아래 마감
                    손절 = 그 캔들 고가, 익절 = 회귀선(중단선)
  국면 구분      : 전날까지의 일봉 국면 점수(regime.py) > 0 이면 상승 국면, < 0 이면 하락 국면
  체결          : 진입 시장가(0.055%), 익절 지정가(0.02%), 손절 시장가(0.055%). 같은 캔들에 둘 다 닿으면 손절

사용:  python -m smc.resistance
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .backtest import BTConfig, _manage
from .data import fetch_binance_archive, resample
from .detectors import Params, find_fakeouts
from .money import equity, report
from .regime import indicators

MAKER, TAKER = 0.0002, 0.00055


def _trade(df, side, i, entry, stop, target, hold):
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    risk = abs(entry - stop)
    if i + 1 >= len(c) or risk < 0.001 * entry or side * (target - entry) <= 0:
        return None
    ei, ex, oc = _manage(o, h, l, c, side, i + 1, entry, stop, target, BTConfig(max_hold=hold))
    fee = TAKER * entry + (MAKER if oc == "tp" else TAKER) * ex
    return {"entry_time": df["time"].iat[i], "exit_time": df["time"].iat[ei], "side": side,
            "r": (side * (ex - entry) - fee) / risk, "stop_pct": risk / entry, "rr": abs(target - entry) / risk,
            "outcome": oc}


def fakeout_shorts(df, hold):
    out = []
    for f in find_fakeouts(df, Params()):
        if f.side < 0 and (t := _trade(df, -1, f.confirm, f.entry, f.stop, f.targets[0], hold)):
            out.append(t)
    return out


def channel_shorts(df, hold, n=100, k=2.0):
    o, h, c = df["open"].to_numpy(), df["high"].to_numpy(), df["close"].to_numpy()
    x = np.arange(n)
    xm, xv = x.mean(), ((x - x.mean()) ** 2).sum()
    out = []
    for i in range(n, len(c)):
        y = c[i - n:i]                      # 신호 캔들 이전 n개로 채널을 만든다 (미래 참조 없음)
        b = ((x - xm) * (y - y.mean())).sum() / xv
        a = y.mean() - b * xm
        sd = (y - (a + b * x)).std()
        mid = a + b * n                     # 신호 캔들 위치까지 연장한 중단선
        upper = mid + k * sd
        if h[i] >= upper and c[i] < upper and c[i] < o[i]:
            if t := _trade(df, -1, i, c[i], h[i], mid, hold):
                out.append(t)
    return out


def tag_regime(trades: list[dict], daily: pd.DataFrame) -> pd.DataFrame:
    t = pd.DataFrame(trades)
    if t.empty:
        return t
    score = daily["score"].shift(1)         # 전날까지 확정된 점수만 사용
    day = t["entry_time"].dt.floor("D")
    t["score"] = score.reindex(day).to_numpy()
    return t.dropna(subset=["score"])


def main():
    pd.set_option("display.width", 200)
    for sym in ("BTCUSDT", "ETHUSDT"):
        df1 = fetch_binance_archive(sym, "1h")
        daily = indicators(resample(df1, "1D").set_index("time"))
        print(f"\n■ {sym}")
        print(f"  {'신호':24} {'국면':6} {'거래':>5} {'승률':>6} {'평균R':>7} {'18–21':>7} {'22–26':>7} {'오차±':>6} {'$1,000→':>9}")
        for tf, df, hold in (("1시간봉", df1, 48), ("4시간봉", resample(df1, "4h"), 30)):
            for name, fn in (("A 거짓 돌파 숏", fakeout_shorts), ("B 채널 상단 숏", channel_shorts)):
                t = tag_regime(fn(df, hold), daily)
                for reg, m in (("상승중", t.score > 0), ("하락중", t.score < 0), ("전체", t.score == t.score)):
                    x = t[m]
                    if x.empty:
                        continue
                    yr = x.entry_time.dt.year
                    fin = report(equity(x, 1000, 0.01))["final"]
                    print(f"  {tf + ' ' + name:24} {reg:6} {len(x):5} {(x.r > 0).mean()*100:5.1f}% {x.r.mean():+7.3f}"
                          f" {x.r[yr <= 2021].mean():+7.3f} {x.r[yr >= 2022].mean():+7.3f} {x.r.std()/np.sqrt(len(x)):6.3f} ${fin:>8,.0f}")


if __name__ == "__main__":
    main()
