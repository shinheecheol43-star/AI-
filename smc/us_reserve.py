"""미국: 처음 1,000만원은 시스템으로, 매달 50만원은 현금 예비금으로 모았다가 큰 낙폭 뒤 반전 신호에 QQQ 에 크게.

규칙과 후보 값은 결과를 보기 전에 정했다 (smc.us_combo.run 의 contrib·reserve).
  시스템: 방어+스윙30% (−10% 3분할 80% · 수익권 추적 · 평소 지수 스위칭 50% · 스윙 30%) / 균형 (QQQ 스위칭 100%)
  예비금 투입: QQQ 1년 고점 대비 −X% (15 · 20 · 30) 를 찍은 뒤 · 신호 '바로' / '20일선 위 마감' 에 예비금 전부
  예비금 매수분 매도: '추적' (+10% 뒤 max(평균가, 고점×0.85) 아래 → 다시 예비금) / '2년' / '계속' (안 팖, 다음 큰 낙폭엔 새 예비금만 추가)
  비교: QQQ 적립식 (처음 1,000만원 + 매달 50만원 바로 매수) · 시스템에 50만원 바로 넣기
  평가: 시작 2001 · 2005 · 2015 각각, 최종 금액 · 넣은 돈 · 연 환산 수익률(돈 넣은 시점 반영, IRR) · 넣은 돈 대비 최악 손실 · 최대 낙폭
  비용 편도 0.1%, 배당·현금 이자 제외.
사용: python -m smc.us_reserve
"""
from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from .us_combo import prep, run
from .us_leaders import load

C = 0.05                     # 50만원 / 1,000만원


def irr(flows):
    t0 = flows[0][0]
    ts = np.array([(t - t0).days / 365.25 for t, _ in flows])
    v = np.array([x for _, x in flows])
    lo, hi = -0.9, 1.0
    for _ in range(100):
        mid = (lo + hi) / 2
        if (v / (1 + mid) ** ts).sum() > 0:
            lo = mid
        else:
            hi = mid
    return mid


def summary(r):
    eq = r["eq"]
    inv = pd.Series(0.0, index=eq.index)
    for t, x in r["flows"][:-1]:
        inv[t] += -x
    inv = inv.cumsum()
    return dict(final=r["final"], invested=r["invested"], irr=irr(r["flows"]), worst=(eq / inv - 1).min(), mdd=(eq / eq.cummax() - 1).min())


def dca(D, lo, hi):
    F, idx = D["F"], D["idx"]
    c = F["QQQ"].close
    m = (idx >= lo) & (idx < hi)
    days = idx[m]
    q, flows, eq = 0.0, [], []
    for k, t in enumerate(days):
        if k == 0 or t.month != days[k - 1].month:
            amt = 1.0 if k == 0 else C
            q += amt * (1 - 0.001) / c[t]
            flows.append((t, -amt))
        eq.append(q * c[t])
    eq = pd.Series(eq, index=days)
    flows.append((days[-1], eq.iloc[-1]))
    return {"eq": eq, "flows": flows, "final": eq.iloc[-1], "invested": -sum(v for _, v in flows[:-1])}


def main():
    D = prep(load())
    end = "2026-11-19"
    SYS = {"방어+스윙30": dict(L=10, W=0.8, core=0.5, S=0.3), "균형": dict(L=10, W=0.0, core=1.0, S=0.0)}
    cfg = [("QQQ 적립식", None, None)]
    for s in SYS:
        cfg.append((f"{s} · 50만원 바로 시스템에", s, None))
    for s, X, sig, ex in product(SYS, (0.15, 0.20, 0.30), ("바로", "20일선"), ("추적", "2년", "계속")):
        cfg.append((f"{s} · 예비금 −{int(X*100)}% {sig} {ex}", s, (X, sig, ex)))
    print("처음 1,000만원 + 매달 50만원 · 비용 0.1% · 배당·현금 이자 제외 · 금액 단위 만원\n")
    res = {}
    for lo in ("2001-01-01", "2005-01-01", "2015-01-01"):
        print(f"■ 시작 {lo[:4]}년")
        print(f"  {'구성':34} | {'최종':>9} {'넣은 돈':>7} {'배수':>5} | {'연 환산':>7} | {'넣은 돈 대비 최악':>10} | {'최대 낙폭':>7}")
        for name, s, rv in cfg:
            r = dca(D, lo, end) if s is None else run(D, lo, end, **SYS[s], contrib=C, reserve=rv)
            x = summary(r)
            res[(lo, name)] = x
            print(f"  {name:34} | {x['final']*1000:9,.0f} {x['invested']*1000:7,.0f} {x['final']/x['invested']:5.2f} | {x['irr']*100:+6.1f}% | {x['worst']*100:+9.0f}% | {x['mdd']*100:6.0f}%", flush=True)
        print()
    print("■ 세 시작 시점 평균 (연 환산 · 최악 손실 · 최대 낙폭)")
    for name, _, _ in cfg:
        xs = [res[(lo, name)] for lo in ("2001-01-01", "2005-01-01", "2015-01-01")]
        print(f"  {name:34} | 연 {np.mean([x['irr'] for x in xs])*100:+5.1f}% · 최악 {np.mean([x['worst'] for x in xs])*100:+4.0f}% · 낙폭 {np.mean([x['mdd'] for x in xs])*100:4.0f}% · 2001 시작 연 {xs[0]['irr']*100:+.1f}%")


if __name__ == "__main__":
    main()
