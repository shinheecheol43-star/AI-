"""스윙 전략 롱·숏 비교: 4시간봉 20봉 돌파(숏은 이탈) · 강한 신호(근거 ≥ 4) · 한 번에 진입 · 추적 손절.

근거 5가지는 모두 '신호 방향 기준'으로 계산된 값(research.py)이라 숏에도 같은 식을 쓴다.
  4h 추세 일치, 일봉 국면 = 신호 방향으로 +3, RSI 상위 1/3, 20EMA 이격 상위 1/3, 펀딩비 쏠림 하위 1/3
  (분위 기준값은 방향별로 설계 구간 2018–2021 에서만 계산)
청산: 최초 손절 신호가 ∓ ATR × 2, 추적 손절 최고가(숏은 최저가) ∓ ATR × 3, 최대 120봉.
자금: 거래당 1% 리스크, 복리, 레버리지 합계 3배 이하. Bybit 수수료와 실제 펀딩비(숏은 받거나 냄).

사용:  python -m smc.swing_ls
"""
from __future__ import annotations

import pandas as pd

from .research import OUT as DATA, TAKER
from .research_report import SPLIT
from .split_entry import HOLD, STOP_ATR, TRAIL_ATR
from .split_evidence import context


def strong(side: int) -> pd.DataFrame:
    d = pd.read_pickle(DATA)
    d = d[(d.tf == "4h") & (d.side == side)]
    tr = d[d.time < SPLIT]                       # 기준값은 그 방향의 4시간봉 신호 전체로 (split_entry.py 와 동일)
    q_rsi, q_d20, q_f = tr.rsi.quantile(2 / 3), tr.dist_ema20.quantile(2 / 3), tr.funding_rank.quantile(1 / 3)
    st = ((d.trend4h > 0).astype(int) + (d.day_score >= 3) + (d.rsi > q_rsi) + (d.dist_ema20 > q_d20)
          + (d.funding_rank <= q_f))
    return d[(st >= 4) & (d.family == "20봉돌파")]


def simulate(ctx: dict, i: int, side: int) -> dict:
    o, h, l, c, atr = ctx["o"], ctx["h"], ctx["l"], ctx["c"], ctx["atr"]
    n, p0 = len(c), c[i]
    stop = p0 - side * STOP_ATR * atr[i]
    one_r = abs(p0 - stop)
    ext, ex, ei = p0, None, None
    for t in range(i + 1, min(n, i + HOLD + 1)):
        if (o[t] <= stop) if side > 0 else (o[t] >= stop):
            ex, ei = o[t], t
            break
        if (l[t] <= stop) if side > 0 else (h[t] >= stop):
            ex, ei = stop, t
            break
        ext = max(ext, h[t]) if side > 0 else min(ext, l[t])
        new = ext - side * TRAIL_ATR * atr[t]
        stop = max(stop, new) if side > 0 else min(stop, new)
    if ex is None:
        ei = min(n - 1, i + HOLD)
        ex = c[ei]
    fund = (ctx["fcum"][ctx["didx"][ei]] - ctx["fcum"][ctx["didx"][i]]) * p0
    pnl = side * (ex - p0) - TAKER * (p0 + ex) - side * fund
    return {"r": pnl / one_r, "exit_t": ei, "stop_pct": one_r / p0}


def trades(sides=(1, -1)) -> pd.DataFrame:
    ctxs = {s: context(s) for s in ("BTC", "ETH")}
    rows = []
    for side in sides:
        sig = strong(side)
        for sym, ctx in ctxs.items():
            for _, s in sig[sig.symbol == sym].iterrows():
                i = ctx["idx"][s.time]
                r = simulate(ctx, i, side)
                rows.append({"symbol": sym, "side": side, "entry": ctx["df"].time.iat[i] + pd.Timedelta("4h"),
                             "exit": ctx["df"].time.iat[r["exit_t"]] + pd.Timedelta("4h"), **r})
    return pd.DataFrame(rows).sort_values("entry").reset_index(drop=True)


def equity_curve(x: pd.DataFrame, start=1000.0, risk=0.01, max_lev=3.0) -> pd.Series:
    bal, open_pos, ev = start, [], []
    for _, t in x.sort_values("entry").iterrows():
        for p in sorted([p for p in open_pos if p["exit"] <= t.entry], key=lambda p: p["exit"]):
            bal += p["pnl"]
            open_pos.remove(p)
            ev.append((p["exit"], bal))
        planned = bal * risk / t.stop_pct
        n = min(planned, max_lev * bal - sum(p["notional"] for p in open_pos))
        if n <= 0:
            continue
        open_pos.append({"exit": t.exit, "pnl": bal * risk * (n / planned) * t.r, "notional": n})
    for p in sorted(open_pos, key=lambda p: p["exit"]):
        bal += p["pnl"]
        ev.append((p["exit"], bal))
    return pd.Series([b for _, b in ev], index=pd.DatetimeIndex([e for e, _ in ev])).sort_index()


def describe(cv: pd.Series, start=1000.0) -> dict:
    lo, end = pd.Timestamp("2018-03-15", tz="UTC"), pd.Timestamp("2026-10-01", tz="UTC")
    full = pd.concat([pd.Series([start], index=[lo]), cv])

    def seg(a, b):
        c = full[(full.index >= a) & (full.index < b)]
        b0 = full[full.index < a].iloc[-1] if (full.index < a).any() else start
        allc = pd.concat([pd.Series([b0], index=[a]), c])
        return (c.iloc[-1] / b0) ** (365.25 / (b - a).days) - 1, (allc / allc.cummax() - 1).min()

    years, prev = {}, start
    for y in range(2018, 2027):
        c = cv[cv.index.year == y]
        years[y] = (c.iloc[-1] / prev - 1) if len(c) else 0.0
        prev = c.iloc[-1] if len(c) else prev
    return {"full": seg(lo, end), "design": seg(lo, SPLIT), "test": seg(SPLIT, end), "years": years, "final": cv.iloc[-1]}


def main():
    x = trades()
    print(f"{'스윙':12} | {'전체 연평균':>9} {'낙폭':>7} | {'설계':>7} | {'검증':>7} | 거래 승률 평균R(설계/검증)")
    rows = {}
    for name, m in (("롱만", x.side > 0), ("숏만", x.side < 0), ("롱 + 숏", x.side != 0)):
        y = x[m]
        d = describe(equity_curve(y))
        rows[name] = d
        a, b = y[y.entry < SPLIT], y[y.entry >= SPLIT]
        print(f"{name:12} | {d['full'][0]*100:+8.1f}% {d['full'][1]*100:6.1f}% | {d['design'][0]*100:+6.1f}% | {d['test'][0]*100:+6.1f}% |"
              f" {len(y):4} {(y.r > 0).mean()*100:4.1f}% {a.r.mean():+.2f}/{b.r.mean():+.2f}")
    print("\n연도별")
    print(f"{'':12} " + " ".join(f"{yy:>6}" for yy in range(2018, 2027)))
    for name, d in rows.items():
        print(f"{name:12} " + " ".join(f"{d['years'][yy]*100:+5.0f}%" for yy in range(2018, 2027)))


if __name__ == "__main__":
    main()
