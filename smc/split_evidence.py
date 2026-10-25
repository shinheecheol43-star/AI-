"""분할 진입의 2차 진입 근거 비교.

대상·청산·자금 규칙은 split_entry.py 와 같다 (4h 20봉 돌파, 강한 신호, 롱만, 추적 손절, 레버리지 3배, 1% 복리).
1차: 신호 캔들 종가에 계획 수량의 50%.  2차: 아래 근거가 12봉 안에 나오면 나머지 50%, 안 나오면 취소.

  ① 가격 눌림     : 신호가 − 0.5 ATR 지정가
  ② 돌파 리테스트 : 돌파한 직전 20봉 고점 가격 지정가
  ③ FVG 구간      : 돌파 캔들이 만든 상승 FVG 윗변 지정가 (FVG 없으면 2차 없음)
  ④ OB 구간       : 돌파 캔들로 생긴 상승 오더블럭 윗변 지정가 (OB 없으면 2차 없음)
  ⑤ 지지 확인 후  : 저가가 20 EMA에 닿은 뒤, 20 EMA 위에서 양봉 마감하면 그 종가
  ⑥ 상승 확인 후  : 고가가 신호가 + 1 ATR 에 닿으면 그 가격 (불타기)

사용:  python -m smc.split_evidence
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import fetch_binance_archive, resample
from .detectors import Params, find_fvgs
from .ob_lecture import find as find_ob
from .regime import DEFAULT_FUNDING, fetch_funding
from .research import MAKER, TAKER, tf_features
from .research_report import SPLIT
from .split_entry import HOLD, STOP_ATR, TRAIL_ATR, WAIT, portfolio, strong_signals

METHODS = ["한 번에 100%", "50%만 (2차 없음)", "① 가격 눌림 0.5ATR", "② 돌파 리테스트", "③ FVG 구간",
           "④ OB 구간", "⑤ 지지 확인 후", "⑥ 상승 확인 후"]


def simulate(ctx: dict, i: int, method: str) -> dict:
    o, h, l, c, atr, ema = ctx["o"], ctx["h"], ctx["l"], ctx["c"], ctx["atr"], ctx["ema20"]
    n, p0, a = len(c), c[i], atr[i]
    stop0 = p0 - STOP_ATR * a
    stop, one_r = stop0, p0 - stop0
    legs = [{"w": 1.0 if method == "한 번에 100%" else 0.5, "px": p0, "t": i, "fee": TAKER}]
    pending = method not in ("한 번에 100%", "50%만 (2차 없음)")
    limit, avail = None, i + 1
    if method == "① 가격 눌림 0.5ATR":
        limit = p0 - 0.5 * a
    elif method == "② 돌파 리테스트":
        limit = ctx["hh"][i]
    elif method == "③ FVG 구간":
        z = ctx["fvg"].get(i)
        limit, avail = (z if z is None else z[0]), (i + 2 if z else n)
        pending = z is not None
    elif method == "④ OB 구간":
        b = ctx["ob"].get(i)
        limit, avail = (b if b is None else b[0]), (b[1] + 1 if b else n)
        pending = b is not None
    touched = False
    ext, ex, ei = p0, None, None
    for t in range(i + 1, min(n, i + HOLD + 1)):
        live = pending and t <= i + WAIT and t >= avail
        if live and limit is not None and limit > stop and l[t] <= limit:     # 지정가: 체결 후 손절 확인(보수적)
            legs.append({"w": 0.5, "px": min(o[t], limit), "t": t, "fee": MAKER})
            pending = False
        if live and method == "⑥ 상승 확인 후" and h[t] >= p0 + a:
            legs.append({"w": 0.5, "px": max(o[t], p0 + a), "t": t, "fee": TAKER})
            pending = False
        if o[t] <= stop:
            ex, ei = o[t], t
            break
        if l[t] <= stop:
            ex, ei = stop, t
            break
        if live and method == "⑤ 지지 확인 후":
            if l[t] <= ema[t]:
                touched = True
            if touched and c[t] > ema[t] and c[t] > o[t] and c[t] > stop:
                legs.append({"w": 0.5, "px": c[t], "t": t, "fee": TAKER})
                pending = False
        ext = max(ext, h[t])
        stop = max(stop, ext - TRAIL_ATR * atr[t])
    if ex is None:
        ei = min(n - 1, i + HOLD)
        ex = c[ei]
    fcum, didx = ctx["fcum"], ctx["didx"]
    pnl = sum(g["w"] * ((ex - g["px"]) - g["fee"] * g["px"] - TAKER * ex
                        - (fcum[didx[ei]] - fcum[didx[g["t"]]]) * g["px"]) for g in legs)
    return {"r": pnl / one_r, "added": len(legs) > 1, "exit_t": ei, "stop_pct": one_r / p0}


def context(sym: str) -> dict:
    df = resample(fetch_binance_archive(sym + "USDT", "1h"), "4h")
    f = tf_features(df)
    days = df["time"].dt.floor("D")
    fund = fetch_funding(sym + "USDT").reindex(pd.DatetimeIndex(days.unique())).fillna(DEFAULT_FUNDING)
    fvg = {z.confirm - 1: (z.top, z.confirm) for z in find_fvgs(df, Params()) if z.side > 0}
    ob = {b.impulse: (b.top, b.confirm) for b in find_ob(df) if b.side > 0}
    return {"df": df, "o": df["open"].to_numpy(), "h": df["high"].to_numpy(), "l": df["low"].to_numpy(),
            "c": df["close"].to_numpy(), "atr": f["atr"].to_numpy(), "ema20": f["ema20"].to_numpy(),
            "hh": df["high"].rolling(20).max().shift(1).to_numpy(), "fvg": fvg, "ob": ob,
            "fcum": np.r_[0.0, fund.cumsum().to_numpy()], "didx": pd.Index(fund.index).get_indexer(days) + 1,
            "idx": {t: k for k, t in enumerate(df["time"])}}


def main():
    sig = strong_signals()
    ctxs = {s: context(s) for s in ("BTC", "ETH")}
    print("4h 20봉 돌파 · 강한 신호 · 롱만 · 1차 50% + 근거 시 2차 50% · 레버리지 ≤ 3배 · 1% 복리\n")
    print(f"{'2차 근거':20} {'구간':6} {'승률':>6} {'평균R':>7} {'2차 체결':>8} {'체결시 승률':>9} {'미체결 승률':>9}"
          f" {'$1,000→':>9} {'연평균':>7} {'낙폭':>7} {'연평균/낙폭':>9}")
    for m in METHODS:
        rows = []
        for sym, ctx in ctxs.items():
            for _, s in sig[sig.symbol == sym].iterrows():
                i = ctx["idx"][s.time]
                r = simulate(ctx, i, m)
                rows.append({"symbol": sym, "entry": ctx["df"]["time"].iat[i] + pd.Timedelta("4h"),
                             "exit": ctx["df"]["time"].iat[r["exit_t"]] + pd.Timedelta("4h"), **r})
        x = pd.DataFrame(rows).sort_values("entry").reset_index(drop=True)
        for per, mask in (("검증", x.entry >= SPLIT), ("전체", x.entry == x.entry)):
            y = x[mask]
            p = portfolio(y)
            yrs = (y.exit.max() - y.entry.min()).days / 365.25
            cagr = (p["final"] / 1000) ** (1 / yrs) - 1
            add, noadd = y[y.added], y[~y.added]
            fr = f"{y.added.mean()*100:.0f}%" if m not in METHODS[:2] else "-"
            wa = f"{(add.r > 0).mean()*100:.1f}%" if len(add) and m not in METHODS[:2] else "-"
            wn = f"{(noadd.r > 0).mean()*100:.1f}%" if len(noadd) and m not in METHODS[:2] else "-"
            print(f"{m:20} {per:6} {(y.r > 0).mean()*100:5.1f}% {y.r.mean():+7.3f} {fr:>8} {wa:>9} {wn:>9}"
                  f" ${p['final']:>8,.0f} {cagr*100:+6.1f}% {p['mdd']*100:6.1f}% {cagr / -p['mdd']:9.2f}")


if __name__ == "__main__":
    main()
