"""미국 통합: QQQ 큰 조정 분할 매수(수익권 추적 손절) + 평소 QQQ 스위칭 + 주도주 스윙 — 비중과 깊이를 함께 고른다 (일봉).

규칙과 후보 값은 결과를 보기 전에 정했다.
  조정 매수: QQQ 1년 고점 대비 −L% · −(L+10)% · −(L+20)% 에서 W/3 씩 (L = 10 · 15 · 20, W = 50 · 80 · 100%)
     매도: 평균가 +10% 넘은 뒤 max(평균가, 고점×0.85) 아래 / 평균가 −25% (후보: 있음·없음) / +10% 못 가면 첫 매수 2년 뒤
     매도 뒤 다시 쓰려면 1년 고점 대비 낙폭이 −5% 보다 작아진 뒤
  평소 지수: 없음 / 계좌 50% × 스위칭 비중 (QQQ 종가>50일>200일 = 1 · 종가<50일<200일 = 0 · 나머지 0.5, 5일 확인) — 바뀔 때만 맞춤
  주도주 스윙 (smc.us_leaders, 섹터당 2 · 위험 1%): 스윙에 쓰는 돈 한도 S = 0 · 30 · 60% 
  돈 쓰는 순서: 조정 매수 → 평소 지수 → 스윙. 합계 ≤ 계좌 (레버리지 없음). 비용 편도 0.1%, 배당 제외.
고르기 = 2001~2014 (닷컴 끝 · 2008 포함) '연수익 ÷ |최대 낙폭|', 채점 = 2015~2026-11. 설계 상위 10 만 검증 구간 따로 돌림.
사용: python -m smc.us_combo
"""
from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from .us_dip import COST, FAST, SLOW, stats, yearly
from .us_leaders import SECTOR, load
from .us_switch import confirm

DESIGN, TEST = ("2001-01-01", "2015-01-01"), ("2015-01-01", "2026-11-19")


def prep(D):
    q = D["F"]["QQQ"]
    c = q.close
    t = pd.Series(0.5, index=c.index)
    t[(c > q.ema50) & (q.ema50 > q.ema200)] = 1.0
    t[(c < q.ema50) & (q.ema50 < q.ema200)] = 0.0
    D["sw"] = confirm(t, 5)
    D["qdd"] = (c / c.rolling(250, min_periods=60).max() - 1)
    return D


def run(D, lo, hi, L=20, W=1.0, stop=None, core=0.0, S=0.6, log=None, exit2y=False, tranches=3, swlog=None):
    F, idx, st, weak, elig = D["F"], D["idx"], D["st"], D["weak"], D["elig"]
    i0, i1 = int(idx.searchsorted(pd.Timestamp(lo))), int(idx.searchsorted(pd.Timestamp(hi)))
    qc = F["QQQ"].close.to_numpy()
    dd = D["qdd"].to_numpy()
    swt = D["sw"].to_numpy()
    cash, pos, eq, last_exit = 1.0, [], [], {}
    dip = None                                   # {q, cost, n, first_i, peak, on}
    levels_used, armed = 0, True
    core_q, core_t = 0.0, None
    for i in range(i0, i1):
        c = qc[i]
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
                if swlog is not None:
                    swlog.append(dict(s=p["s"], exit=idx[i], ret=ex / p["p0"] - 1 - 2 * COST))
        # --- 조정 매수 청산 (종가 판단)
        if dip:
            avg = dip["cost"] / dip["q"]
            dip["peak"] = max(dip["peak"], c)
            if dip["peak"] >= avg * 1.10:
                dip["on"] = True
            why = None
            if exit2y:
                if i - dip["first_i"] >= 500:
                    why = "2년"
            elif dip["on"] and c <= max(avg, dip["peak"] * 0.85):
                why = "수익권 손절"
            elif stop and c <= avg * (1 - stop):
                why = "손절"
            elif not dip["on"] and i - dip["first_i"] >= 500:
                why = "2년"
            if why:
                cash += dip["q"] * c * (1 - COST)
                if log is not None:
                    log.append(dict(buy=idx[dip["first_i"]].date(), sell=idx[i].date(), n=dip["n"], ret=c / avg - 1, why=why))
                dip, levels_used, armed = None, 0, False
        if not armed and dd[i] > -0.05:
            armed = True
        # --- 평가
        val = sum(p["q"] * (F[p["s"]].close.iat[i] if np.isfinite(F[p["s"]].close.iat[i]) else p["p0"]) for p in pos)
        val += (dip["q"] * c if dip else 0) + core_q * c
        E = cash + val
        eq.append(E)
        # --- 조정 분할 매수
        while armed and levels_used < tranches and dd[i] <= -(L + 10 * levels_used) / 100:
            money = min(E * W / tranches, cash)
            if money <= 0 and core_q > 0:                      # 평소 지수를 덜어서라도 조정 매수
                take = min(core_q, E * W / tranches / c)
                core_q -= take
                cash += take * c * (1 - COST)
                money = min(E * W / tranches, cash)
            if money > 0:
                q = money / (c * (1 + COST))
                if dip is None:
                    dip = dict(q=0.0, cost=0.0, n=0, first_i=i, peak=c, on=False)
                dip["q"] += q
                dip["cost"] += q * c
                dip["n"] += 1
                cash -= money
            levels_used += 1
        # --- 평소 지수 (스위칭, 바뀔 때만 맞춤)
        if core > 0 and swt[i] != core_t:
            core_t = swt[i]
            want = E * core * core_t / c
            if want < core_q:
                cash += (core_q - want) * c * (1 - COST)
                core_q = want
            else:
                add = min((want - core_q) * c, cash)
                if add > 0:
                    core_q += add / (c * (1 + COST))
                    cash -= add
        # --- 주도주 스윙
        state = st.iat[i]
        if S <= 0 or state == "하락" or len(pos) >= 8:
            continue
        N, sk, tk, hold = FAST if state == "상승" else SLOW
        r_ = 0.005 if weak.iat[i] else 0.01
        kmom = F["SPY"].mom.iat[i]
        used = sum(p["q"] * p["p0"] for p in pos)
        cands = []
        for s in D["names"]:
            if not elig[s].iat[i] or any(p["s"] == s for p in pos) or last_exit.get(s, -1) >= i:
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
            if ev >= 3 and f.mom.iat[i] > kmom and cpos >= 0.75:
                cands.append((f.mom.iat[i], s, cl, a))
        for _, s, cl, a in sorted(cands, reverse=True):
            if len(pos) >= 8:
                break
            if sum(SECTOR[p["s"]] == SECTOR[s] for p in pos) >= 2:
                continue
            money = min(E * r_ / (sk * a / cl), cash, E * S - used)
            if money <= 0:
                continue
            pos.append(dict(s=s, i=i, p0=cl, q=money / (cl * (1 + COST)), stop=cl - sk * a, ext=cl, trail=tk, hold=hold))
            cash -= money
            used += money
    eq = pd.Series(eq, index=idx[i0:i1])
    return stats(eq) | {"eq": eq}


def main():
    D = prep(load())
    F, idx = D["F"], D["idx"]
    full = (DESIGN[0], TEST[1])
    print("미국 통합 시스템 (조정 분할 매수 + 평소 지수 스위칭 + 주도주 스윙) · 비용 편도 0.1% · 배당 제외 · 평가금액 낙폭\n")
    hdr = f"  {'구성':44} | {'2001~2014 연':>12} {'낙폭':>6} {'점수':>5} | {'2015~2026 연':>12} {'낙폭':>6} | {'전체 연':>7} {'낙폭':>6} {'1,000만원→':>13} | 손실해"
    rows = {}
    for L, stop, W, S, core in product((10, 15, 20), (0.25, None), (0.5, 0.8, 1.0), (0.0, 0.3, 0.6), (0.0, 0.5)):
        name = f"−{L}%부터 · {'평균가−25% 손절' if stop else '손절 없음'} · 조정 {int(W*100)}% · 지수 {'스위칭50%' if core else '없음'} · 스윙 {int(S*100)}%"
        f = run(D, *full, L, W, stop, core, S)
        a = stats(f["eq"][f["eq"].index < DESIGN[1]])
        rows[name] = dict(kw=(L, W, stop, core, S), a=a, f=f)
    top = sorted(rows, key=lambda n: -rows[n]["a"]["score"])[:10]

    def show(name):
        r = rows[name]
        if "b" not in r:
            r["b"] = run(D, *TEST, *r["kw"])
        a, b, f = r["a"], r["b"], r["f"]
        ys = yearly(f["eq"])
        print(f"  {name:44} | {a['cagr']*100:+11.1f}% {a['mdd']*100:5.1f}% {a['score']:5.2f} | {b['cagr']*100:+11.1f}% {b['mdd']*100:5.1f}% |"
              f" {f['cagr']*100:+6.1f}% {f['mdd']*100:5.1f}% {f['final']*1e7:13,.0f} | {sum(v < 0 for v in ys.values())}년", flush=True)

    m = (idx >= full[0])
    for s in ("SPY", "QQQ"):
        e = F[s].close[m] / F[s].close[m].iloc[0]
        x = stats(e); ea = e[e.index < DESIGN[1]]; a = stats(ea / ea.iloc[0]); eb = F[s].close[idx >= TEST[0]]; b = stats(eb / eb.iloc[0])
        print(f"  {s + ' 보유':44} | {a['cagr']*100:+11.1f}% {a['mdd']*100:5.1f}% {a['score']:5.2f} | {b['cagr']*100:+11.1f}% {b['mdd']*100:5.1f}% | {x['cagr']*100:+6.1f}% {x['mdd']*100:5.1f}% {x['final']*1e7:13,.0f} |")
    print("\n■ 설계(2001~2014) 점수 상위 10")
    print(hdr)
    for n in top:
        show(n)
    print("\n■ 질문별 평균 (108개 조합, 전체 2001~2026)")
    def avg(pred, label):
        g = [rows[n] for n in rows if pred(rows[n]["kw"])]
        print(f"   {label:22}: 설계 점수 {np.mean([r['a']['score'] for r in g]):.2f} · 전체 연 {np.mean([r['f']['cagr'] for r in g])*100:+.1f}% · 전체 낙폭 {np.mean([r['f']['mdd'] for r in g])*100:.1f}%")
    for L in (10, 15, 20):
        avg(lambda k, L=L: k[0] == L, f"첫 매수 −{L}%")
    for W in (0.5, 0.8, 1.0):
        avg(lambda k, W=W: k[1] == W, f"조정 비중 {int(W*100)}%")
    avg(lambda k: k[2] is not None, "평균가 −25% 손절")
    avg(lambda k: k[2] is None, "손절 없음")
    avg(lambda k: k[3] > 0, "평소 지수 스위칭 50%")
    avg(lambda k: k[3] == 0, "평소 지수 없음")
    for S in (0.0, 0.3, 0.6):
        avg(lambda k, S=S: k[4] == S, f"스윙 한도 {int(S*100)}%")
    best = top[0]
    print(f"\n  → 설계 점수로 고른 값: {best}")
    log = []
    run(D, *full, *rows[best]["kw"], log=log)
    print("  조정 매수 기록:")
    for x in log:
        print(f"    {x['buy']} ~ {x['sell']} · {x['n']}번 나눠 삼 · {x['ret']*100:+.0f}% · {x['why']}")
    q = F["QQQ"].close
    ys = yearly(rows[best]["f"]["eq"])
    print("  연도 | 고른 값 | QQQ")
    for y, v in ys.items():
        b = q[(q.index >= f"{y}-01-01") & (q.index < f"{y + 1}-01-01")]
        print(f"  {y} | {v*100:+7.1f}% | {(b.iloc[-1]/b.iloc[0]-1)*100:+6.1f}%")


if __name__ == "__main__":
    main()
