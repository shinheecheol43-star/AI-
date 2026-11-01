"""스윙 시스템(smc.system)에 분할 익절 + 본절 이동을 붙여 승률을 올려 본다. 규칙은 결과를 보기 전에 정했다.

진입·최초 손절(2 ATR)·추적 손절(3 ATR)·최대 120봉은 그대로.
  +a R 에 닿으면 수량의 f 만큼 그 가격에 익절, 남은 수량의 손절을 본절(진입가 + 수수료)로 올림. 남은 수량은 원래대로 추적.
  a = 0.5 · 1.0 · 1.5 · 2.0,  f = 0.3 · 0.5 · 0.7.   비교 기준 = 지금 시스템 (분할 없음)
판정: 검증 구간(2022~)에서 승률이 오르면서 연수익이 지금의 90% 이상, 최대 낙폭이 지금보다 나쁘지 않을 것.
레버리지 상한·리스크·비상 브레이크 없음 (account_curve 기본, 지금 시스템 비교와 같은 조건).

사용:  python -m smc.swing_partial
"""
from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from . import system as S
from .dd_brake import curve as account_curve
from .swing_ls import describe


def trail_partial(X: dict, i: int, side: int, a: float | None, f: float) -> dict:
    o, h, l, c, atr = X["o"], X["h"], X["l"], X["c"], X["atr"]
    n, p0 = len(c), c[i]
    stop = p0 - side * S.STOP_ATR * atr[i]
    one_r, ext = abs(p0 - stop), p0
    be = p0 + side * 2 * S.TAKER * p0
    took, part = False, 0.0
    ex = ei = None
    for t in range(i + 1, min(n, i + S.HOLD + 1)):
        if (o[t] <= stop) if side > 0 else (o[t] >= stop):
            ex, ei = o[t], t
            break
        if (l[t] <= stop) if side > 0 else (h[t] >= stop):
            ex, ei = stop, t
            break
        if a is not None and not took:
            tp = p0 + side * a * one_r
            if (h[t] >= tp) if side > 0 else (l[t] <= tp):
                took = True
                part = f * (side * (tp - p0) - S.TAKER * (p0 + tp))
                stop = max(stop, be) if side > 0 else min(stop, be)
        ext = max(ext, h[t]) if side > 0 else min(ext, l[t])
        new = ext - side * S.TRAIL_ATR * atr[t]
        stop = max(stop, new) if side > 0 else min(stop, new)
    still = ex is None and i + S.HOLD >= n - 1
    if ex is None:
        ei = min(n - 1, i + S.HOLD)
        ex = c[ei]
    fund = (X["fcum"][X["didx"][ei]] - X["fcum"][X["didx"][i]]) * p0
    rest = (1 - f if took else 1.0) * (side * (ex - p0) - S.TAKER * (p0 + ex))
    pnl = part + rest - side * fund
    return {"r": pnl / one_r, "exit_t": ei, "stop_pct": one_r / p0, "open": still}


def trades(Xs, a, f) -> pd.DataFrame:
    rows = []
    for X in Xs.values():
        times, n = X["df"].time, len(X["c"])
        for name, (side, sig) in S.SWING.items():
            ends = []
            for i in range(201, n):
                ends = [e for e in ends if e >= i]
                if len(ends) >= S.MAX_OPEN[name] or not np.isfinite(X["atr"][i]) or not sig(X, i):
                    continue
                r = trail_partial(X, i, side, a, f)
                ends.append(r["exit_t"] if not r["open"] else n)
                rows.append({"symbol": X["sym"], "src": name, "side": side, "entry": times.iat[i] + pd.Timedelta("4h"),
                             "exit": times.iat[r["exit_t"]] + pd.Timedelta("4h"), **r})
    x = pd.DataFrame(rows)
    x = x[~x.open]
    return x.assign(risk=x.src.map(S.RISK), r=x.r - 2 * S.SLIP / x.stop_pct)


def main():
    Xs = {s: S.context(s) for s in S.SYMS}
    print("스윙 시스템 (BTC·ETH, 롱 + S5 + S2) · 분할 익절 비교 · 설계 ~2021 / 검증 2022~\n")
    print(f"{'방식':22} | {'거래':>4} {'승률':>5} {'평균R':>6} | {'전체 연':>6} {'낙폭':>6} | {'설계 연':>6} | {'검증 연':>6} {'검증 낙폭':>7} {'검증 승률':>7}")
    base = None
    for a, f in [(None, 0.0)] + list(product((0.5, 1.0, 1.5, 2.0), (0.3, 0.5, 0.7))):
        x = trades(Xs, a, f)
        cv, _ = account_curve(x, max_lev=S.MAX_LEV)
        d = describe(cv)
        te = x[x.entry >= S.SPLIT]
        row = (d["full"][0], d["full"][1], d["design"][0], d["test"][0], d["test"][1], (te.r > 0).mean())
        if base is None:
            base = row
        ok = a is not None and row[5] > base[5] and row[3] >= 0.9 * base[3] and row[4] >= base[4]
        name = "지금 (분할 없음)" if a is None else f"+{a}R 에서 {f*100:.0f}% 익절"
        print(f"{name:22} | {len(x):4} {(x.r > 0).mean()*100:4.0f}% {x.r.mean():+.3f} | {row[0]*100:+5.1f}% {row[1]*100:5.1f}% |"
              f" {row[2]*100:+5.1f}% | {row[3]*100:+5.1f}% {row[4]*100:6.1f}% {row[5]*100:6.0f}% | {'✅' if ok else ''}")


if __name__ == "__main__":
    main()
