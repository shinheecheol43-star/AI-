"""대응형 + 코어 보유: 강한 상승장이면 KODEX 200 을 계좌 일정 비중 들고 가고, 나머지로 대응형 매매 (일봉).

규칙과 후보 값은 결과를 보기 전에 정했다.
  대응형 매매: smc.kr_adaptive 이동평균 배열 기준, 상승장 1% · 박스권 1% · 하락장 롱 없음, 최대 8종목
  코어: 조건이 켜진 다음 날 종가에 KODEX 200 을 계좌 × 비중만큼 매수, 조건이 꺼진 다음 날 종가에 매도 (비용 편도 0.05%)
    조건 '상승장'      : 종가 > 50일선 > 200일선 (전날 종가)
    조건 '강한 상승장' : 위 + ADX(14) ≥ 25
    비중: 30% · 50% · 70%
  레버리지 없음: 코어와 스윙을 합친 투자액 ≤ 계좌 (코어가 먼저 자리를 잡고 남은 돈으로 스윙)

사용:  python -m smc.kr_core
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor

import pandas as pd

from .kr_adaptive import FAST, SLOW, box_mr, inverse_signal, regime_ma
from .kr_portfolio import load
from .kr_tune import CAP, DESIGN, TEST, account, build_longs, filters, index_data, universe
from .research import tf_features

MAX_POS = 8


def core_trades(cond: pd.Series, weight: float) -> pd.DataFrame:
    kd, _ = index_data()
    c = kd.set_index("time").close
    rows, t0 = [], None
    for t, on in cond.items():
        if t not in c.index:
            continue
        if t0 is None and on:
            t0 = t
        elif t0 is not None and not on:
            ret = c[t] / c[t0] - 1 - 0.001
            rows.append(("KODEX 200 코어", "코어", t0, t, ret / 0.10, 0.10, 0.10 * weight))
            t0 = None
    if t0 is not None:
        t = c.index[-1]
        rows.append(("KODEX 200 코어", "코어", t0, t, (c[t] / c[t0] - 1 - 0.001) / 0.10, 0.10, 0.10 * weight))
    return pd.DataFrame(rows, columns=["sym", "sector", "entry", "exit", "r", "stop_pct", "risk"])


def main():
    universe(); filters()
    with ProcessPoolExecutor(2) as pool:
        res = dict(pool.map(build_longs, [FAST, SLOW]))
    st = regime_ma()
    fast = res[FAST].assign(state=st.reindex(res[FAST].entry).fillna("박스").to_numpy())
    slow = res[SLOW].assign(state=st.reindex(res[SLOW].entry).fillna("박스").to_numpy())
    inv, box = inverse_signal(st), box_mr(st)
    base = pd.concat([fast[fast.state == "상승"].assign(risk=0.01), slow[slow.state == "박스"].assign(risk=0.01),
                      inv.assign(risk=0.005), box.assign(risk=0.01)], ignore_index=True)
    kd, _ = index_data()
    adx = tf_features(kd).set_index(kd.time)["adx"].shift(1)
    bull = st == "상승"
    conds = {"상승장": bull, "강한 상승장 (ADX≥25)": bull & (adx.reindex(bull.index) >= 25)}
    k = load("069500").set_index("time").close

    print("대응형 + KODEX 200 코어 보유 · 1,000만원 · 레버리지 없음 (코어 + 스윙 ≤ 계좌)\n")
    rows = [("대응형만 (코어 없음)", base)]
    for cname, cond in conds.items():
        on = cond[cond.index >= "2012-01-01"].mean()
        print(f"  코어 조건 '{cname}': 2012년 이후 켜진 날 {on*100:.0f}%")
        for w in (0.3, 0.5, 0.7):
            rows.append((f"{cname} · 코어 {int(w*100)}%", pd.concat([core_trades(cond, w), base], ignore_index=True)))
    print(f"\n  {'구성':28} | {'2012~2019 연':>12} {'낙폭':>6} | {'2020~2026 연':>12} {'낙폭':>6} | {'2012~2026 연':>12} {'낙폭':>6} {'1,000만원 →':>14} | 손실 난 해")
    out = {}
    for name, T in rows:
        a, b, f = account(T, *DESIGN, MAX_POS), account(T, *TEST, MAX_POS), account(T, "2012-01-01", TEST[1], MAX_POS)
        ys = {y: account(T, f"{y}-01-01", f"{y + 1}-01-01", MAX_POS)["final"] / CAP - 1 for y in range(2012, 2027)}
        out[name] = ys
        print(f"  {name:28} | {a['cagr']*100:+11.1f}% {a['mdd']*100:5.1f}% | {b['cagr']*100:+11.1f}% {b['mdd']*100:5.1f}% |"
              f" {f['cagr']*100:+11.1f}% {f['mdd']*100:5.1f}% {f['final']:14,.0f} | {sum(v < 0 for v in ys.values())}년")
    bh = {y: (lambda b: b.iloc[-1] / b.iloc[0] - 1)(k[(k.index >= f"{y}-01-01") & (k.index < f"{y + 1}-01-01")]) for y in range(2012, 2027)}
    b = k[k.index >= "2012-01-01"]
    print(f"  {'KODEX 200 보유':28} | {'':>19} | {'':>19} | {((b.iloc[-1]/b.iloc[0])**(365.25/(b.index[-1]-b.index[0]).days)-1)*100:+11.1f}%"
          f" {(b/b.cummax()-1).min()*100:5.1f}% {CAP*b.iloc[-1]/b.iloc[0]:14,.0f} | {sum(v < 0 for v in bh.values())}년")
    print("\n■ 연도별")
    names = ["대응형만 (코어 없음)", "상승장 · 코어 50%", "강한 상승장 (ADX≥25) · 코어 50%"]
    print(f"  {'연도':4} | " + " | ".join(f"{n[:20]:>20}" for n in names) + f" | {'KODEX 200':>9}")
    for y in range(2012, 2027):
        print(f"  {y} | " + " | ".join(f"{out[n][y]*100:+19.1f}%" for n in names) + f" | {bh[y]*100:+8.1f}%")


if __name__ == "__main__":
    main()
