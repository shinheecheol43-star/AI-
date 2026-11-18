"""미국 시스템: 평소 시가총액 상위 10 롱 스윙 + 큰 조정에 QQQ 비중 매수(2년) + 하락 신호 때 하락(인버스) 베이스.

규칙과 후보 값은 결과를 보기 전에 정했다. 상위 10 명단·스윙 틀은 smc.us_dip 과 같음.
  조정 매수 (고정, 지난 검증에서 이웃 값에도 안정): QQQ 1년 고점 대비 −10% → 계좌 50% 매수, 2년 보유, 손절 없음
  A. 스윙 보완 (설계 점수로 고름)
     상위 3: 상위 10 중 120일 수익률 상위 3 만 / 하락장 스윙: 하락장에도 60일 돌파·ATR×3·×5, 위험 0.5% / 위험 1% · 2%
  B. 하락 베이스 (A 에서 고른 값 위에, 설계 점수로 고름). 인버스는 QQQ 일간 −1배 − 연 0.95% 보수로 만든 PSQ 근사
     B1 QQQ 종가<50일선<200일선 (전날) 동안 보유 20% · 40%
     B2 QQQ 50일선<200일선 (데드크로스, 전날) 동안 보유 20% · 40%
     B3 QQQ 숏 신호(S5 스윙저점 이탈 · S2 되돌림 실패) 때만 위험 0.5%, QQQ 기준 손절 ATR×2 · 추적 ×3 · 최대 60일
     겹침: 따로 / 조정 매수 보유 중엔 베이스 안 깜
  비용 편도 0.1%, 배당·현금 이자 제외, 레버리지 없음 (모든 매수 합 ≤ 계좌). 고르기 = 2005~2014 '연수익 ÷ |최대 낙폭|', 채점 = 2015~2026-11.
사용: python -m smc.us_system
"""
from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from .detectors import pivots
from .us_dip import COST, DESIGN, FAST, SLOW, TEST, TOP10, load, stats, yearly


def extras(D):
    F, idx, st, weak = D
    q = F["QQQ"]
    r = q.close.pct_change().fillna(0)
    inv = (1 - r - 0.0095 / 252).cumprod() * 100           # PSQ 근사
    qst = pd.Series("박스", index=idx)
    qst[(q.close > q.ema50) & (q.ema50 > q.ema200)] = "상승"
    qst[(q.close < q.ema50) & (q.ema50 < q.ema200)] = "하락"
    b1 = (qst == "하락").shift(1).fillna(False).astype(bool)
    b2 = (q.ema50 < q.ema200).shift(1).fillna(False).astype(bool)
    dq = q.dropna(subset=["close"])
    _, lows = pivots(dq.reset_index().rename(columns={"index": "time"}), 5)
    sup = pd.Series(np.nan, index=dq.index)
    for _, pc, lvl in lows:
        if pc + 1 < len(dq):
            sup.iloc[pc + 1] = lvl
    sup = sup.ffill().reindex(idx)
    c = q.close
    s5 = sup.notna() & (c < sup) & (c.shift(1) >= sup.shift(1))
    s2 = (q.score <= -1) & (c < q.ema200) & (q.high >= q.ema50) & (c < q.ema50) & (c < q.open)
    sig = (s5 | s2) & (st == "하락")
    mom = pd.DataFrame({s: F[s].mom for s in F})
    return dict(inv=inv, b1=b1, b2=b2, sig=sig, mom=mom)


def run(D, X, lo, hi, top3=False, bear_swing=False, risk=0.01, base=None, w=0.0, priority=False, dip=True):
    F, idx, st, weak = D
    i0, i1 = int(idx.searchsorted(pd.Timestamp(lo))), int(idx.searchsorted(pd.Timestamp(hi)))
    q, inv = F["QQQ"], X["inv"]
    qc = q.close
    peak = qc.rolling(250, min_periods=60).max()
    dd = (qc / peak - 1).to_numpy()
    cash, pos, dips, eq, last_exit = 1.0, [], [], [], {}
    armed, hedge, shorts = True, None, []
    cnt = dict(dip=0, sw=0, base=0, sig=0)
    for i in range(i0, i1):
        # --- 스윙 청산
        for p in list(pos):
            f = F[p["s"]]
            o, l = f.open.iat[i], f.low.iat[i]
            if not np.isfinite(o):
                continue
            ex = o if o <= p["stop"] else (p["stop"] if l <= p["stop"] else None)
            if ex is None:
                p["ext"] = max(p["ext"], f.high.iat[i])
                p["stop"] = max(p["stop"], p["ext"] - p["trail"] * f.atr.iat[i])
                if i - p["i"] >= p["hold"]:
                    ex = f.close.iat[i]
            if ex is not None:
                cash += p["q"] * ex * (1 - COST)
                last_exit[p["s"]] = i
                pos.remove(p)
        # --- 신호 숏 청산 (QQQ 기준 손절)
        for p in list(shorts):
            o, h = q.open.iat[i], q.high.iat[i]
            hit = o >= p["stop"] or h >= p["stop"]
            if not hit:
                p["ext"] = min(p["ext"], q.low.iat[i])
                p["stop"] = min(p["stop"], p["ext"] + 3 * q.atr.iat[i])
            if hit or i - p["i"] >= 60:
                cash += p["q"] * inv.iat[i] * (1 - COST)        # 근사: 그날 인버스 종가
                last_exit["sig"] = i
                shorts.remove(p)
        # --- 조정 매수 청산 (2년)
        c = qc.iat[i]
        for d in list(dips):
            if i - d["i"] >= 500:
                cash += d["q"] * c * (1 - COST)
                dips.remove(d)
        if not armed and dd[i] > -0.05 and not dips:
            armed = True
        # --- 하락 베이스 청산
        on = False
        if base in ("B1", "B2"):
            on = bool(X["b1" if base == "B1" else "b2"].iat[i]) and not (priority and dips)
        if hedge and not on:
            cash += hedge["q"] * inv.iat[i] * (1 - COST)
            hedge = None
        # --- 평가
        val = sum(p["q"] * (F[p["s"]].close.iat[i] if np.isfinite(F[p["s"]].close.iat[i]) else p["p0"]) for p in pos)
        val += sum(d["q"] * c for d in dips) + (hedge["q"] * inv.iat[i] if hedge else 0) + sum(p["q"] * inv.iat[i] for p in shorts)
        E = cash + val
        eq.append(E)
        # --- 조정 매수
        if dip and armed and dd[i] <= -0.10:
            money = min(E * 0.5, cash)
            if hedge and priority:                               # 조정 매수 우선: 베이스 걷기
                cash += hedge["q"] * inv.iat[i] * (1 - COST)
                hedge = None
                money = min(E * 0.5, cash)
            if money > 0:
                dips.append(dict(i=i, q=money / (c * (1 + COST))))
                cash -= money
                cnt["dip"] += 1
            armed = False
        # --- 하락 베이스 깔기
        if on and hedge is None:
            money = min(E * w, cash)
            if money > 0:
                hedge = dict(q=money / (inv.iat[i] * (1 + COST)))
                cash -= money
                cnt["base"] += 1
        # --- 신호 숏
        if base == "B3" and X["sig"].iat[i] and not shorts and last_exit.get("sig", -1) < i and not (priority and dips):
            a = q.atr.iat[i]
            money = min(E * 0.005 / (2 * a / c), cash)
            if money > 0:
                shorts.append(dict(i=i, q=money / (inv.iat[i] * (1 + COST)), stop=c + 2 * a, ext=c))
                cash -= money
                cnt["sig"] += 1
        # --- 롱 스윙
        state = st.iat[i]
        if (state == "하락" and not bear_swing) or len(pos) >= 8:
            continue
        N, sk, tk, hold = FAST if state == "상승" else SLOW
        r_ = (0.005 if state == "하락" else (risk / 2 if weak.iat[i] else risk))
        names = TOP10.get(idx[i].year, [])
        if top3:
            m = X["mom"].iloc[i][[s for s in names if s in X["mom"]]].dropna()
            names = list(m.sort_values(ascending=False).index[:3])
        kmom = F["SPY"].mom.iat[i]
        for s in names:
            if len(pos) >= 8 or any(p["s"] == s for p in pos) or last_exit.get(s, -1) >= i:
                continue
            f = F[s]
            cl, a = f.close.iat[i], f.atr.iat[i]
            if not np.isfinite(cl) or not np.isfinite(a) or f.bars.iat[i] < 300:
                continue
            if not (cl > f[f"hh{N}"].iat[i] and f.close.iat[i - 1] <= f[f"hh{N}"].iat[i - 1]):
                continue
            ev = int(cl > f.ema200.iat[i]) + int(f.score.iat[i] >= 3) + int(f.rsi.iat[i] > 60) + int((cl - f.ema20.iat[i]) / a > 1)
            rng = f.high.iat[i] - f.low.iat[i]
            cpos = (cl - f.low.iat[i]) / rng if rng > 0 else 0.5
            if ev < 3 or not f.mom.iat[i] > kmom or cpos < 0.75:
                continue
            money = min(E * r_ / (sk * a / cl), cash)
            if money <= 0:
                continue
            pos.append(dict(s=s, i=i, p0=cl, q=money / (cl * (1 + COST)), stop=cl - sk * a, ext=cl, trail=tk, hold=hold))
            cash -= money
            cnt["sw"] += 1
    eq = pd.Series(eq, index=idx[i0:i1])
    return stats(eq) | {"eq": eq, **cnt}


def evaluate(D, X, **kw):
    full = (DESIGN[0], TEST[1])
    f, b = run(D, X, *full, **kw), run(D, X, *TEST, **kw)
    a = stats(f["eq"][f["eq"].index < DESIGN[1]])
    return a, b, f, yearly(f["eq"])


def main():
    D = load()
    X = extras(D)
    hdr = f"  {'구성':34} | {'2005~2014 연':>12} {'낙폭':>6} {'점수':>5} | {'2015~2026 연':>12} {'낙폭':>6} | {'전체 연':>7} {'낙폭':>6} {'1,000만원→':>13} | 손실해"

    def line(name, r):
        a, b, f, ys = r
        print(f"  {name:34} | {a['cagr']*100:+11.1f}% {a['mdd']*100:5.1f}% {a['score']:5.2f} | {b['cagr']*100:+11.1f}% {b['mdd']*100:5.1f}% |"
              f" {f['cagr']*100:+6.1f}% {f['mdd']*100:5.1f}% {f['final']*1e7:13,.0f} | {sum(v < 0 for v in ys.values())}년", flush=True)

    print("미국 시스템 · 상위 10 롱 스윙 + QQQ −10% 조정 50% 2년 + 하락 베이스 · 비용 편도 0.1% · 배당 제외 · 평가금액 낙폭\n")
    print("■ A. 스윙 보완 (조정 매수 고정, 하락 베이스 없음)")
    print(hdr)
    A = {}
    line("(참고) 조정 매수 없이 스윙만", evaluate(D, X, dip=False))
    for top3, bs, risk in product((False, True), (False, True), (0.01, 0.02)):
        name = f"{'상위3' if top3 else '상위10'} · 하락장 스윙 {'O' if bs else 'X'} · 위험 {risk*100:.0f}%"
        A[name] = (dict(top3=top3, bear_swing=bs, risk=risk), evaluate(D, X, top3=top3, bear_swing=bs, risk=risk))
        line(name, A[name][1])
    bestA = max(A, key=lambda n: A[n][1][0]["score"])
    kwA = A[bestA][0]
    print(f"  → 고른 값: {bestA}\n")
    print("■ B. 하락 베이스 (A 위에)")
    print(hdr)
    B = {"없음": (dict(), A[bestA][1])}
    line("없음", A[bestA][1])
    for base, w, pr in [(b, w, p) for b in ("B1", "B2") for w in (0.2, 0.4) for p in (False, True)] + [("B3", 0, False), ("B3", 0, True)]:
        name = f"{base}{' ' + str(int(w*100)) + '%' if w else ''} · {'조정 매수 우선' if pr else '따로'}"
        r = evaluate(D, X, **kwA, base=base, w=w, priority=pr)
        B[name] = (dict(base=base, w=w, priority=pr), r)
        line(name, r)
    bestB = max(B, key=lambda n: B[n][1][0]["score"])
    print(f"  → 고른 값: {bestB}")
    final = B[bestB][1]
    print("\n■ 최종 연도별 (QQQ 보유 비교)")
    q = D[0]["QQQ"].close
    for y, v in final[3].items():
        b = q[(q.index >= f"{y}-01-01") & (q.index < f"{y + 1}-01-01")]
        print(f"  {y}: {v*100:+6.1f}%  | QQQ {(b.iloc[-1]/b.iloc[0]-1)*100:+6.1f}%")
    f = final[2]
    print(f"  매매: 조정 매수 {f['dip']}번 · 스윙 {f['sw']}건 · 하락 베이스 {f['base']}번 · 신호 숏 {f['sig']}건")


if __name__ == "__main__":
    main()
