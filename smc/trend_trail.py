"""추세 방향 + 추적 손절 검증. research.py 데이터셋의 4시간봉 신호에 다른 청산을 적용한다.

청산(검증 전에 고정)
  최초 손절 : 진입가 ∓ 신호 캔들 ATR × 2
  추적 손절 : 진입 후 최고가(숏은 최저가) ∓ 현재 ATR × mult(기본 3). 손절선은 유리한 쪽으로만 움직임
  최대 보유 : 120봉(20일). 익절 목표 없음 — 추세가 끝날 때까지 따라감
  비용      : 진입(지정가 0.02% / 시장가 0.055%), 청산 0.055%, 보유 기간의 실제 펀딩비
비교      : 같은 방향·같은 청산으로 '아무 시점에나' 진입한 대조군

사용:  python -m smc.trend_trail
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .data import fetch_binance_archive, resample
from .regime import DEFAULT_FUNDING, fetch_funding
from .research import MAKER, OUT as DATA, TAKER, tf_features
from .research_report import SPLIT, equity

HOLD = 120


def _trail(o, h, l, c, atr, day_idx, fund_cum, t0, start, side, fill, risk, mult):
    stop, ext = fill - side * risk, fill
    ex = ei = None
    for t in range(start, min(len(c), t0 + HOLD + 1)):
        if (o[t] <= stop) if side > 0 else (o[t] >= stop):
            ex, ei = o[t], t
            break
        if (l[t] <= stop) if side > 0 else (h[t] >= stop):
            ex, ei = stop, t
            break
        ext = max(ext, h[t]) if side > 0 else min(ext, l[t])
        new = ext - side * mult * atr[t]
        stop = max(stop, new) if side > 0 else min(stop, new)
    if ex is None:
        ei = min(len(c) - 1, t0 + HOLD)
        ex = c[ei]
    funding = fund_cum[day_idx[ei]] - fund_cum[day_idx[t0]]   # 보유한 날들의 펀딩비 합 (롱이 냄)
    return ei, ex, side * funding * fill


def build(mult: float = 3.0, random_reps: int = 0, seed: int = 0) -> pd.DataFrame:
    d = pd.read_pickle(DATA)
    d = d[d.tf == "4h"]
    rows, rng = [], np.random.default_rng(seed)
    for sym in ("BTC", "ETH"):
        df = resample(fetch_binance_archive(sym + "USDT", "1h"), "4h")
        f = tf_features(df)
        o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
        atr, ema200 = f["atr"].to_numpy(), f["ema200"].to_numpy()
        days = df["time"].dt.floor("D")
        fund = fetch_funding(sym + "USDT").reindex(pd.DatetimeIndex(days.unique())).fillna(DEFAULT_FUNDING)
        fund_cum = np.r_[0.0, fund.cumsum().to_numpy()]
        day_idx = pd.Index(fund.index).get_indexer(days) + 1
        idx = {t: i for i, t in enumerate(df["time"])}
        for _, s in d[d.symbol == sym].iterrows():
            i, t0, side, fill = idx[s.time], int(s.t_entry), int(s.side), float(s.entry)
            risk = 2.0 * atr[i]
            fee_in = MAKER if s.limit_entry else TAKER
            ei, ex, fcost = _trail(o, h, l, c, atr, day_idx, fund_cum, t0, t0 if s.limit_entry else t0 + 1,
                                   side, fill, risk, mult)
            r = (side * (ex - fill) - fee_in * fill - TAKER * ex - fcost) / risk
            base = dict(symbol=sym, family=s.family, side=side, time=s.time, good=(s.trend4h > 0) and (s.day_score >= 1),
                        trend4h=s.trend4h, day_score=s.day_score)
            rows.append({**base, "kind": "신호", "r": r, "entry_time": df["time"].iat[t0],
                         "exit_time": df["time"].iat[ei] + pd.Timedelta("4h"), "stop_pct": risk / fill,
                         "hold_bars": ei - t0})
            for _ in range(random_reps):   # 대조군: 같은 방향, 4h 추세도 같은 방향인 아무 시점
                for _ in range(50):
                    j = int(rng.integers(300, len(c) - HOLD - 2))
                    if np.sign(c[j] - ema200[j]) == side:
                        break
                ej, exj, fj = _trail(o, h, l, c, atr, day_idx, fund_cum, j, j + 1, side, c[j], 2.0 * atr[j], mult)
                rj = (side * (exj - c[j]) - TAKER * (c[j] + exj) - fj) / (2.0 * atr[j])
                rows.append({**base, "kind": "추세방향 무작위", "r": rj, "time": df["time"].iat[j]})
    return pd.DataFrame(rows)


def main():
    x = build(3.0, random_reps=5)
    sig = x[x.kind == "신호"]
    out = {}
    print(f"{'구성':30} {'설계 n/승률/R':>22} {'검증 n/승률/R':>22} {'검증 BTC/ETH':>15} {'검증 $1,000→':>12} {'낙폭':>6}  무작위(추세방향)")
    for name, m in (("4h 20봉 돌파 + 추세 근거", (sig.family == "20봉돌파") & sig.good),
                    ("4h 20봉 돌파 + 추세 근거, 롱만", (sig.family == "20봉돌파") & sig.good & (sig.side > 0)),
                    ("4h 모든 신호 + 추세 근거", sig.good),
                    ("4h 모든 신호 (근거 없음)", sig.good | ~sig.good)):
        y = sig[m]
        tr, te = y[y.time < SPLIT], y[y.time >= SPLIT]
        eq, eq_all = equity(te), equity(y)
        rnd = x[(x.kind != "신호") & x.family.isin(y.family.unique()) & x.side.isin(y.side.unique())
                & (x.good if "추세" in name else True)]
        out[name] = {"train": [len(tr), float((tr.r > 0).mean()), float(tr.r.mean())],
                     "test": [len(te), float((te.r > 0).mean()), float(te.r.mean())],
                     "test_btc": float(te[te.symbol == "BTC"].r.mean()), "test_eth": float(te[te.symbol == "ETH"].r.mean()),
                     "equity_test": eq, "equity_all": eq_all, "random": float(rnd.r.mean()),
                     "by_year": {int(k): float(v) for k, v in y.groupby(y.time.dt.year).r.mean().items()},
                     "hold_days_median": float(y.hold_bars.median() / 6)}
        print(f"{name:30} {len(tr):5} {(tr.r>0).mean()*100:5.1f}% {tr.r.mean():+.3f}  {len(te):5} {(te.r>0).mean()*100:5.1f}%"
              f" {te.r.mean():+.3f}  {out[name]['test_btc']:+.3f}/{out[name]['test_eth']:+.3f}  ${eq['final']:>9,.0f}"
              f" {eq['mdd']*100:5.1f}%  {out[name]['random']:+.3f}")
    with open(DATA.with_name("trend_trail.json"), "w") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
