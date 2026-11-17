"""국내 시스템 '대응형': 시장 상태에 따라 매매 방식과 크기를 바꾼다 (일봉, smc.kr_tune 재사용).

규칙과 후보 값은 결과를 보기 전에 정했다. 시장 상태는 KODEX 200, 전날 종가 기준. 두 가지 판단 기준 비교: smc.kr_tune.regime(고점 대비 −10%·ADX) / 이동평균 배열(종가·50일선·200일선)
  상승장: 빠른 롱  — 20일 돌파 · 손절 ATR×2 · 추적 ATR×3 · 최대 60일, 거래당 위험 R_up (1% · 1.5% · 2%)
  박스권: 느린 롱  — 60일 돌파 · 손절 ATR×3 · 추적 ATR×5 · 최대 60일, 거래당 위험 R_box (0.5% · 1%)
          + KODEX 200 박스권 평균회귀 (볼린저 하단 매수 → 중간선 매도), 위험 R_box
  하락장: 새 롱 위험 R_down (0% · 0.25%, 느린 롱 규칙), 인버스는 KODEX 200 숏 신호 때만 0.5%
  공통: 주도 섹터 + 상대 강도 종목만, 최대 8종목, 레버리지 없음, 비용 포함, 1,000만원
고르기는 설계 구간(2012~2019) '연수익 ÷ |최대 낙폭|', 채점은 2020~2026. 예금 연 3% 와 비교.

사용:  python -m smc.kr_adaptive
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from itertools import product

import pandas as pd

import numpy as np

from . import stock_swing as ss
from .kr_portfolio import load
from .kr_tune import CAP, DESIGN, TEST, account, build_longs, filters, index_data, regime, universe
from .research import tf_features


def regime_ma() -> pd.Series:
    """이동평균 배열로 판단 (전날 종가): 종가 > 50일선 > 200일선 = 상승, 종가 < 50일선 < 200일선 = 하락, 나머지 = 박스."""
    kd, _ = index_data()
    c = kd.set_index("time").close
    e50, e200 = c.ewm(span=50, adjust=False).mean(), c.ewm(span=200, adjust=False).mean()
    st = pd.Series("박스", index=c.index)
    st[(c > e50) & (e50 > e200)] = "상승"
    st[(c < e50) & (e50 < e200)] = "하락"
    return st.shift(1).fillna("박스")


def inverse_signal(st: pd.Series) -> pd.DataFrame:
    kd, inv = index_data()
    invc = inv.set_index("time").close
    ss.COST = 0.0005
    kx = ss.trades(ss.context(kd))
    ks = kx[(kx.side < 0) & (st.reindex(kx.entry).fillna("") == "하락").to_numpy()]
    return pd.DataFrame([("KODEX 인버스", "인버스", t.entry, t.exit, (invc[t.exit] / invc[t.entry] - 1 - 0.001) / t.stop_pct, t.stop_pct, 0.005)
                         for t in ks.itertuples() if t.entry in invc.index and t.exit in invc.index],
                        columns=["sym", "sector", "entry", "exit", "r", "stop_pct", "risk"])


def box_mr(st: pd.Series) -> pd.DataFrame:
    kd, _ = index_data()
    c, o, l, a = kd.close.to_numpy(), kd.open.to_numpy(), kd.low.to_numpy(), tf_features(kd).atr.to_numpy()
    mid = kd.close.rolling(20).mean().to_numpy()
    low = mid - 2 * kd.close.rolling(20).std().to_numpy()
    rows, busy = [], -1
    for i in range(250, len(kd)):
        t = kd.time.iat[i]
        if i <= busy or st.get(t, "") != "박스" or not c[i] < low[i]:
            continue
        p0, stop, ex = c[i], c[i] - 2 * a[i], None
        for j in range(i + 1, min(len(kd), i + 11)):
            if l[j] <= stop:
                ex, ei = min(stop, o[j]), j; break
            if c[j] > mid[j]:
                ex, ei = c[j], j; break
        if ex is None:
            ei = min(len(kd) - 1, i + 10); ex = c[ei]
        rows.append(("KODEX 200", "박스", t, kd.time.iat[ei], ((ex - p0) - 0.0005 * (p0 + ex)) / (p0 - stop), (p0 - stop) / p0, 0.01))
        busy = ei
    return pd.DataFrame(rows, columns=["sym", "sector", "entry", "exit", "r", "stop_pct", "risk"])

FAST, SLOW = (20, 2.0, 3.0, 60), (60, 3.0, 5.0, 60)
R_UP, R_BOX, R_DOWN = (0.01, 0.015, 0.02), (0.005, 0.01), (0.0, 0.0025)
MAX_POS = 8
DEPOSIT = 0.03


def main():
    universe(); filters()
    with ProcessPoolExecutor(2) as pool:
        res = dict(pool.map(build_longs, [FAST, SLOW]))
    for rname, st in (("고점 대비 −10% 기준 (이전)", regime()), ("이동평균 배열 기준 (새로)", regime_ma())):
        print(f"\n==================== 시장 상태 판단: {rname} ====================")
        run(res, st)


def run(res, st):
    fast = res[FAST].assign(state=lambda x: st.reindex(x.entry).fillna("박스").to_numpy())
    slow = res[SLOW].assign(state=lambda x: st.reindex(x.entry).fillna("박스").to_numpy())
    inv, box = inverse_signal(st), box_mr(st)

    def system(ru, rb, rd):
        parts = [fast[fast.state == "상승"].assign(risk=ru), slow[slow.state == "박스"].assign(risk=rb),
                 inv.assign(risk=0.005), box.assign(risk=rb)]
        if rd > 0:
            parts.append(slow[slow.state == "하락"].assign(risk=rd))
        return pd.concat(parts, ignore_index=True)

    print("국내 대응형 시스템 · 상승장 빠르고 크게 / 박스권 느리고 작게 / 하락장 쉬고 인버스 · 1,000만원, 최대 8종목, 레버리지 없음\n")
    days = st[(st.index >= "2012-01-01")]
    print("  시장 상태 비율 (2012~): " + " · ".join(f"{k} {v*100:.0f}%" for k, v in days.value_counts(normalize=True).items()))
    rows = []
    for ru, rb, rd in product(R_UP, R_BOX, R_DOWN):
        T = system(ru, rb, rd)
        a, b = account(T, *DESIGN, MAX_POS), account(T, *TEST, MAX_POS)
        ys = {}
        for y in range(2012, 2027):
            z = account(T, f"{y}-01-01", f"{y + 1}-01-01", MAX_POS)
            ys[y] = z["final"] / CAP - 1
        rows.append(dict(ru=ru, rb=rb, rd=rd, a=a, b=b, ys=ys))
    print(f"\n  {'상승':>5} {'박스':>5} {'하락':>5} | {'2012~2019 연':>12} {'낙폭':>6} {'점수':>5} | {'2020~2026 연':>12} {'낙폭':>6} | {'예금보다 나은 해':>14} {'손실 난 해':>9}")
    for r in rows:
        a, b, ys = r["a"], r["b"], r["ys"]
        better = sum(v > DEPOSIT for v in ys.values())
        loss = sum(v < 0 for v in ys.values())
        print(f"  {r['ru']*100:4.1f}% {r['rb']*100:4.1f}% {r['rd']*100:4.2f}% | {a['cagr']*100:+11.1f}% {a['mdd']*100:5.1f}% {a['score']:5.2f} |"
              f" {b['cagr']*100:+11.1f}% {b['mdd']*100:5.1f}% | {better:6}/15년 {loss:8}년")
    best = max(rows, key=lambda r: r["a"]["score"])
    print(f"\n  → 설계 점수로 고른 값: 상승장 {best['ru']*100:.1f}% · 박스권 {best['rb']*100:.1f}% · 하락장 롱 {best['rd']*100:.2f}%")
    print("     연도별 (KODEX 200 보유 · 예금 3%):")
    k = load("069500").set_index("time").close
    for y, v in best["ys"].items():
        b = k[(k.index >= f"{y}-01-01") & (k.index < f"{y + 1}-01-01")]
        state = st[(st.index >= f"{y}-01-01") & (st.index < f"{y + 1}-01-01")].value_counts(normalize=True)
        mood = " · ".join(f"{s} {state.get(s, 0)*100:.0f}%" for s in ("상승", "박스", "하락"))
        print(f"     {y}: {v*100:+6.1f}%  | KODEX 200 {(b.iloc[-1]/b.iloc[0]-1)*100:+6.1f}% | {mood}")
    a, b = best["a"], best["b"]
    print(f"\n     2012~2019: 연 {a['cagr']*100:+.1f}% 낙폭 {a['mdd']*100:.1f}% · 1,000만원 → {a['final']:,.0f}원")
    print(f"     2020~2026: 연 {b['cagr']*100:+.1f}% 낙폭 {b['mdd']*100:.1f}% · 1,000만원 → {b['final']:,.0f}원 · 거래 {b['n']}건")
    full = account(system(best["ru"], best["rb"], best["rd"]), "2012-01-01", TEST[1], MAX_POS)
    print(f"     2012~2026 전체: 연 {full['cagr']*100:+.1f}% 낙폭 {full['mdd']*100:.1f}% · 1,000만원 → {full['final']:,.0f}원 (예금 3% 복리면 {CAP*1.03**14.9:,.0f}원)")


if __name__ == "__main__":
    main()
