"""국내: 평소엔 대형주 스윙(균형형), 조정(KODEX 200 1년 고점 대비 −X%)이 오면 KODEX 200 을 길게 보유.

규칙과 후보 값은 결과를 보기 전에 정했다. 스윙은 kr_trader 의 균형형 코드 그대로 (실매매와 같은 코드).
  조정 매수: 그날 종가 기준 1년(250일) 고점 대비 X% 이하 → 그날 종가에 KODEX 200 을 계좌 × W 만큼 (손절 없음)
     X: 10 · 20 · 30%   W: 30 · 50%
  매도: '고점 회복' = 매수 때의 1년 고점 종가 다시 넘으면 / '1년' = 250일 / '2년' = 500일
  다시 쓰려면 낙폭이 X/2 보다 작아진 뒤 (같은 하락장에서 반복 매수 방지)
  기존 코어(강한 상승장 KODEX 200 50%): 유지 / 없앰
  변형: 분할 매수 (−10 · −20 · −30% 에서 W/3 씩, 매도는 '고점 회복')
고르기 = 설계 2004~2019 '연수익 ÷ |최대 낙폭|' (2008 포함, 2009-04 이전 지수는 코스피로 근사), 채점 = 2020~2026. 평가금액 기준 낙폭, 1,000만원.
사용: python -m smc.kr_dip
"""
from __future__ import annotations

import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "kr_trader"))
import strategy as S                                      # noqa: E402
from data import load_all                                 # noqa: E402

DESIGN, TEST = ("2004-01-01", "2020-01-01"), ("2020-01-01", "2026-11-19")
CAP = 10_000_000


def spliced():
    """야후 KODEX 200 은 2009-04-17 이전이 비어 있음(2008 통째로 없음) → 그 전은 코스피(^KS11) 를 이어 붙인 근사. 인버스는 2009-09 상장이라 그 전엔 없음."""
    from smc.stock_swing import fetch
    D = load_all(refresh=False)
    kd = D[S.KODEX200]
    ks = fetch("^KS11")
    ks = ks.set_index(ks.time.dt.tz_convert("Asia/Seoul").dt.normalize().dt.tz_localize(None))[["open", "high", "low", "close", "volume"]]
    t0 = pd.Timestamp("2009-04-17")
    ratio = kd.close.loc[t0] / ks.close.loc[t0]
    early = ks[ks.index < t0].copy()
    early[["open", "high", "low", "close"]] *= ratio
    D[S.KODEX200] = pd.concat([early, kd[kd.index >= t0]])
    return D


def run(mk, lo, hi, X=None, W=0.0, exit_rule="고점 회복", core=True, split=False):
    i0, i1 = int(mk.dates.searchsorted(pd.Timestamp(lo))), int(mk.dates.searchsorted(pd.Timestamp(hi)))
    kc = mk.k.c
    peak = kc.rolling(250, min_periods=60).max()
    dd = (kc / peak - 1).to_numpy()
    cash, pos, last_exit, eq = float(CAP), [], {}, []
    dips, armed, n_dip = [], ({10: True, 20: True, 30: True} if split else {X: True} if X else {}), 0
    cost = S.cost_of
    core_save = mk.k.core_on.copy()
    if not core:
        mk.k["core_on"] = False

    def sell(p, i, px):
        nonlocal cash
        cash += p["qty"] * px * (1 - cost(p["code"]))
        last_exit[p["code"] if p["kind"] == "stock" else p["kind"] + p.get("src", "")] = i
        pos.remove(p)

    for i in range(i0, i1):
        for p in list(pos):
            px = mk.intraday_exit(p, i)
            if px is not None:
                sell(p, i, px)
        for p in list(pos):
            why = mk.close_update(p, i)
            if why:
                sell(p, i, mk.price(p["code"], i))
        c = kc.iat[i]
        for d in list(dips):                                # 조정 보유 매도
            held = i - d["i"]
            if (exit_rule == "고점 회복" and c >= d["peak"]) or (exit_rule == "1년" and held >= 250) or (exit_rule == "2년" and held >= 500):
                cash += d["qty"] * c * (1 - 0.0005)
                dips.remove(d)
        for lvl in armed:                                   # 낙폭이 기준의 절반보다 작아지면 다시 준비
            if not armed[lvl] and dd[i] > -lvl / 200 and not any(d["lvl"] == lvl for d in dips):
                armed[lvl] = True
        value = sum(p["qty"] * mk.price(p["code"], i) for p in pos) + sum(d["qty"] * c for d in dips)
        E = cash + value
        eq.append(E)
        for lvl in armed:                                   # 조정 매수 (스윙보다 먼저 돈을 씀)
            if armed[lvl] and dd[i] <= -lvl / 100:
                money = min(E * (W / 3 if split else W), cash)
                if money > 0:
                    q = money / (c * 1.0005)
                    cash -= money
                    dips.append(dict(i=i, qty=q, peak=peak.iat[i], lvl=lvl))
                    n_dip += 1
                armed[lvl] = False
        for s in S.plan_entries(mk, i, pos, last_exit, E, cash, cost):
            cash -= s["qty"] * s["price"] * (1 + cost(s["code"]))
            pos.append(s)
    mk.k["core_on"] = core_save
    eq = pd.Series(eq, index=mk.dates[i0:i1])
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / CAP) ** (1 / yrs) - 1
    mdd = (eq / eq.cummax() - 1).min()
    return dict(cagr=cagr, mdd=mdd, score=cagr / abs(mdd), final=eq.iloc[-1], eq=eq, n_dip=n_dip)


def yearly(eq):
    out = {}
    for y, g in eq.groupby(eq.index.year):
        prev = eq[eq.index < f"{y}-01-01"]
        out[y] = g.iloc[-1] / (prev.iloc[-1] if len(prev) else CAP) - 1
    return out


def main():
    mk = S.Market(spliced())
    full = (DESIGN[0], TEST[1])
    rows = []
    configs = [("균형형 지금 (코어 유지, 조정 매수 없음)", dict(core=True)), ("균형형 코어 없앰", dict(core=False))]
    for core, X, W, ex in product((True, False), (10, 20, 30), (0.3, 0.5), ("고점 회복", "1년", "2년")):
        configs.append((f"{'코어+' if core else ''}조정 −{X}% · {int(W*100)}% · {ex}", dict(core=core, X=X, W=W, exit_rule=ex)))
    for core, W in product((True, False), (0.3, 0.5)):
        configs.append((f"{'코어+' if core else ''}분할 −10/−20/−30 · {int(W*100)}%", dict(core=core, W=W, split=True)))
    print("국내 균형형 스윙 + 조정 때 KODEX 200 장기 보유 · 1,000만원 · 평가금액 기준 낙폭 · 설계 2004~2019 / 검증 2020~2026\n")
    hdr = f"  {'구성':34} | {'2004~2019 연':>12} {'낙폭':>6} {'점수':>5} | {'2020~2026 연':>12} {'낙폭':>6} | {'전체 연':>7} {'낙폭':>6} {'1,000만원→':>12} | 매수 | 손실해"
    print(hdr)
    for name, kw in configs:
        f, b = run(mk, *full, **kw), run(mk, *TEST, **kw)
        e = f["eq"][f["eq"].index < DESIGN[1]]
        yrs = (e.index[-1] - e.index[0]).days / 365.25
        ca, md = (e.iloc[-1] / CAP) ** (1 / yrs) - 1, (e / e.cummax() - 1).min()
        a = dict(cagr=ca, mdd=md, score=ca / abs(md))
        ys = yearly(f["eq"])
        rows.append((name, kw, a, b, f, ys))
        print(f"  {name:34} | {a['cagr']*100:+11.1f}% {a['mdd']*100:5.1f}% {a['score']:5.2f} | {b['cagr']*100:+11.1f}% {b['mdd']*100:5.1f}% |"
              f" {f['cagr']*100:+6.1f}% {f['mdd']*100:5.1f}% {f['final']:12,.0f} | {f['n_dip']:3}번 | {sum(v < 0 for v in ys.values())}년", flush=True)
    best = max(rows[2:], key=lambda r: r[2]["score"])
    base = rows[0]
    print(f"\n  → 설계 점수로 고른 값: {best[0]}")
    k = mk.k.c
    print("  연도 | 균형형 지금 | 고른 값 | KODEX 200")
    for y in sorted(best[5]):
        b = k[(k.index >= f"{y}-01-01") & (k.index < f"{y + 1}-01-01")]
        print(f"  {y} | {base[5][y]*100:+9.1f}% | {best[5][y]*100:+7.1f}% | {(b.iloc[-1]/b.iloc[0]-1)*100:+8.1f}%")


if __name__ == "__main__":
    main()
