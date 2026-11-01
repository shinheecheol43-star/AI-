"""고승률 전략을 '유연하게' 운용하면 되는가: 워크포워드(주기적으로 다시 고르기) 검증.

방식 (사람이 실제로 할 수 있는 그대로, 미래 정보 없음)
  후보: highwin.py 1차 3,054개 (장세 필터 없음) + highwin2.py 2차 3,133개 (일봉 장세 필터)
  매 주기(1개월 또는 3개월) 시작 시점에
    직전 L 개월(3·6·12·24) 성적만 보고, 승률 ≥ W(80% / 85%) · 기대값 > 0 · 거래 ≥ 20 인 후보 중
    그 기간 누적 수익이 가장 큰 상위 K 개(1 / 5 / 20)를 고름 → 다음 주기 동안 그 전략들로 매매
    고를 게 없으면 쉰다.
  K 개를 고르면 각 거래 크기는 1/K (레버리지 lev 를 K 개가 나눠 씀)
결과는 2019~ 전체와 2022~ 를 따로. 레버리지 1·3·5배.
'다시 고르는 방식' 자체도 여러 개 시험하므로, 대부분이 좋아야 의미가 있다 (하나만 좋으면 우연).

사용:  python -m smc.walkforward
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from itertools import product

import numpy as np
import pandas as pd

from . import highwin, highwin2

START = pd.Timestamp("2019-01-01", tz="UTC")
TEST = pd.Timestamp("2022-01-01", tz="UTC")
END = pd.Timestamp("2026-10-01", tz="UTC")


def load_all():
    c1 = [("1차",) + c for c in product(highwin.TFS, highwin.CONDS, (False, True), (1, -1))]
    c2 = [("2차",) + c for c in product(highwin2.TFS, highwin2.CONDS, (False, True), (1, -1))]
    with ProcessPoolExecutor(4) as pool:
        res = [r for chunk in pool.map(_run, c1 + c2, chunksize=2) for r in chunk]
    keys = [k for k, _ in res]
    big = pd.concat([x[["time", "exit", "ret"]].assign(cid=i) for i, (_, x) in enumerate(res)], ignore_index=True)
    return keys, big


def _run(c):
    fn = highwin.job if c[0] == "1차" else highwin2.job
    return [((c[0],) + k, x) for k, x in fn(c[1:])]


def monthly(big: pd.DataFrame):
    """후보별 · 청산 월별 거래 수, 이긴 수, 수익 합 (직전 L 개월 성적을 빨리 계산하려고)."""
    m = big.exit.dt.tz_localize(None).dt.to_period("M")
    g = big.assign(m=m, w=(big.ret > 0).astype(int)).groupby(["cid", "m"]).agg(n=("ret", "size"), w=("w", "sum"), s=("ret", "sum"))
    months = pd.period_range("2017-12", END.tz_localize(None).to_period("M"), freq="M")
    cids = big.cid.unique()
    idx = pd.MultiIndex.from_product([cids, months], names=["cid", "m"])
    g = g.reindex(idx, fill_value=0)
    return {k: g[k].unstack("cid").cumsum() for k in ("n", "w", "s")}


def walk(big: pd.DataFrame, M, L: int, W: float, K: int, step: int) -> pd.DataFrame:
    picks = []
    t = START
    entry_m = big.time.dt.tz_localize(None).dt.to_period("M")
    while t < END:
        nxt = t + pd.DateOffset(months=step)
        last = t.tz_localize(None).to_period("M") - 1           # 직전 달까지 청산된 거래만
        first = last - L
        n, w, s = (M[k].loc[last] - M[k].loc[first] for k in ("n", "w", "s"))
        ok = (n >= 20) & (w / n.where(n > 0) >= W) & (s > 0)
        chosen = s[ok].sort_values(ascending=False).head(K).index
        if len(chosen):
            a, b = t.tz_localize(None).to_period("M"), nxt.tz_localize(None).to_period("M")
            fut = big[big.cid.isin(chosen) & (entry_m >= a) & (entry_m < b)]
            picks.append(fut.assign(w=1.0 / K))
        t = nxt
    return pd.concat(picks, ignore_index=True) if picks else pd.DataFrame(columns=["time", "exit", "ret", "cid", "w"])


def perf(x: pd.DataFrame, lev: float, a, b):
    x = x[(x.time >= a) & (x.time < b)].sort_values("exit")
    if not len(x):
        return 0.0, 0.0, 0.0, 0
    r = np.maximum(x.ret.to_numpy() * lev * x.w.to_numpy(), -1)
    eq = np.cumprod(1 + r)
    yrs = (b - a).days / 365.25
    mdd = (eq / np.maximum.accumulate(np.concatenate([[1], eq]))[1:] - 1).min()
    return max(eq[-1], 1e-9) ** (1 / yrs) - 1, mdd, (x.ret > 0).mean(), len(x)


def main():
    keys, big = load_all()
    M = monthly(big)
    print(f"후보 전략 {len(keys)}개 · 주기마다 직전 성적으로 다시 고름 · 비용 포함\n")
    print(f"{'주기':4} {'보는기간':5} {'승률≥':4} {'개수':3} | {'2019~ 1배':>9} {'낙폭':>5} | {'2022~ 1배':>9} {'낙폭':>5} {'승률':>4} {'거래':>5} |"
          f" {'2022~ 3배':>9} {'낙폭':>5} | {'2022~ 5배':>9} {'낙폭':>5}")
    rows = []
    for step, L, W, K in product((1, 3), (3, 6, 12, 24), (0.80, 0.85), (1, 5, 20)):
        x = walk(big, M, L, W, K, step)
        a = perf(x, 1, START, END)
        b1, b3, b5 = (perf(x, v, TEST, END) for v in (1, 3, 5))
        rows.append((step, L, W, K, a[0], b1[0], b3[0], b5[0]))
        print(f"{step:2}달 {L:3}달 {W*100:4.0f}% {K:3} | {a[0]*100:+8.1f}% {a[1]*100:4.0f}% | {b1[0]*100:+8.1f}% {b1[1]*100:4.0f}% {b1[2]*100:3.0f}% {b1[3]:5} |"
              f" {b3[0]*100:+8.1f}% {b3[1]*100:4.0f}% | {b5[0]*100:+8.1f}% {b5[1]*100:4.0f}%")
    R = pd.DataFrame(rows, columns=["step", "L", "W", "K", "all1", "te1", "te3", "te5"])
    print(f"\n■ 다시 고르는 방식 {len(R)}개 중 2022~ 1배 수익이 플러스: {(R.te1 > 0).sum()}개 · 5배 플러스: {(R.te5 > 0).sum()}개")
    print(f"  2022~ 1배 연수익 중간값 {R.te1.median()*100:+.1f}% · 최고 {R.te1.max()*100:+.1f}% · 최저 {R.te1.min()*100:+.1f}%")


if __name__ == "__main__":
    main()
