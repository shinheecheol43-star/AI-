"""검증: run_daily.py 와 같은 규칙(strategy.py)을 과거 하루하루에 그대로 돌려 본다.

  python backtest.py                 # 2012-01-01 ~ 오늘, 1,000만원
  python backtest.py 2020-01-01 50000000
장중 손절은 시가·저가로 판단 (갭이면 시가), 진입·종가 청산은 그날 종가, 비용 편도 주식 0.15% · ETF 0.05%.
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from data import load_all
from strategy import NAME, Market, cost_of, plan_entries


def run(mk: Market, start="2012-01-01", cap=10_000_000, verbose=False):
    i0 = int(np.searchsorted(mk.dates, pd.Timestamp(start)))
    cash, pos, last_exit, eq, log = float(cap), [], {}, [], []

    def close(p, i, px, why):
        nonlocal cash
        cash += p["qty"] * px * (1 - cost_of(p["code"]))
        key = p["code"] if p["kind"] == "stock" else p["kind"] + p.get("src", "")
        last_exit[key] = i
        pnl = p["qty"] * (px * (1 - cost_of(p["code"])) - p["price"] * (1 + cost_of(p["code"])))
        log.append(dict(kind=p["kind"], name=NAME.get(p["code"], p["code"]), entry=mk.dates[p["entry_i"]], exit=mk.dates[i],
                        pnl=pnl, ret=px / p["price"] - 1, why=why, days=i - p["entry_i"]))
        pos.remove(p)

    for i in range(i0, len(mk.dates)):
        for p in list(pos):
            px = mk.intraday_exit(p, i)
            if px is not None:
                close(p, i, px, "손절")
        for p in list(pos):
            why = mk.close_update(p, i)
            if why:
                close(p, i, mk.price(p["code"], i), why)
        value = sum(p["qty"] * (mk.price(p["code"], i) if np.isfinite(mk.price(p["code"], i)) else p["price"]) for p in pos)
        equity = cash + value
        for s in plan_entries(mk, i, pos, last_exit, equity, cash, cost_of):
            cash -= s["qty"] * s["price"] * (1 + cost_of(s["code"]))
            pos.append(s)
            if verbose:
                print(mk.dates[i].date(), "매수", NAME.get(s["code"]), s["qty"], s["why"])
        eq.append(equity)
    return pd.Series(eq, index=mk.dates[i0:]), pd.DataFrame(log), pos


def report(eq: pd.Series, log: pd.DataFrame, cap: float):
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / cap) ** (1 / yrs) - 1
    mdd = (eq / eq.cummax() - 1).min()
    print(f"기간 {eq.index[0].date()} ~ {eq.index[-1].date()} · 시작 {cap:,.0f}원 → {eq.iloc[-1]:,.0f}원")
    print(f"연 {cagr*100:+.1f}% · 최대 낙폭 {mdd*100:.1f}% · 거래 {len(log)}건")
    if len(log):
        print(log.groupby("kind").agg(건수=("pnl", "size"), 승률=("pnl", lambda x: (x > 0).mean()), 손익합=("pnl", "sum")).round(2).to_string())
    print("연도별: " + " ".join(f"{y}:{(g.iloc[-1] / (eq[eq.index < f'{y}-01-01'].iloc[-1] if (eq.index < f'{y}-01-01').any() else cap) - 1) * 100:+.0f}%"
                              for y, g in eq.groupby(eq.index.year)))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    start = args[0] if args else "2012-01-01"
    cap = float(args[1]) if len(args) > 1 else 10_000_000
    mk = Market(load_all(refresh="--cache" not in sys.argv))
    eq, log, _ = run(mk, start, cap)
    report(eq, log, cap)
