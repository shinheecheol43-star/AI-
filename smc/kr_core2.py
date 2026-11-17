"""최종 국내 시스템 + 강한 하락장 인버스 코어 (일봉).

규칙과 후보 값은 결과를 보기 전에 정했다.
  기본 = smc.kr_core '강한 상승장 · 코어 50%' (KODEX 200 코어 + 대응형 매매)
  인버스 코어: '강한 하락장' (종가 < 50일선 < 200일선 + ADX(14) ≥ 25, 전날 종가) 이 켜진 다음 날 종가에
               KODEX 인버스를 계좌 × 비중 매수, 꺼진 다음 날 종가에 매도. 비중 20% · 30% · 50%
  비교: 느슨한 하락장 (종가 < 50일선 < 200일선, ADX 조건 없음) 30%

사용:  python -m smc.kr_core2
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from .kr_adaptive import FAST, SLOW, box_mr, inverse_signal, regime_ma
from .kr_core import MAX_POS, core_trades
from .kr_portfolio import load
from .kr_tune import CAP, DESIGN, TEST, account, build_longs, filters, index_data, universe
from .research import tf_features


def inv_core(cond: pd.Series, weight: float) -> pd.DataFrame:
    _, inv = index_data()
    c = inv.set_index("time").close
    rows, t0 = [], None
    for t, on in cond.items():
        if t not in c.index:
            continue
        if t0 is None and on:
            t0 = t
        elif t0 is not None and not on:
            rows.append(("KODEX 인버스 코어", "인버스코어", t0, t, (c[t] / c[t0] - 1 - 0.001) / 0.10, 0.10, 0.10 * weight))
            t0 = None
    if t0 is not None:
        t = c.index[-1]
        rows.append(("KODEX 인버스 코어", "인버스코어", t0, t, (c[t] / c[t0] - 1 - 0.001) / 0.10, 0.10, 0.10 * weight))
    return pd.DataFrame(rows, columns=["sym", "sector", "entry", "exit", "r", "stop_pct", "risk"])


def main():
    universe(); filters()
    with ProcessPoolExecutor(2) as pool:
        res = dict(pool.map(build_longs, [FAST, SLOW]))
    st = regime_ma()
    fast = res[FAST].assign(state=st.reindex(res[FAST].entry).fillna("박스").to_numpy())
    slow = res[SLOW].assign(state=st.reindex(res[SLOW].entry).fillna("박스").to_numpy())
    kd, _ = index_data()
    adx = tf_features(kd).set_index(kd.time)["adx"].shift(1).reindex(st.index)
    strong_bull = (st == "상승") & (adx >= 25)
    strong_bear = (st == "하락") & (adx >= 25)
    base = pd.concat([fast[fast.state == "상승"].assign(risk=0.01), slow[slow.state == "박스"].assign(risk=0.01),
                      inverse_signal(st).assign(risk=0.005), box_mr(st).assign(risk=0.01), core_trades(strong_bull, 0.5)],
                     ignore_index=True)
    print("최종 국내 시스템 + 강한 하락장 인버스 코어 · 1,000만원 · 레버리지 없음\n")
    print(f"  강한 하락장 켜진 날 (2012~): {strong_bear[strong_bear.index >= '2012-01-01'].mean()*100:.0f}% · 느슨한 하락장: {(st == '하락')[st.index >= '2012-01-01'].mean()*100:.0f}%")
    ic = inv_core(strong_bear, 1.0)
    ic["ret"] = ic.r * ic.stop_pct
    print(f"  강한 하락장 인버스 보유 단독: {len(ic)}번 · 이긴 비율 {(ic.ret > 0).mean()*100:.0f}% · 평균 보유 수익 {ic.ret.mean()*100:+.1f}%"
          f" · 평균 보유 {((ic.exit - ic.entry).dt.days).mean():.0f}일")
    rows = [("기본 (인버스 코어 없음)", base)]
    for w in (0.2, 0.3, 0.5):
        rows.append((f"+ 강한 하락장 인버스 {int(w*100)}%", pd.concat([base, inv_core(strong_bear, w)], ignore_index=True)))
    rows.append(("+ 느슨한 하락장 인버스 30%", pd.concat([base, inv_core(st == "하락", 0.3)], ignore_index=True)))
    k = load("069500").set_index("time").close
    print(f"\n  {'구성':26} | {'2012~2019 연':>12} {'낙폭':>6} | {'2020~2026 연':>12} {'낙폭':>6} | {'2012~2026 연':>12} {'낙폭':>6} {'1,000만원 →':>14} | 손실 난 해")
    out = {}
    for name, T in rows:
        a, b, f = account(T, *DESIGN, MAX_POS), account(T, *TEST, MAX_POS), account(T, "2012-01-01", TEST[1], MAX_POS)
        ys = {y: account(T, f"{y}-01-01", f"{y + 1}-01-01", MAX_POS)["final"] / CAP - 1 for y in range(2012, 2027)}
        out[name] = ys
        print(f"  {name:26} | {a['cagr']*100:+11.1f}% {a['mdd']*100:5.1f}% | {b['cagr']*100:+11.1f}% {b['mdd']*100:5.1f}% |"
              f" {f['cagr']*100:+11.1f}% {f['mdd']*100:5.1f}% {f['final']:14,.0f} | {sum(v < 0 for v in ys.values())}년")
    print("\n■ 연도별 (지수가 빠진 해 위주로 보세요)")
    names = [r[0] for r in rows[:3]]
    print(f"  {'연도':4} | " + " | ".join(f"{n[:18]:>18}" for n in names) + f" | {'KODEX 200':>9}")
    for y in range(2012, 2027):
        b = k[(k.index >= f"{y}-01-01") & (k.index < f"{y + 1}-01-01")]
        print(f"  {y} | " + " | ".join(f"{out[n][y]*100:+17.1f}%" for n in names) + f" | {(b.iloc[-1]/b.iloc[0]-1)*100:+8.1f}%")


if __name__ == "__main__":
    main()
