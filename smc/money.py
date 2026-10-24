"""$1,000으로 시작했을 때 잔고가 어떻게 변하는지 시뮬레이션.

포지션 크기: 진입 시점 잔고의 risk(기본 1%)를 잃으면 손절되도록 수량을 정한다.
           손절폭이 너무 좁아 레버리지가 max_lev(3배)를 넘으면 수량을 줄인다(그만큼 리스크도 줄어듦).
손익은 청산 시점에 잔고에 반영(복리). 수수료는 Bybit(지정가 0.02%, 시장가 0.055%) 기준.

전략 (손절·익절 규칙 포함)
  OB 강의 방식    : 강의 1장 그대로. 오더블럭 몸통 진입, 패턴 꼬리 끝 손절,
                    파동 고점 탈환 시 1/2 익절 + 나머지 본절 스탑, 반대 OB 출현 시 종료
  FVG 추세        : 4시간봉, 200 EMA 방향의 FVG만. FVG 진입, 세 캔들 꼬리 끝 손절, 파동 고점 전량 익절
  FVG + OB 분할   : 위 FVG에 1차, FVG 패턴 안의 같은 방향 OB에 2차(같은 수량) 진입, 둘 중 먼 꼬리 끝 손절

사용:  python -m smc.money
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from .data import DEFAULT_CSV, load, resample
from .detectors import find_fvgs, find_order_blocks
from .ob_lecture import MAKER, TAKER, find as find_ob_lecture, simulate as simulate_ob


def fvg_trend(df: pd.DataFrame, split_with_ob: bool, max_wait: int = 24, max_hold: int = 120) -> pd.DataFrame:
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    ema = df["close"].ewm(span=200, adjust=False).mean().to_numpy()
    n, times = len(c), df["time"]
    obs = find_order_blocks(df) if split_with_ob else []
    rows = []
    for z in find_fvgs(df):
        s = z.side
        if z.confirm < 200 or (s > 0) != (c[z.confirm] > ema[z.confirm]):
            continue
        cand = [b for b in obs if b.side == s and z.confirm - 3 <= b.confirm <= z.confirm and s * (z.entry - b.entry) > 0]
        ob = min(cand, key=lambda b: s * b.entry, default=None)
        legs = [z.entry] + ([ob.entry] if ob else [])
        stop = z.stop if ob is None else (min(z.stop, ob.stop) if s > 0 else max(z.stop, ob.stop))
        wave = h[z.confirm] if s > 0 else l[z.confirm]
        t0 = None
        for t in range(z.confirm + 1, min(n, z.confirm + 1 + max_wait)):
            if (l[t] <= legs[0]) if s > 0 else (h[t] >= legs[0]):
                t0 = t
                break
            wave = max(wave, h[t]) if s > 0 else min(wave, l[t])
        if t0 is None or ((o[t0] <= stop) if s > 0 else (o[t0] >= stop)):
            continue
        filled, ex, kind = [], None, None
        for u in range(t0, min(n, t0 + 1 + max_hold)):
            for p in legs:
                if p not in filled and ((l[u] <= p) if s > 0 else (h[u] >= p)):
                    filled.append(p)
            if (l[u] <= stop) if s > 0 else (h[u] >= stop):
                ex, kind = stop, "sl"
                break
            if u > t0 and ((h[u] >= wave) if s > 0 else (l[u] <= wave)):
                ex, kind = wave, "tp"
                break
        if ex is None:
            u = min(n - 1, t0 + max_hold)
            ex, kind = c[u], "time"
        risk = sum(abs(p - stop) for p in filled)
        if risk < 0.001 * filled[0]:
            continue
        pnl = sum(s * (ex - p) - MAKER * p - (MAKER if kind == "tp" else TAKER) * ex for p in filled)
        rows.append({"entry_time": times.iloc[t0], "exit_time": times.iloc[u], "side": s,
                     "r": pnl / risk, "stop_pct": abs(filled[0] - stop) / filled[0], "outcome": kind})
    return pd.DataFrame(rows)


def equity(trades: pd.DataFrame, start: float = 1000.0, risk: float = 0.01, max_lev: float = 3.0) -> pd.DataFrame:
    """거래 목록 → 청산 순서대로 잔고 변화. 진입 시점까지 확정된 잔고로 수량을 정한다."""
    t = trades.sort_values("entry_time").reset_index(drop=True)
    realized = []        # (청산 시각, 손익)
    sizes = np.zeros(len(t))
    for i, row in t.iterrows():
        bal = start + sum(p for (et, p) in realized if et <= row.entry_time)
        if bal <= 0:
            break
        f = min(risk, max_lev * row.stop_pct)       # 레버리지 상한 때문에 줄어든 실제 리스크
        sizes[i] = bal * f
        realized.append((row.exit_time, sizes[i] * row.r))
    t["pnl"] = [sizes[i] * t.r.iloc[i] for i in range(len(t))]
    curve = t.sort_values("exit_time")[["exit_time", "pnl"]].copy()
    curve["balance"] = start + curve.pnl.cumsum()
    return curve


def report(curve: pd.DataFrame, start: float = 1000.0) -> dict:
    bal = curve.balance.to_numpy()
    peak = np.maximum.accumulate(np.r_[start, bal])[1:]
    years = pd.DatetimeIndex(curve.exit_time).year
    year_end = {int(y): float(curve.balance[years == y].iloc[-1]) for y in sorted(set(years))}
    return {"final": float(bal[-1]) if len(bal) else start, "mdd": float((bal / peak - 1).min()) if len(bal) else 0.0,
            "trades": len(curve), "year_end": year_end}


def strategies(df1: pd.DataFrame) -> dict[str, pd.DataFrame]:
    df4 = resample(df1, "4h")
    return {
        "OB 강의 방식 (1시간봉)": simulate_ob(df1, find_ob_lecture(df1), "lecture", "wick", 48, 240),
        "OB 강의 방식 (4시간봉)": simulate_ob(df4, find_ob_lecture(df4), "lecture", "wick", 24, 120),
        "FVG 추세 (4시간봉)": fvg_trend(df4, split_with_ob=False),
        "FVG + OB 분할 (4시간봉)": fvg_trend(df4, split_with_ob=True),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=str(DEFAULT_CSV))
    ap.add_argument("--symbol")
    ap.add_argument("--count", type=int, default=20000)
    ap.add_argument("--start", type=float, default=1000.0)
    a = ap.parse_args()

    df1 = load(a.source, a.symbol, "1h", a.count)
    bh = a.start * df1.close.iloc[-1] / df1.close.iloc[0]
    print(f"기간 {df1.time.iloc[0]:%Y-%m-%d} ~ {df1.time.iloc[-1]:%Y-%m-%d}, 시작 ${a.start:,.0f}")
    print(f"그냥 사서 보유: ${bh:,.0f}\n")
    for name, tr in strategies(df1).items():
        for risk in (0.01, 0.02):
            r = report(equity(tr, a.start, risk), a.start)
            ye = "  ".join(f"{y}년말 ${v:,.0f}" for y, v in r["year_end"].items())
            print(f"{name:22} 거래당 {risk*100:.0f}% | 최종 ${r['final']:>8,.0f} ({(r['final']/a.start-1)*100:+6.1f}%)"
                  f"  최대낙폭 {r['mdd']*100:5.1f}%  거래 {r['trades']}건  | {ye}")


if __name__ == "__main__":
    main()
