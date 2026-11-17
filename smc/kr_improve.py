"""최종 국내 시스템 개선: 주도 섹터 돌파를 더 잘 잡기 + 하락 초반 대응 (일봉).

규칙과 후보는 결과를 보기 전에 정했다. 고르기 = 2012~2019, 채점 = 2020~2026.
기준 = smc.kr_core 최종 (상승장 빠른 돌파 · 박스권 느린 돌파 · 박스권 밴드 · 하락장 인버스 신호 · 강한 상승장 KODEX 200 코어 50%,
       롱 1%, 최대 8종목, 주도 섹터(120일 강도 상위 3) + 상대 강도(종목 120일 수익률 > KODEX 200))
A. 롱 종목 고르기 후보 (기준에서 하나씩 바꿈)
   A1 강도 기간 60일   A2 강도 기간 250일   A3 주도 섹터 2개   A4 주도 섹터 4개
   A5 섹터 안 강도 1~2위만   A6 돌파 날 거래량 ≥ 20일 평균 × 1.5   A7 돌파 날 종가가 그날 범위 위쪽 25%
   A8 섹터 전체(종목 종가 평균 지수)가 50일선 위
B. 하락 초반 대응 (롱 위험 절반)
   B1 KODEX 200 종가 < 50일선   B2 종가 < 20일선   B3 20일 고점 대비 −5% 이상
설계 점수(연수익 ÷ |최대 낙폭|)가 기준보다 좋아진 A 를 모두 합치고, 가장 좋은 B 를 더해 최종

사용:  python -m smc.kr_improve
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from .kr_adaptive import FAST, SLOW, box_mr, inverse_signal, regime_ma
from .kr_core import MAX_POS, core_trades
from .kr_portfolio import POOL, load
from .kr_tune import CAP, DESIGN, TEST, account, index_data, long_trades_param, universe
from .research import tf_features


def all_trades(params):
    rows = []
    for name, (sec, d) in universe().items():
        rows += long_trades_param(name, sec, d, *params)
    return params, pd.DataFrame(rows, columns=["sym", "sector", "entry", "exit", "r", "stop_pct"])


def features(x: pd.DataFrame) -> pd.DataFrame:
    U = universe()
    kd, _ = index_data()
    k = kd.set_index("time").close
    close = pd.DataFrame({n: d.set_index("time").close for n, (s, d) in U.items()})
    sector_of = {n: s for n, (s, d) in U.items()}
    out = x.copy()
    for lb in (60, 120, 250):
        M = (close / close.shift(lb) - 1).shift(1)
        km = (k / k.shift(lb) - 1).shift(1)
        sm = pd.DataFrame({s: M[[n for n in M if sector_of[n] == s]].mean(axis=1) for s in POOL})
        rk = sm.rank(axis=1, ascending=False)
        out[f"srank{lb}"] = [rk[sector_of[n]].get(t, 99) for n, t in zip(x.sym, x.entry)]
        out[f"rs{lb}"] = np.array([M[n].get(t, np.nan) for n, t in zip(x.sym, x.entry)]) > km.reindex(x.entry).to_numpy()
        if lb == 120:
            inrank = {s: M[[n for n in M if sector_of[n] == s]].rank(axis=1, ascending=False) for s in POOL}
            out["inrank"] = [inrank[sector_of[n]][n].get(t, 99) for n, t in zip(x.sym, x.entry)]
    # 섹터 지수 (종목 종가를 첫날 100 으로 맞춘 평균) 50일선 위
    norm = close / close.bfill().iloc[0]
    sec_ix = pd.DataFrame({s: norm[[n for n in norm if sector_of[n] == s]].mean(axis=1) for s in POOL})
    sec_up = (sec_ix > sec_ix.ewm(span=50, adjust=False).mean()).shift(1)
    out["sec_up"] = [bool(sec_up[sector_of[n]].get(t, False)) for n, t in zip(x.sym, x.entry)]
    vr, cp = [], []
    for n, t in zip(x.sym, x.entry):
        d = U[n][1].set_index("time")
        i = d.index.get_loc(t)
        v20 = d.volume.iloc[max(0, i - 20):i].mean()
        vr.append(d.volume.iloc[i] / v20 if v20 > 0 else np.nan)
        rng = d.high.iloc[i] - d.low.iloc[i]
        cp.append((d.close.iloc[i] - d.low.iloc[i]) / rng if rng > 0 else 0.5)
    out["vol"], out["cpos"] = vr, cp
    return out


def main():
    universe()
    with ProcessPoolExecutor(2) as pool:
        res = dict(pool.map(all_trades, [FAST, SLOW]))
    st = regime_ma()
    kd, _ = index_data()
    k = kd.set_index("time").close
    adx = tf_features(kd).set_index(kd.time)["adx"].shift(1).reindex(st.index)
    F = {p: features(x).assign(state=st.reindex(x.entry).fillna("박스").to_numpy()) for p, x in res.items()}
    other = pd.concat([box_mr(st).assign(risk=0.01), inverse_signal(st).assign(risk=0.005),
                       core_trades((st == "상승") & (adx >= 25), 0.5)], ignore_index=True)
    warn = {"없음": pd.Series(False, index=k.index),
            "B1 지수 < 50일선": (k < k.ewm(span=50, adjust=False).mean()).shift(1).fillna(False),
            "B2 지수 < 20일선": (k < k.ewm(span=20, adjust=False).mean()).shift(1).fillna(False),
            "B3 20일 고점 −5%": (k / k.rolling(20).max() - 1 <= -0.05).shift(1).fillna(False)}
    base_mask = lambda f: (f.srank120 <= 3) & f.rs120
    A = {"기준": base_mask,
         "A1 강도 60일": lambda f: (f.srank60 <= 3) & f.rs60,
         "A2 강도 250일": lambda f: (f.srank250 <= 3) & f.rs250,
         "A3 주도 섹터 2개": lambda f: (f.srank120 <= 2) & f.rs120,
         "A4 주도 섹터 4개": lambda f: (f.srank120 <= 4) & f.rs120,
         "A5 섹터 대장 1~2위": lambda f: base_mask(f) & (f.inrank <= 2),
         "A6 거래량 1.5배": lambda f: base_mask(f) & (f.vol >= 1.5),
         "A7 강한 마감": lambda f: base_mask(f) & (f.cpos >= 0.75),
         "A8 섹터 50일선 위": lambda f: base_mask(f) & f.sec_up}

    def system(mask_fn, warn_key="없음"):
        fast, slow = F[FAST], F[SLOW]
        L = pd.concat([fast[mask_fn(fast) & (fast.state == "상승")], slow[mask_fn(slow) & (slow.state == "박스")]], ignore_index=True)
        w = warn[warn_key].reindex(L.entry).fillna(False).to_numpy().astype(bool)
        L = L.assign(risk=np.where(w, 0.005, 0.01))
        return pd.concat([L, other], ignore_index=True)

    def evaluate(T):
        a, b, f = account(T, *DESIGN, MAX_POS), account(T, *TEST, MAX_POS), account(T, "2012-01-01", TEST[1], MAX_POS)
        ys = {y: account(T, f"{y}-01-01", f"{y + 1}-01-01", MAX_POS)["final"] / CAP - 1 for y in range(2012, 2027)}
        return a, b, f, ys

    def line(name, a, b, f, ys):
        print(f"  {name:22} | {a['cagr']*100:+6.1f}% {a['mdd']*100:5.1f}% {a['score']:5.2f} | {b['cagr']*100:+6.1f}% {b['mdd']*100:5.1f}% |"
              f" {f['cagr']*100:+6.1f}% {f['mdd']*100:5.1f}% {f['final']:13,.0f} | {sum(v < 0 for v in ys.values())}년 |"
              f" 18:{ys[2018]*100:+.0f}% 22:{ys[2022]*100:+.0f}% 26:{ys[2026]*100:+.0f}%")

    hdr = f"  {'구성':22} | {'설계 연':>7} {'낙폭':>6} {'점수':>5} | {'검증 연':>7} {'낙폭':>6} | {'전체 연':>7} {'낙폭':>6} {'1,000만원 →':>13} | 손실해 | 하락한 해"
    print("국내 최종 시스템 개선 · 1,000만원 · 최대 8종목 · 레버리지 없음 · 설계 2012~2019 / 검증 2020~2026\n")
    print("■ A. 주도 섹터 돌파 잡는 방법")
    print(hdr)
    scoreA = {}
    for name, fn in A.items():
        r = evaluate(system(fn))
        scoreA[name] = r[0]["score"]
        line(name, *r)
    print("\n■ B. 하락 초반 대응 (기준 종목 고르기 위에)")
    print(hdr)
    scoreB = {}
    for wk in warn:
        r = evaluate(system(base_mask, wk))
        scoreB[wk] = r[0]["score"]
        line(wk, *r)

    good = [n for n in A if n != "기준" and scoreA[n] > scoreA["기준"]]
    # 같은 종류(강도 기간·섹터 수)는 하나만: 점수 높은 것
    groups = [["A1 강도 60일", "A2 강도 250일"], ["A3 주도 섹터 2개", "A4 주도 섹터 4개"]]
    for gset in groups:
        inset = [n for n in good if n in gset]
        if len(inset) > 1:
            keep = max(inset, key=lambda n: scoreA[n])
            good = [n for n in good if n not in inset or n == keep]
    bestB = max([w for w in warn if w != "없음"], key=lambda w: scoreB[w])
    useB = bestB if scoreB[bestB] > scoreB["없음"] else "없음"

    def combined(f):
        lb = 60 if "A1 강도 60일" in good else 250 if "A2 강도 250일" in good else 120
        top = 2 if "A3 주도 섹터 2개" in good else 4 if "A4 주도 섹터 4개" in good else 3
        m = (f[f"srank{lb}"] <= top) & f[f"rs{lb}"]
        if "A5 섹터 대장 1~2위" in good: m &= f.inrank <= 2
        if "A6 거래량 1.5배" in good: m &= f.vol >= 1.5
        if "A7 강한 마감" in good: m &= f.cpos >= 0.75
        if "A8 섹터 50일선 위" in good: m &= f.sec_up
        return m

    print(f"\n■ 최종: 설계에서 좋아진 A = {', '.join(good) if good else '없음'} · B = {useB}")
    print(hdr)
    line("기준 (지금 최종)", *evaluate(system(base_mask)))
    line("개선판", *evaluate(system(combined, useB)))
    b = k[k.index >= "2012-01-01"]
    print(f"  KODEX 200 보유 2012~: 연 {((b.iloc[-1]/b.iloc[0])**(365.25/(b.index[-1]-b.index[0]).days)-1)*100:+.1f}% 낙폭 {(b/b.cummax()-1).min()*100:.1f}%")
    _, _, _, ys = evaluate(system(combined, useB))
    print("  개선판 연도별: " + " ".join(f"{y}:{v*100:+.0f}%" for y, v in ys.items()))

    print("\n■ 2차: 다 합치면 거래가 너무 줄어서, 하나씩 효과가 컸던 것만 조합 (설계 점수 상위 A 와 B2)")
    print(hdr)
    combos = {
        "A7 강한 마감 + B2": (lambda f: base_mask(f) & (f.cpos >= 0.75), "B2 지수 < 20일선"),
        "A7 + A4(섹터 4개) + B2": (lambda f: (f.srank120 <= 4) & f.rs120 & (f.cpos >= 0.75), "B2 지수 < 20일선"),
        "A7 + A3(섹터 2개) + B2": (lambda f: (f.srank120 <= 2) & f.rs120 & (f.cpos >= 0.75), "B2 지수 < 20일선"),
        "A7 + A5(대장) + B2": (lambda f: base_mask(f) & (f.cpos >= 0.75) & (f.inrank <= 2), "B2 지수 < 20일선"),
        "A4(섹터 4개) + B2": (lambda f: (f.srank120 <= 4) & f.rs120, "B2 지수 < 20일선"),
    }
    best = None
    for name, (fn, wk) in combos.items():
        r = evaluate(system(fn, wk))
        line(name, *r)
        if best is None or r[0]["score"] > best[1][0]["score"]:
            best = (name, r)
    name, (a, b, f, ys) = best
    print(f"\n  → 설계 점수로 고른 조합: {name}")
    print("    연도별: " + " ".join(f"{y}:{v*100:+.0f}%" for y, v in ys.items()))


if __name__ == "__main__":
    main()
