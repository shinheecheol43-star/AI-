"""미국 포지션 스위칭: QQQ 롱 100% / 50% / 현금 / 인버스 를 신호에 따라 바꿔 탄다 (일봉).

규칙과 후보 값은 결과를 보기 전에 정했다. 신호는 그날 종가로 판단, 그날 종가에 바꿈 (점검: 하루 늦게 바꾸기).
  M  이동평균 배열: QQQ 종가>50일>200일 = 100% · 종가<50일<200일 = 인버스 · 나머지 = 50%
  MV M + ① 반등 확인: 1년 고점 대비 −10% 이상 빠진 뒤 20일선 위 마감 → 100% (배열이 하락이어도)
         + ② 늦은 숏 금지: 고점 대비 −20% 보다 더 빠졌으면 인버스 대신 현금
  B  시장 폭: 그해 상위 10 중 50일선 위 비율 ≥70% = 100% · ≤30% 이고 QQQ<200일선 = 인버스 · 나머지 = 50%
  공통: 확인 기간 1 · 3 · 5일 (새 목표가 그만큼 이어져야 바꿈), 인버스 비중 0% (현금) · 40%
  인버스 = QQQ 일간 −1배 − 연 0.95% (PSQ 근사). 비용 = 바뀐 비중 × 0.1%. 배당·현금 이자 제외.
고르기 = 2005~2014 '연수익 ÷ |최대 낙폭|', 채점 = 2015~2026-11.
사용: python -m smc.us_switch
"""
from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from .us_dip import COST, DESIGN, TEST, TOP10, load, stats, yearly


def signals(D):
    F, idx, _, _ = D
    q = F["QQQ"]
    c = q.close
    peak = c.rolling(250, min_periods=60).max()
    dd = c / peak - 1
    up = (c > q.ema50) & (q.ema50 > q.ema200)
    down = (c < q.ema50) & (q.ema50 < q.ema200)
    above = pd.DataFrame({s: (F[s].close > F[s].ema50).where(F[s].close.notna()) for s in F if s not in ("SPY", "QQQ")})
    breadth = pd.Series([above.loc[t, [s for s in TOP10.get(t.year, []) if s in above]].mean() for t in idx], index=idx)
    # 반등 확인 상태: −10% 이상 빠진 적이 있고 아직 배열이 상승으로 돌아오지 않았을 때 20일선 위
    deep, flag = False, []
    for t in idx:
        if dd[t] <= -0.10:
            deep = True
        if up[t]:
            deep = False
        flag.append(deep and c[t] > q.ema20[t])
    rebound = pd.Series(flag, index=idx)
    return dict(dd=dd, up=up, down=down, breadth=breadth, rebound=rebound, below200=c < q.ema200)


def target(S, rule, short_w):
    neg = -short_w
    if rule == "M":
        t = pd.Series(0.5, index=S["dd"].index)
        t[S["up"]] = 1.0
        t[S["down"]] = neg
    elif rule == "MV":
        t = pd.Series(0.5, index=S["dd"].index)
        t[S["up"]] = 1.0
        t[S["down"]] = np.where(S["dd"][S["down"]] < -0.20, 0.0, neg)
        t[S["rebound"]] = 1.0
    else:
        b = S["breadth"]
        t = pd.Series(0.5, index=b.index)
        t[b >= 0.7] = 1.0
        t[(b <= 0.3) & S["below200"]] = neg
    return t


def confirm(t: pd.Series, n: int) -> pd.Series:
    out, cur, cand, run_ = [], 0.0, None, 0
    for v in t.to_numpy():
        if v == cur:
            cand, run_ = None, 0
        elif v == cand:
            run_ += 1
        else:
            cand, run_ = v, 1
        if cand is not None and run_ >= n:
            cur, cand, run_ = cand, None, 0
        out.append(cur)
    return pd.Series(out, index=t.index)


def backtest(D, w: pd.Series, lo, hi, lag=0):
    F, idx = D[0], D[1]
    r = F["QQQ"].close.pct_change().fillna(0)
    rinv = -r - 0.0095 / 252
    w = w.shift(lag).fillna(0)
    held = w.shift(1).fillna(0)
    ret = held.clip(lower=0) * r + (-held.clip(upper=0)) * rinv - w.diff().abs().fillna(0) * COST
    m = (idx >= lo) & (idx < hi)
    eq = (1 + ret[m]).cumprod()
    return stats(eq) | {"eq": eq}


def quality(D, w, lo, hi):
    """바꾼 뒤 60거래일 QQQ 수익: 롱으로 올렸을 때 / 인버스로 내렸을 때."""
    c = D[0]["QQQ"].close
    fwd = c.shift(-60) / c - 1
    ch = w.diff().fillna(0)
    m = (w.index >= lo) & (w.index < hi)
    to_long = fwd[(ch > 0) & (w == 1.0) & m]
    to_short = fwd[(ch < 0) & (w < 0) & m]
    return len(to_long), to_long.mean(), len(to_short), to_short.mean()


def main():
    D = load()
    S = signals(D)
    full = (DESIGN[0], TEST[1])
    F = D[0]
    hdr = (f"  {'규칙':22} | {'2005~2014 연':>12} {'낙폭':>6} {'점수':>5} | {'2015~2026 연':>12} {'낙폭':>6} | {'전체 연':>7} {'낙폭':>6} {'1,000만원→':>13} |"
           f" 손실해 | 연 전환 | 하루늦게 전체")
    print("미국 포지션 스위칭 (QQQ 100% · 50% · 현금 · 인버스) · 비용 0.1% · 배당 제외 · 평가금액 낙폭\n")
    print(hdr)
    rows = {}

    def line(name, w):
        a = stats(backtest(D, w, *full)["eq"][lambda e: e.index < DESIGN[1]])
        b, f = backtest(D, w, *TEST), backtest(D, w, *full)
        l1 = backtest(D, w, *full, lag=1)
        ys = yearly(f["eq"])
        m = (w.index >= full[0])
        sw = (w.diff().abs() > 0)[m].sum() / ((w.index[m][-1] - w.index[m][0]).days / 365.25)
        rows[name] = (a, b, f, ys, w)
        print(f"  {name:22} | {a['cagr']*100:+11.1f}% {a['mdd']*100:5.1f}% {a['score']:5.2f} | {b['cagr']*100:+11.1f}% {b['mdd']*100:5.1f}% |"
              f" {f['cagr']*100:+6.1f}% {f['mdd']*100:5.1f}% {f['final']*1e7:13,.0f} | {sum(v < 0 for v in ys.values()):4}년 | {sw:5.1f}회 |"
              f" {l1['cagr']*100:+5.1f}% {l1['mdd']*100:5.1f}%", flush=True)

    line("QQQ 보유", pd.Series(1.0, index=D[1]))
    for rule, n, sw in product(("M", "MV", "B"), (1, 3, 5), (0.0, 0.4)):
        line(f"{rule} · 확인 {n}일 · 인버스 {int(sw*100)}%", confirm(target(S, rule, sw), n))
    cands = [k for k in rows if k != "QQQ 보유"]
    best = max(cands, key=lambda k: rows[k][0]["score"])
    print(f"\n  → 설계 점수로 고른 규칙: {best}")
    for rule in ("M", "MV", "B"):
        sc = [rows[k][0]["score"] for k in cands if k.startswith(rule + " ")]
        print(f"     {rule} 후보 6개 설계 점수 평균 {np.mean(sc):.2f} · 검증 연수익 평균 {np.mean([rows[k][1]['cagr'] for k in cands if k.startswith(rule + ' ')])*100:+.1f}%")
    a, b, f, ys, w = rows[best]
    nl, ml, ns, ms = quality(D, w, *full)
    print(f"\n  전환 품질 (바꾼 뒤 60거래일 QQQ): 100% 로 올림 {nl}번 평균 {ml*100:+.1f}% · 인버스로 내림 {ns}번 평균 {ms*100:+.1f}%"
          f" (아무 날 평균 {((F['QQQ'].close.shift(-60)/F['QQQ'].close-1)[F['QQQ'].close.index>=full[0]]).mean()*100:+.1f}%)")
    m = w.index >= full[0]
    print("  비중별 기간: " + " · ".join(f"{('인버스' if v < 0 else f'{int(v*100)}%')} {p*100:.0f}%" for v, p in w[m].value_counts(normalize=True).sort_index().items()))
    q = F["QQQ"].close
    print("\n  연도 | 고른 규칙 | QQQ 보유")
    for y, v in ys.items():
        bq = q[(q.index >= f"{y}-01-01") & (q.index < f"{y + 1}-01-01")]
        print(f"  {y} | {v*100:+8.1f}% | {(bq.iloc[-1]/bq.iloc[0]-1)*100:+7.1f}%")
    print("\n  2020·2022 전환 기록 (고른 규칙):")
    ch = w[w.diff().fillna(0) != 0]
    for t, v in ch[(ch.index >= "2020-01-01") & (ch.index < "2023-06-01")].items():
        print(f"    {t.date()} → {'인버스' if v < 0 else f'{int(v*100)}%'}  (QQQ {q[t]:.0f}, 고점 대비 {S['dd'][t]*100:+.0f}%)")


if __name__ == "__main__":
    main()
