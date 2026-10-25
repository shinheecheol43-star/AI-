"""BTC·ETH 9년치(바이낸스 공개 데이터)로 지금까지 찾은 전략들을 $1,000 시뮬레이션.

전략을 찾은 기간은 2017–2019년 BTC(Coinbase)였으므로,
  - BTC 2020년 이후 = 한 번도 안 본 기간
  - ETH 전체       = 한 번도 안 본 종목
이 진짜 검증이다.

사용:  python -m smc.study                 (BTCUSDT, ETHUSDT 1시간봉 + 5분봉)
       python -m smc.study --no-5m         (5분봉 생략, 빠름)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .data import fetch_binance_archive, resample
from .detectors import find_fvgs
from .money import equity, fvg_trend, report
from .ob_lecture import find as find_ob, simulate as simulate_ob


def ob_trigger(df_low: pd.DataFrame, df4: pd.DataFrame, low_step: str, need_sweep: bool,
               max_wait: int, max_hold: int, obs=None) -> pd.DataFrame:
    """4시간봉 200 EMA 추세 방향 + 4시간봉 FVG 구간 안에서 생긴 하위봉 OB만 (강의 방식 손절·익절)."""
    ema4 = df4["close"].ewm(span=200, adjust=False).mean().to_numpy()
    close4 = (df4["time"] + pd.Timedelta("4h")).to_numpy()
    c4 = df4["close"].to_numpy()
    by_confirm: dict[int, list] = {}
    for z in find_fvgs(df4):
        by_confirm.setdefault(z.confirm, []).append(z)
    t_low = (df_low["time"] + pd.Timedelta(low_step)).to_numpy()
    keep = []
    for b in (obs if obs is not None else find_ob(df_low)):
        k = int(np.searchsorted(close4, t_low[b.impulse], side="right")) - 1   # 마감된 마지막 4시간봉
        if k < 200 or (c4[k] > ema4[k]) != (b.side > 0):
            continue
        if need_sweep and not b.tags["sweep"]:
            continue
        # 최근 24개 4시간봉 안에 확정된 같은 방향 FVG 구간과 OB 구간이 겹치는가
        if any(z.side == b.side and b.bottom <= z.top and b.top >= z.bottom
               for zc in range(k - 24, k + 1) for z in by_confirm.get(zc, ())):
            keep.append(b)
    return simulate_ob(df_low, keep, "lecture", "wick", max_wait, max_hold)


def ob_trend(df_low: pd.DataFrame, df4: pd.DataFrame, low_step: str, max_wait: int, max_hold: int,
             obs=None) -> pd.DataFrame:
    """4시간봉 200 EMA 추세 방향의 하위봉 OB만."""
    ema4 = df4["close"].ewm(span=200, adjust=False).mean().to_numpy()
    close4 = (df4["time"] + pd.Timedelta("4h")).to_numpy()
    c4 = df4["close"].to_numpy()
    t_low = (df_low["time"] + pd.Timedelta(low_step)).to_numpy()
    keep = []
    for b in (obs if obs is not None else find_ob(df_low)):
        k = np.searchsorted(close4, t_low[b.impulse], side="right") - 1
        if k >= 200 and (c4[k] > ema4[k]) == (b.side > 0):
            keep.append(b)
    return simulate_ob(df_low, keep, "lecture", "wick", max_wait, max_hold)


def run_symbol(symbol: str, with_5m: bool, only_5m: bool = False) -> dict:
    df1 = fetch_binance_archive(symbol, "1h")
    df4 = resample(df1, "4h")
    S = {} if only_5m else {
        "OB 강의 방식 1시간봉": simulate_ob(df1, find_ob(df1), "lecture", "wick", 48, 240),
        "OB 강의 방식 4시간봉": simulate_ob(df4, find_ob(df4), "lecture", "wick", 24, 120),
        "FVG 추세 4시간봉": fvg_trend(df4, split_with_ob=False),
        "FVG + OB 분할 4시간봉": fvg_trend(df4, split_with_ob=True),
        "추세 + 4h FVG 구간 + 1h OB": ob_trigger(df1, df4, "1h", False, 48, 240),
        "위 + 유동성 흡수": ob_trigger(df1, df4, "1h", True, 48, 240),
    }
    if with_5m:
        df5 = fetch_binance_archive(symbol, "5m")
        obs5 = find_ob(df5)   # 5분봉 OB 탐지는 무거우니 한 번만 하고 세 전략이 같이 쓴다
        S["OB 강의 방식 5분봉"] = simulate_ob(df5, obs5, "lecture", "wick", 48, 288)
        S["추세 방향 5분봉 OB"] = ob_trend(df5, df4, "5min", 48, 288, obs5)
        S["추세 + 4h FVG 구간 + 5분봉 OB"] = ob_trigger(df5, df4, "5min", False, 48, 288, obs5)
    out = {"bars": len(df1), "start": str(df1.time.iloc[0]), "end": str(df1.time.iloc[-1]),
           "buy_hold": 1000 * df1.close.iloc[-1] / df1.close.iloc[0], "strategies": {}}
    for name, tr in S.items():
        if tr.empty:
            out["strategies"][name] = {"trades": 0}
            continue
        yrs = pd.DatetimeIndex(tr.entry_time).year
        rep = report(equity(tr, 1000, 0.01))
        out["strategies"][name] = {
            "trades": len(tr), "avg_r": float(tr.r.mean()), "se": float(tr.r.std() / np.sqrt(len(tr))),
            "win": float((tr.r > 0).mean()), "stop_pct": float(tr.stop_pct.median()),
            "avg_r_to_2019": float(tr.r[yrs <= 2019].mean()), "avg_r_2020_on": float(tr.r[yrs >= 2020].mean()),
            "final": rep["final"], "mdd": rep["mdd"], "year_end": rep["year_end"],
            "by_year_r": {int(y): float(tr.r[yrs == y].mean()) for y in sorted(set(yrs))},
        }
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    ap.add_argument("--no-5m", action="store_true")
    ap.add_argument("--only-5m", action="store_true", help="5분봉 전략만")
    ap.add_argument("--out", default="reports/study.json")
    a = ap.parse_args()
    res = {}
    for sym in a.symbols.split(","):
        r = res[sym] = run_symbol(sym, not a.no_5m, a.only_5m)
        print(f"\n■ {sym}  {r['start'][:10]} ~ {r['end'][:10]}   그냥 보유: $1,000 → ${r['buy_hold']:,.0f}")
        print(f"  {'전략':26} {'거래':>6} {'평균R':>7} {'~2019':>7} {'2020~':>7} {'손절폭':>6} {'최종 잔고':>12} {'최대낙폭':>7}")
        for name, s in r["strategies"].items():
            if not s["trades"]:
                print(f"  {name:26} 거래 없음")
                continue
            print(f"  {name:26} {s['trades']:6} {s['avg_r']:+7.3f} {s['avg_r_to_2019']:+7.3f} {s['avg_r_2020_on']:+7.3f}"
                  f" {s['stop_pct']*100:5.2f}% ${s['final']:>11,.0f} {s['mdd']*100:6.1f}%")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float))
    print(f"\n상세(연도별): {a.out}")


if __name__ == "__main__":
    main()
