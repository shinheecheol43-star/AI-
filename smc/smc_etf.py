"""오더블럭·FVG(강의 1·2장)와 거짓 돌파 등 신호를 주식 ETF(SOXX·SOXL·QQQ)에 적용해 본다.

신호와 청산은 research.py 와 같다 (코인에서 쓴 것 그대로)
  OB·FVG : 존이 확정된 뒤 존 윗변(숏은 아랫변)에 지정가, wait 봉 안에 닿으면 체결
  나머지 : 신호 봉 종가에 시장가
  손절 ATR(14) × 1.5, 익절 손절폭 × TP (1.5R 기본, 3R 도 확인), 최대 hold 봉. 같은 봉에서 둘 다 닿으면 손절.
  비용: Bybit 무기한 수수료 (지정가 0.02%, 시장가 0.055%)
나눠 보기: 200일(봉) 평균 방향과 같은 신호만 / 유동성 흡수 동반만
설계 구간 ~2015 (1시간봉은 처음 1년), 검증 구간 그 이후.

사용:  python -m smc.smc_etf
"""
from __future__ import annotations

import pandas as pd

from . import research
from .intraday_etf import fetch_1h
from .stock_swing import fetch

FAMILIES = ["OB", "FVG", "거짓돌파", "채널반전", "20봉돌파", "RSI반전", "EMA교차"]


def collect(d: pd.DataFrame, wait: int, hold: int, tp: float) -> pd.DataFrame:
    research.TP_R = tp
    d = d.reset_index(drop=True)
    f = research.tf_features(d)
    trend = (d.close > d.close.rolling(200).mean()).astype(int) * 2 - 1
    rows = []
    for s in research.signals(d, f, wait):
        o = research.outcome(d, f.atr.to_numpy(), s, wait, hold)
        if o is None or s["i"] < 200:
            continue
        rows.append({"family": s["family"], "side": s["side"], "time": d.time.iat[s["i"]], "sweep": bool(s["sweep"]),
                     "aligned": s["side"] == trend.iat[s["i"]], "r": o["r"]})
    return pd.DataFrame(rows)


def table(name: str, x: pd.DataFrame, split):
    print(f"\n■ {name}  (거래 {len(x)}건)")
    print(f"{'신호':6} {'방향':3} | {'전체 n/승률/R':>17} | {'추세 같은 방향만':>17} | {'설계 R':>7} {'검증 R':>7} (추세 같은 방향)")
    for fam in FAMILIES:
        for side in (1, -1):
            y = x[(x.family == fam) & (x.side == side)]
            if len(y) < 15:
                continue
            a = y[y.aligned]
            f = lambda z: f"{len(z):4} {(z.r > 0).mean()*100:3.0f}% {z.r.mean():+.2f}" if len(z) else "   –"
            print(f"{fam:6} {'롱' if side > 0 else '숏':3} | {f(y):>17} | {f(a):>17} | {a[a.time < split].r.mean():+7.2f} {a[a.time >= split].r.mean():+7.2f}")
    for fam in ("OB", "FVG"):
        y = x[(x.family == fam) & x.sweep & x.aligned]
        if len(y) >= 10:
            print(f"  {fam} 유동성 흡수 + 추세 같은 방향: {len(y)}건 승률 {(y.r > 0).mean()*100:.0f}% 평균 {y.r.mean():+.2f}R")


def main():
    split_d = pd.Timestamp("2016-01-01", tz="UTC")
    for tp in (1.5, 3.0):
        print(f"\n{'=' * 30} 익절 {tp}R {'=' * 30}")
        for sym in ("SOXX", "SOXL", "QQQ"):
            d = fetch(sym)
            table(f"{sym} 일봉 ({d.time.iloc[0]:%Y}~)", collect(d, wait=10, hold=20, tp=tp), split_d)
        h = fetch_1h("SOXL")[["time", "open", "high", "low", "close"]].assign(volume=0.0)
        split_h = h.time.iloc[0] + pd.Timedelta(days=365)
        table("SOXL 1시간봉 (최근 2년)", collect(h, wait=14, hold=35, tp=tp), split_h)
    research.TP_R = 1.5


if __name__ == "__main__":
    main()
