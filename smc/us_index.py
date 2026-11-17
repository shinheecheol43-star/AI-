"""미국 대표 지수 ETF (SPY·QQQ·DIA·IWM) 에 국내 균형형 규칙을 그대로 적용 (일봉, 하루씩 시뮬레이션, 평가금액 기준 낙폭).

규칙과 후보 값은 결과를 보기 전에 정했다.
  시장 상태: SPY 전날 종가 · 50/200일 지수이평 배열 (상승 / 박스 / 하락)
  롱: 상승 = 20일 돌파 · 손절 ATR×2 · 추적 ATR×3 / 박스 = 60일 돌파 · ATR×3 · ATR×5 / 하락 = 없음. 최대 60일
      근거 4개 중 3개 이상 + 4개 중 120일 수익률 상위 2개 + 돌파일 종가가 캔들 위 25%
  박스권 SPY 볼린저 하단 평균회귀 · 하락장 SPY 숏 신호(S5·S2)만 숏 0.5% (인버스 ETF 대용)
  코어(SPY 보유) 후보: 없음 / 강한 상승(ADX≥25) 50% / 상승 50% / 상승 80%
  거래당 위험 후보: 1% / 2%
  비용 편도 0.1% (해외 수수료·환전 감안), 레버리지 없음
고르기 = 설계 2001-08~2014 '연수익 ÷ |최대 낙폭|', 채점 = 2015~2026-11. 비교: SPY·QQQ 보유, 4개 균등 보유, SPY 200일선 위에서만 보유.
사용: python -m smc.us_index
"""
from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from .stock_swing import fetch
from .research import tf_features, rsi
from .detectors import pivots

SYMS = ["SPY", "QQQ", "DIA", "IWM"]
COST = 0.001
DESIGN, TEST = ("2001-08-01", "2015-01-01"), ("2015-01-01", "2026-11-18")
FAST, SLOW = (20, 2.0, 3.0, 60), (60, 3.0, 5.0, 60)


def load():
    D = {}
    for s in SYMS:
        d = fetch(s)
        d["time"] = d.time.dt.tz_localize(None)
        D[s] = d.set_index("time")
    idx = D["SPY"].index
    return {s: d.reindex(idx) for s, d in D.items()}, idx


def prep(D, idx):
    F = {}
    for s, d in D.items():
        dd = d.dropna()
        f = tf_features(dd.reset_index())
        f.index = dd.index
        c = dd.close
        s50, s200 = c.rolling(50).mean(), c.rolling(200).mean()
        f["score"] = (np.sign(c - s200) + np.sign(s50 - s200) + np.sign(c / c.shift(90) - 1)).shift(1)
        f["rsi"] = rsi(c)
        for n in (20, 60):
            f[f"hh{n}"] = dd.high.rolling(n).max().shift(1)
        f["mom"] = (c / c.shift(120) - 1).shift(1)
        f["bars"] = np.arange(1, len(dd) + 1)
        for k in ("open", "high", "low", "close"):
            f[k] = dd[k]
        F[s] = f.reindex(idx)
    k = F["SPY"]
    c = k.close
    st = pd.Series("박스", index=idx)
    st[(c > k.ema50) & (k.ema50 > k.ema200)] = "상승"
    st[(c < k.ema50) & (k.ema50 < k.ema200)] = "하락"
    st = st.shift(1).fillna("박스")
    adx = k.adx.shift(1)
    mom = pd.DataFrame({s: F[s].mom for s in SYMS})
    rank = mom.rank(axis=1, ascending=False)
    mid = c.rolling(20).mean()
    bblo = mid - 2 * c.rolling(20).std()
    _, lows = pivots(D["SPY"].dropna().reset_index(), 5)
    sup = pd.Series(np.nan, index=idx)
    for _, pc, lvl in lows:
        if pc + 1 < len(idx):
            sup.iloc[pc + 1] = lvl
    sup = sup.ffill()
    weak = (c < k.ema20).shift(1).fillna(False).astype(bool)
    return dict(F=F, st=st, adx=adx, rank=rank, mid=mid, bblo=bblo, sup=sup, weak=weak)


def simulate(P, idx, lo, hi, risk=0.01, core="없음", cap=1.0):
    F, st = P["F"], P["st"]
    k = F["SPY"]
    i0, i1 = int(idx.searchsorted(pd.Timestamp(lo))), int(idx.searchsorted(pd.Timestamp(hi)))
    cash, pos, eq, last_exit, n_tr = cap, [], [], {}, 0
    core_on = {"없음": pd.Series(False, index=idx), "강한 상승 50%": (st == "상승") & (P["adx"] >= 25),
               "상승 50%": st == "상승", "상승 80%": st == "상승"}[core]
    core_w = 0.8 if core == "상승 80%" else 0.5

    def px(s, i):
        return F[s].close.iat[i]

    def close(p, i, price):
        nonlocal cash
        if p["side"] > 0:
            cash += p["qty"] * price * (1 - COST)
        else:                                            # 숏: 담보 돌려받고 손익 정산
            cash += p["qty"] * (2 * p["p0"] - price) - p["qty"] * price * COST
        last_exit[p["key"]] = i
        pos.remove(p)

    for i in range(i0, i1):
        for p in list(pos):                              # 장중 손절
            f = F[p["sym"]]
            o, h, l = f.open.iat[i], f.high.iat[i], f.low.iat[i]
            if p["kind"] == "core":
                continue
            if p["side"] > 0:
                if o <= p["stop"]:
                    close(p, i, o)
                elif l <= p["stop"]:
                    close(p, i, p["stop"])
            else:
                if o >= p["stop"]:
                    close(p, i, o)
                elif h >= p["stop"]:
                    close(p, i, p["stop"])
        for p in list(pos):                              # 종가 관리
            f = F[p["sym"]]
            held = i - p["i"]
            if p["kind"] == "long":
                p["ext"] = max(p["ext"], f.high.iat[i])
                p["stop"] = max(p["stop"], p["ext"] - p["trail"] * f.atr.iat[i])
                if held >= p["hold"]:
                    close(p, i, f.close.iat[i])
            elif p["kind"] == "box":
                if f.close.iat[i] > P["mid"].iat[i] or held >= 10:
                    close(p, i, f.close.iat[i])
            elif p["kind"] == "short":
                p["ext"] = min(p["ext"], f.low.iat[i])
                p["stop"] = min(p["stop"], p["ext"] + 3.0 * f.atr.iat[i])
                if held >= 60:
                    close(p, i, f.close.iat[i])
            elif p["kind"] == "core" and not core_on.iat[i]:
                close(p, i, f.close.iat[i])
        val = sum(p["qty"] * px(p["sym"], i) if p["side"] > 0 else p["qty"] * (2 * p["p0"] - px(p["sym"], i)) for p in pos)
        E = cash + val
        eq.append(E)
        state = st.iat[i]
        cand = []
        if state != "하락":
            N, sk, tk, hold = FAST if state == "상승" else SLOW
            for s in SYMS:
                f = F[s]
                if any(p["sym"] == s and p["kind"] == "long" for p in pos) or last_exit.get(s, -1) >= i:
                    continue
                c, a = f.close.iat[i], f.atr.iat[i]
                if not np.isfinite(c) or not np.isfinite(a) or f.bars.iat[i] < 300:
                    continue
                hh, hp = f[f"hh{N}"].iat[i], f[f"hh{N}"].iat[i - 1]
                if not (c > hh and f.close.iat[i - 1] <= hp):
                    continue
                ev = int(c > f.ema200.iat[i]) + int(f.score.iat[i] >= 3) + int(f.rsi.iat[i] > 60) + int((c - f.ema20.iat[i]) / a > 1)
                rng = f.high.iat[i] - f.low.iat[i]
                cpos = (c - f.low.iat[i]) / rng if rng > 0 else 0.5
                if ev >= 3 and P["rank"][s].iat[i] <= 2 and cpos >= 0.75:
                    r = risk / 2 if P["weak"].iat[i] else risk
                    cand.append(dict(kind="long", key=s, sym=s, side=1, p0=c, stop=c - sk * a, ext=c, trail=tk, hold=hold, size=E * r / (sk * a / c)))
        c, a = k.close.iat[i], k.atr.iat[i]
        if state == "박스" and c < P["bblo"].iat[i] and not any(p["kind"] == "box" for p in pos) and last_exit.get("box", -1) < i:
            cand.append(dict(kind="box", key="box", sym="SPY", side=1, p0=c, stop=c - 2 * a, size=E * risk / (2 * a / c)))
        if state == "하락":
            s5 = np.isfinite(P["sup"].iat[i]) and c < P["sup"].iat[i] and k.close.iat[i - 1] >= P["sup"].iat[i - 1]
            s2 = k.score.iat[i] <= -1 and c < k.ema200.iat[i] and k.high.iat[i] >= k.ema50.iat[i] and c < k.ema50.iat[i] and c < k.open.iat[i]
            for src, on in (("S5", s5), ("S2", s2)):
                if on and not any(p.get("key") == src for p in pos) and last_exit.get(src, -1) < i:
                    cand.append(dict(kind="short", key=src, sym="SPY", side=-1, p0=c, stop=c + 2 * a, ext=c, size=E * 0.005 / (2 * a / c)))
        if core_on.iat[i] and not any(p["kind"] == "core" for p in pos) and last_exit.get("core", -1) < i:
            cand.append(dict(kind="core", key="core", sym="SPY", side=1, p0=c, size=E * core_w))
        for s in cand:
            money = min(s.pop("size"), cash)
            if money <= 0:
                continue
            s["qty"] = money / (s["p0"] * (1 + COST))
            cash -= money
            s["i"] = i
            pos.append(s)
            n_tr += 1
    eq = pd.Series(eq, index=idx[i0:i1])
    return stats(eq) | {"n": n_tr, "eq": eq}


def stats(eq):
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    mdd = (eq / eq.cummax() - 1).min()
    return dict(cagr=cagr, mdd=mdd, score=cagr / abs(mdd), final=eq.iloc[-1] / eq.iloc[0])


def hold(D, idx, sym, lo, hi, cond=None):
    c = D[sym].close
    r = c.pct_change().fillna(0)
    if cond is not None:
        sw = cond.astype(float).diff().abs().fillna(0)
        r = r * cond.shift(1).fillna(False).astype(float) - sw * COST
    m = (idx >= lo) & (idx < hi)
    return stats((1 + r[m]).cumprod())


def main():
    D, idx = load()
    P = prep(D, idx)
    full = ("2001-08-01", TEST[1])
    yrs = range(2002, 2027)

    def yearly(fn):
        return {y: fn(f"{y}-01-01", f"{y + 1}-01-01")["final"] - 1 for y in yrs}

    print("미국 대표 지수 ETF (SPY·QQQ·DIA·IWM) · 국내 균형형 규칙 · 비용 편도 0.1% · 평가금액 기준 낙폭\n")
    print(f"  {'구성':26} | {'2001~2014 연':>12} {'낙폭':>6} {'점수':>5} | {'2015~2026 연':>12} {'낙폭':>6} | {'전체 연':>7} {'낙폭':>6} {'1,000만원→':>12} | 손실해")
    rows = {}

    def line(name, fn):
        a, b, f = fn(*DESIGN), fn(*TEST), fn(*full)
        ys = yearly(fn)
        rows[name] = (a, b, f, ys)
        print(f"  {name:26} | {a['cagr']*100:+11.1f}% {a['mdd']*100:5.1f}% {a['score']:5.2f} | {b['cagr']*100:+11.1f}% {b['mdd']*100:5.1f}% |"
              f" {f['cagr']*100:+6.1f}% {f['mdd']*100:5.1f}% {f['final']*1e7:12,.0f} | {sum(v < 0 for v in ys.values())}년")

    ew = lambda lo, hi: stats((1 + pd.DataFrame({s: D[s].close.pct_change() for s in SYMS}).fillna(0).mean(axis=1)[(idx >= lo) & (idx < hi)]).cumprod())
    print("■ 비교 (보유)")
    line("SPY 보유", lambda lo, hi: hold(D, idx, "SPY", lo, hi))
    line("QQQ 보유", lambda lo, hi: hold(D, idx, "QQQ", lo, hi))
    line("4개 균등 보유", ew)
    k = P["F"]["SPY"]
    line("SPY 200일선 위에서만 보유", lambda lo, hi: hold(D, idx, "SPY", lo, hi, k.close > k.ema200))
    print("■ 균형형 규칙 (위험 · 코어)")
    for r, core in product((0.01, 0.02), ("없음", "강한 상승 50%", "상승 50%", "상승 80%")):
        line(f"위험 {r*100:.0f}% · 코어 {core}", lambda lo, hi, r=r, core=core: simulate(P, idx, lo, hi, r, core))
    cand = [n for n in rows if n.startswith("위험")]
    best = max(cand, key=lambda n: rows[n][0]["score"])
    print(f"\n  → 설계(2001~2014) 점수로 고른 값: {best}")
    print("\n■ 연도별")
    names = ["SPY 보유", "QQQ 보유", "SPY 200일선 위에서만 보유", best]
    print("  연도 | " + " | ".join(f"{n[:16]:>16}" for n in names))
    for y in yrs:
        print(f"  {y} | " + " | ".join(f"{rows[n][3][y]*100:+15.1f}%" for n in names))
    st = P["st"][(idx >= "2001-08-01")]
    print("\n  SPY 시장 상태 비율: " + " · ".join(f"{s} {v*100:.0f}%" for s, v in st.value_counts(normalize=True).items()))


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------- 2단계: 느린 추세 보유형 (1단계 실패 원인을 본 뒤 정한 후보, 고르기는 같은 설계 구간)
def run_weights(D, idx, W: pd.DataFrame, lo, hi):
    """W: 날짜 × 종목 목표 비중 (그날 종가에 맞춤, 다음 날부터 수익). 바뀐 만큼 비용."""
    R = pd.DataFrame({s: D[s].close.pct_change() for s in SYMS}).fillna(0)
    W = W.reindex(idx).ffill().fillna(0)
    ret = (W.shift(1).fillna(0) * R).sum(axis=1) - W.diff().abs().sum(axis=1).fillna(0) * COST
    m = (idx >= lo) & (idx < hi)
    return stats((1 + ret[m]).cumprod()) | {"turn": W.diff().abs().sum(axis=1)[m].sum() / 2 / ((idx[m][-1] - idx[m][0]).days / 365.25)}


def candidates(D, idx):
    c = pd.DataFrame({s: D[s].close for s in SYMS})
    month_first = pd.Series(idx.to_period("M"), index=idx).ne(pd.Series(idx.to_period("M"), index=idx).shift(1))
    out = {}
    e50, e200 = c.ewm(span=50, adjust=False).mean(), c.ewm(span=200, adjust=False).mean()
    s200 = c.rolling(200).mean()
    gc = (e50 > e200)                                       # 골든크로스 상태 (느림)
    one = lambda s, cond: pd.DataFrame({x: (cond.astype(float) if x == s else 0.0) for x in SYMS}, index=idx)
    out["T1 SPY 골든크로스(50>200) 때 보유"] = one("SPY", gc["SPY"])
    out["T2 QQQ 골든크로스 때 보유"] = one("QQQ", gc["QQQ"])
    # T3 월 1회: SPY 가 200일선 위면 보유 (월말 종가로 판단)
    mon = (c["SPY"] > s200["SPY"]).where(month_first.shift(-1, fill_value=True)).ffill().fillna(False)
    out["T3 SPY 월1회 200일선 위 보유"] = one("SPY", mon.astype(bool))
    # T4 200일선 ±3% 띠: 3% 위로 가면 사고 3% 아래로 가면 판다
    st, on = [], False
    for v, m2 in zip(c["SPY"].to_numpy(), s200["SPY"].to_numpy()):
        if np.isfinite(m2):
            on = True if v > m2 * 1.03 else False if v < m2 * 0.97 else on
        st.append(on)
    out["T4 SPY 200일선 ±3% 띠"] = one("SPY", pd.Series(st, index=idx))
    # T5 듀얼 모멘텀: 월 1회, 4개 중 250일 수익률 1위가 플러스이고 SPY 골든크로스면 그 ETF 100%, 아니면 현금
    mom = (c / c.shift(250) - 1)
    W = pd.DataFrame(0.0, index=idx, columns=SYMS)
    cur = None
    for t in idx:
        if month_first[t] and np.isfinite(mom.loc[t].max()):
            pass
    prev = None
    rows = []
    for k_, t in enumerate(idx):
        if k_ > 0 and month_first.iat[k_]:
            m = mom.iloc[k_ - 1]
            best = m.idxmax() if m.notna().any() else None
            prev = best if best is not None and m[best] > 0 and gc["SPY"].iat[k_ - 1] else None
        rows.append(prev)
    for k_, s in enumerate(rows):
        if s:
            W.iat[k_, SYMS.index(s)] = 1.0
    out["T5 듀얼 모멘텀(월1회 1위 ETF)"] = W
    # T6 T1 의 비중을 골든크로스 100% / 아니면 SPY 가 200일선 위일 때 50%
    w6 = gc["SPY"].astype(float).where(gc["SPY"], (c["SPY"] > s200["SPY"]).astype(float) * 0.5)
    out["T6 골든크로스 100% · 200일선 위 50%"] = pd.DataFrame({x: (w6 if x == "SPY" else 0.0) for x in SYMS}, index=idx)
    return out


def main2():
    D, idx = load()
    full = ("2001-08-01", TEST[1])
    C = candidates(D, idx)
    print("\n■ 2단계: 느린 추세 보유형 (현금일 땐 이자 0 으로 계산 · 배당 제외 가격 기준 · 비용 편도 0.1%)")
    print(f"  {'구성':30} | {'2001~2014 연':>12} {'낙폭':>6} {'점수':>5} | {'2015~2026 연':>12} {'낙폭':>6} | {'전체 연':>7} {'낙폭':>6} {'1,000만원→':>12} | 손실해 | 연 매매")
    res = {}
    base = {"SPY 보유": pd.DataFrame({x: (1.0 if x == "SPY" else 0.0) for x in SYMS}, index=idx),
            "QQQ 보유": pd.DataFrame({x: (1.0 if x == "QQQ" else 0.0) for x in SYMS}, index=idx)}
    for name, W in {**base, **C}.items():
        a, b, f = (run_weights(D, idx, W, *p) for p in (DESIGN, TEST, full))
        ys = {y: run_weights(D, idx, W, f"{y}-01-01", f"{y + 1}-01-01")["final"] - 1 for y in range(2002, 2027)}
        res[name] = (a, b, f, ys)
        print(f"  {name:30} | {a['cagr']*100:+11.1f}% {a['mdd']*100:5.1f}% {a['score']:5.2f} | {b['cagr']*100:+11.1f}% {b['mdd']*100:5.1f}% |"
              f" {f['cagr']*100:+6.1f}% {f['mdd']*100:5.1f}% {f['final']*1e7:12,.0f} | {sum(v < 0 for v in ys.values()):3}년 | {f['turn']:4.1f}회")
    best = max(C, key=lambda n: res[n][0]["score"])
    print(f"\n  → 설계 점수로 고른 값: {best}")
    names = ["SPY 보유", "QQQ 보유", best]
    print("  연도 | " + " | ".join(f"{n[:18]:>18}" for n in names))
    for y in range(2002, 2027):
        print(f"  {y} | " + " | ".join(f"{res[n][3][y]*100:+17.1f}%" for n in names))
    return res, best
