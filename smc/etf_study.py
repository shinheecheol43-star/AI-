"""레버리지 없는 ETF(예: SOXX)로 단순한 전략들을 비교하고, 최대 3배 레버리지를 걸었을 때를 본다.

검증 전에 정한 후보 (결과를 보고 숫자를 바꾸지 않는다. 다른 숫자는 '안정성 확인'용으로만 같이 보여 준다)
  보유      : 계속 들고 있기 (비교 기준)
  추세 SMA  : 종가 > 200일 단순 이동평균이면 보유, 아니면 현금 (안정성 확인 100·150일)
  모멘텀    : 최근 12개월(252일) 수익률 > 0 이면 보유, 아니면 현금
  추세+모멘텀: 두 조건 모두일 때만 보유
  돌파      : 종가가 55일 고가 돌파 시 매수, 20일 저가 이탈 시 매도 (터틀식)
  눌림 매수 : 종가 > 200일 평균인 상승장에서 RSI(2) < 10 이면 매수, 종가 > 5일 평균이면 매도
신호는 그날 종가로 판단하고 다음 날 수익률부터 반영한다 (미래 정보 없음).
레버리지 L 배: 매일 L 배로 맞춘다(일일 리밸런싱, SOXL 같은 레버리지 ETF와 같은 방식).
  비용: 매매할 때 0.1%, 빌린 금액(L−1)에 연 5% 이자 (선물이면 펀딩비에 해당)
설계 구간 ~2015, 검증 구간 2016~.

사용:  python -m smc.etf_study SOXX
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from .research import rsi
from .stock_swing import fetch

COST, BORROW = 0.001, 0.05
SPLIT = pd.Timestamp("2016-01-01", tz="UTC")


def positions(d: pd.DataFrame) -> dict[str, pd.Series]:
    """전략별 보유 여부 (1 = 보유, 0 = 현금). 그날 종가 기준 판단."""
    c = d.close
    sma = {n: c.rolling(n).mean() for n in (5, 100, 150, 200)}
    mom = c / c.shift(252) - 1
    hi55, lo20 = d.high.rolling(55).max().shift(1), d.low.rolling(20).min().shift(1)
    brk = pd.Series(np.nan, index=d.index)
    brk[c > hi55] = 1.0
    brk[c < lo20] = 0.0
    r2 = rsi(c, 2)
    dip, held = [], 0.0
    for i in range(len(d)):
        if held == 0 and c.iat[i] > sma[200].iat[i] and r2.iat[i] < 10:
            held = 1.0
        elif held == 1 and c.iat[i] > sma[5].iat[i]:
            held = 0.0
        dip.append(held)
    return {"보유": pd.Series(1.0, index=d.index),
            "추세 SMA200": (c > sma[200]).astype(float),
            "  (확인) SMA150": (c > sma[150]).astype(float),
            "  (확인) SMA100": (c > sma[100]).astype(float),
            "모멘텀 12개월": (mom > 0).astype(float),
            "추세+모멘텀": ((c > sma[200]) & (mom > 0)).astype(float),
            "돌파 55/20": brk.ffill().fillna(0.0),
            "눌림 매수 RSI2": pd.Series(dip, index=d.index)}


def run(d: pd.DataFrame, pos: pd.Series, lev: float) -> pd.Series:
    ret = d.close.pct_change().fillna(0.0)
    p = pos.shift(1).fillna(0.0)                                   # 어제 종가 신호 → 오늘 수익
    daily = p * (lev * ret - (lev - 1) * BORROW / 252) - p.diff().abs().fillna(0.0) * COST * lev
    eq = (1 + daily.clip(lower=-0.999)).cumprod()
    return pd.Series(eq.to_numpy(), index=pd.DatetimeIndex(d.time))


def stats(eq: pd.Series, lo=None, hi=None) -> tuple:
    e = eq[(eq.index >= lo) if lo is not None else slice(None)]
    e = e[e.index < hi] if hi is not None else e
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    cagr = (e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1
    mdd = (e / e.cummax() - 1).min()
    r = e.pct_change().dropna()
    sharpe = r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0
    return cagr, mdd, sharpe


def main(sym: str = "SOXX"):
    d = fetch(sym)
    d = d[d.close > 0].reset_index(drop=True)
    print(f"{sym} 일봉 {d.time.iloc[0]:%Y-%m-%d} ~ {d.time.iloc[-1]:%Y-%m-%d} ({len(d)}일)")
    P = positions(d)
    start = d.time.iloc[252]                                       # 12개월 모멘텀이 계산되는 시점부터 비교
    print(f"비교 구간 {start:%Y-%m-%d} ~ · 설계 ~2015 · 검증 2016~ · 레버리지는 매일 리밸런싱, 빌린 돈 연 {BORROW:.0%}, 매매 {COST:.1%}\n")
    print(f"{'전략':16} {'배':>2} | {'연평균':>7} {'최대낙폭':>8} {'샤프':>5} {'효율':>5} | {'설계 연평균':>9} {'낙폭':>7} | {'검증 연평균':>9} {'낙폭':>7} | 보유비율 매매/년")
    rows = []
    for name, pos in P.items():
        yrs = (d.time.iloc[-1] - start).days / 365.25
        trades = pos[d.time >= start].diff().abs().sum() / 2 / yrs
        for lev in (1, 2, 3):
            eq = run(d, pos, lev)
            eq = eq[eq.index >= start]
            f, a, b = stats(eq), stats(eq, hi=SPLIT), stats(eq, lo=SPLIT)
            rows.append((name, lev, f, a, b))
            print(f"{name:16} {lev:2} | {f[0]*100:+6.1f}% {f[1]*100:7.1f}% {f[2]:5.2f} {f[0]/-f[1]:5.2f} | {a[0]*100:+8.1f}% {a[1]*100:6.1f}% |"
                  f" {b[0]*100:+8.1f}% {b[1]*100:6.1f}% | {pos[d.time >= start].mean()*100:5.0f}% {trades:5.1f}")
        print()
    i = len(d) - 1
    c = d.close
    print(f"■ 지금 ({d.time.iloc[-1]:%Y-%m-%d} 종가 {c.iat[i]:.2f})")
    print(f"  200일 평균 {c.rolling(200).mean().iat[i]:.2f} · 150일 {c.rolling(150).mean().iat[i]:.2f} · 100일 {c.rolling(100).mean().iat[i]:.2f}"
          f" · 12개월 수익률 {(c.iat[i] / c.iat[i - 252] - 1) * 100:+.1f}% · 55일 고가 {d.high.iloc[-56:-1].max():.2f} · 20일 저가 {d.low.iloc[-21:-1].min():.2f}"
          f" · RSI(2) {rsi(c, 2).iat[i]:.0f}")
    for name, pos in P.items():
        print(f"  {name:16} → {'보유' if pos.iat[i] else '현금'}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "SOXX")
