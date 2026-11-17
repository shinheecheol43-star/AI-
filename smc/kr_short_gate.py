"""국내 시장: 시장이 조정에 들어갔을 때만 숏 시스템을 켜면 어떤가 (일봉, 12종목, smc.kr_swing 과 같은 규칙).

규칙은 결과를 보기 전에 정했다.
  숏 스위치 (KODEX 200, 전날 종가 기준)
    켜짐: 최근 250거래일 최고가 대비 하락률 ≥ 10% (비교: 15% · 20%)
    꺼짐: 하락률이 5% 이내로 회복
  추가 비교: 종목 자체도 250일 고가 대비 10% 이상 하락했을 때만
  숏 신호는 smc.stock_swing 의 S5(스윙 저점 이탈)·S2(하락장 50일선 반등 실패) 그대로, 진행 중 거래는 현재가로 평가
  실제로는 개별 종목 공매도가 어려우므로 '인버스 ETF·대주로 같은 방향을 잡는다'고 가정한 계산
계좌: 1,000만원, 롱 거래당 1% · 숏 거래당 0.5% (숏은 절반), 레버리지 없음 (롱·숏 손익을 각각 계산해 더한 근사). 설계 ~2019 / 검증 2020~

사용:  python -m smc.kr_short_gate
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import stock_swing as ss
from .kr_swing import CAP, UNIVERSE

GATES = (0.10, 0.15, 0.20)
OFF = 0.05


def gate(close: pd.Series, on: float) -> pd.Series:
    dd = close / close.rolling(250, min_periods=60).max() - 1
    state, out = False, []
    for v in dd.to_numpy():
        if not state and v <= -on:
            state = True
        elif state and v > -OFF:
            state = False
        out.append(state)
    return pd.Series(out, index=close.index).shift(1).fillna(False).astype(bool)   # 전날 종가로 판단


def main():
    k = ss.fetch("069500.KS")
    k = k[k.close > 0].set_index("time").close
    rows, own = [], {}
    for sym, (name, cost) in UNIVERSE.items():
        d = ss.fetch(sym)
        d = d[d.close > 0].reset_index(drop=True)
        ss.COST = cost
        x = ss.trades(ss.context(d)).assign(sym=name)
        c = d.set_index("time").close
        own[name] = ((c / c.rolling(250, min_periods=60).max() - 1).shift(1) <= -0.10)
        rows.append(x)
    X = pd.concat(rows, ignore_index=True)
    X["own_dd"] = [bool(own[s].get(t, False)) for s, t in zip(X.sym, X.entry)]
    L, S = X[X.side > 0], X[X.side < 0]
    print("국내 시장 · 조정장 스위치가 켜졌을 때만 숏 · 12종목 · 설계 ~2019 / 검증 2020~ · R 은 비용 뺀 값\n")
    print(f"  {'숏 조건':30} | {'거래':>5} {'승률':>4} {'평균R':>6} | {'~2019':>13} | {'2020~':>13} | {'2026 고점 뒤':>13} | 스위치 켜진 날 비율")
    variants = [("항상 (지금)", pd.Series(True, index=k.index))] + [(f"지수 −{int(g*100)}% 조정 때만", gate(k, g)) for g in GATES]
    peak = k[k.index >= "2026-01-01"].idxmax()
    res = {}
    for name, g in variants:
        on = g.reindex(S.entry).fillna(False).to_numpy().astype(bool)
        for lab, extra in (("", np.ones(len(S), bool)), (" + 종목도 −10%", S.own_dd.to_numpy())):
            z = S[on & extra]
            a, b, p = z[z.entry < ss.SPLIT], z[z.entry >= ss.SPLIT], z[z.entry >= peak]
            res[name + lab] = z
            print(f"  {name + lab:30} | {len(z):5} {(z.r > 0).mean()*100:3.0f}% {z.r.mean():+6.2f} | {a.r.mean():+6.2f} ({len(a):4}) |"
                  f" {b.r.mean():+6.2f} ({len(b):4}) | {p.r.sum():+6.1f}R ({len(p):3}) | {g.mean()*100:4.0f}%")
            if name.startswith("항상"):
                break
    z = res["지수 −10% 조정 때만"]
    print("\n  지수 −10% 스위치 숏, 연도별 평균 R (건수): " +
          " ".join(f"{y}:{gg.r.mean():+.2f}({len(gg)})" for y, gg in z.groupby(z.entry.dt.year)))
    g10 = gate(k, 0.10)
    on_days = g10[g10.index >= "2026-01-01"]
    first = on_days[on_days].index.min()
    print(f"  2026년 스위치 켜진 날: {first.date() if pd.notna(first) else '없음'} (지수 고점 {peak.date()})")

    print("\n■ 1,000만원 계좌 연도별: 롱만 vs 롱 + 조정장 숏 (롱 1%, 숏 0.5%, 레버리지 없음)")
    print(f"  {'연도':4} | {'롱만':>8} | {'롱+숏(−10%)':>11} | {'롱+숏(−15%)':>11} | {'KODEX 200':>9}")
    for y in range(2020, 2027):
        out = []
        for shorts in (None, res["지수 −10% 조정 때만"], res["지수 −15% 조정 때만"]):
            df = L if shorts is None else pd.concat([L, shorts])
            zz = df[(df.entry >= f"{y}-01-01") & (df.entry < f"{y + 1}-01-01")]
            if not len(zz):
                out.append(0.0); continue
            bal = CAP
            for side, risk in ((1, 0.01), (-1, 0.005)):
                part = zz[zz.side == side]
                if len(part):
                    cv = ss.equity(part, risk=risk, start=CAP)
                    bal += cv.iloc[-1] - CAP
            out.append(bal / CAP - 1)
        b = k[(k.index >= f"{y}-01-01") & (k.index < f"{y + 1}-01-01")]
        print(f"  {y} | {out[0]*100:+7.1f}% | {out[1]*100:+10.1f}% | {out[2]*100:+10.1f}% | {(b.iloc[-1]/b.iloc[0]-1)*100:+8.1f}%")


if __name__ == "__main__":
    main()
