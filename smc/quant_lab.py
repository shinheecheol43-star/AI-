"""개인이 할 수 있는 퀀트: 널리 알려진 전략 6가지를 원래 규칙 그대로 검증 (배당 포함 가격, 비용 편도 0.1%).

규칙은 문헌에 알려진 기본값 그대로, 결과를 보기 전에 정했다. 설계 2005~2014 / 검증 2015~2026-11 둘 다 본다 (고르지 않음).
  A 자산배분 추세 (Faber): SPY EFA EEM IEF TLT GLD VNQ 1/7 씩, 월말 종가 < 10개월 평균이면 그 몫은 SHY
  B 듀얼 모멘텀 (Antonacci): 12개월 수익률 SPY vs EFA 높은 쪽, 둘 다 SHY 보다 낮으면 IEF
  C 종목 모멘텀: 미국 대형주(그때 60일 거래대금 상위 40) 중 12-1개월 수익률 상위 10 균등 · C2 = SPY < 10개월 평균이면 SHY
  D 저변동성: 같은 후보 중 1년 일간 변동성 하위 10 균등 · D2 = 같은 추세 필터
  E 단기 과매도 (Connors RSI2): SPY 종가 > 200일 평균 & RSI(2) < 10 → 종가 매수, 종가 > 5일 평균 → 종가 매도
  F 월말·월초: 매달 마지막 4거래일 종가 매수 → 다음 달 3번째 거래일 종가 매도 (SPY)
  조합 (미리 정함): A · B · C2 1/3 씩, 월말 재조정
  비교: SPY · QQQ 보유, SPY 60 / IEF 40 월말 재조정
  현금(안 들고 있을 때) 이자 0. 세금 제외. 일별 평가로 낙폭 계산.
사용: python -m smc.quant_lab
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import requests

from .us_leaders import SECTOR

COST = 0.001
DESIGN, TEST = ("2005-01-01", "2015-01-01"), ("2015-01-01", "2026-11-23")
ETFS = ["SPY", "QQQ", "EFA", "EEM", "IEF", "TLT", "GLD", "VNQ", "SHY"]


def fetch_adj(sym):
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                     params={"period1": 0, "period2": 4102444800, "interval": "1d", "events": "div,split"},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    j = r.json()["chart"]["result"][0]
    t = pd.to_datetime(j["timestamp"], unit="s").normalize()
    q = j["indicators"]["quote"][0]
    adj = j["indicators"]["adjclose"][0]["adjclose"]
    d = pd.DataFrame({"adj": adj, "close": q["close"], "volume": q["volume"]}, index=t).dropna()
    return d[~d.index.duplicated(keep="last")]


def load():
    raw = {}
    for s in [*ETFS, *SECTOR]:
        try:
            raw[s] = fetch_adj(s)
        except Exception as e:
            print("  받기 실패", s, e)
    idx = raw["SPY"].index
    P = pd.DataFrame({s: d.adj for s, d in raw.items()}).reindex(idx)
    DV = pd.DataFrame({s: (d.close * d.volume).rolling(60).mean() for s, d in raw.items() if s in SECTOR}).reindex(idx)
    return P, DV


def month_ends(idx):
    s = pd.Series(idx, index=idx)
    return list(s.groupby(idx.to_period("M")).max())


def run_monthly(P, wfun, lo, hi):
    """wfun(t) → {종목: 비중}. 월말 종가에 맞추고 다음 달 동안 들고 감 (일별 평가)."""
    idx = P.index
    me = [t for t in month_ends(idx) if t < pd.Timestamp(hi)]
    me = [t for t in me if t >= pd.Timestamp(lo) - pd.offsets.MonthEnd(1)]
    eq, val, w_old, out = 1.0, {}, {}, []
    for k, t in enumerate(me[:-1]):
        w = wfun(t)
        turn = sum(abs(w.get(s, 0) - w_old.get(s, 0)) for s in set(w) | set(w_old))
        eq *= 1 - turn * COST
        nxt = me[k + 1]
        seg = P.loc[t:nxt, list(w)] if w else None
        days = idx[(idx > t) & (idx <= nxt)]
        if w:
            rel = seg.div(seg.iloc[0]).loc[days]
            v = sum(w[s] * rel[s].fillna(1.0) for s in w) + (1 - sum(w.values()))
            out.append(eq * v)
            eq = eq * v.iloc[-1]
            # 들고 가며 비중이 변한 것 반영
            last = {s: w[s] * rel[s].fillna(1.0).iloc[-1] / v.iloc[-1] for s in w}
            w_old = last
        else:
            out.append(pd.Series(eq, index=days))
            w_old = {}
    e = pd.concat(out)
    e = e[(e.index >= lo) & (e.index < hi)]
    return e / e.iloc[0]


def run_daily_pos(P, sym, pos: pd.Series, lo, hi):
    """pos: 날짜별 보유 여부(그날 종가 기준 결정, 다음 날부터 수익)."""
    r = P[sym].pct_change().fillna(0)
    held = pos.shift(1).fillna(False).astype(float)
    ret = held * r - pos.astype(float).diff().abs().fillna(0) * COST
    m = (P.index >= lo) & (P.index < hi)
    return (1 + ret[m]).cumprod(), held[m].mean()


def stats(e):
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    cagr = e.iloc[-1] ** (1 / yrs) - 1
    mdd = (e / e.cummax() - 1).min()
    ys = e.groupby(e.index.year).apply(lambda g: g.iloc[-1]) / e.groupby(e.index.year).apply(lambda g: g.iloc[-1]).shift(1).fillna(1.0) - 1
    return dict(cagr=cagr, mdd=mdd, score=cagr / abs(mdd), loss=int((ys < 0).sum()), worst=ys.min())


def rsi(c, n):
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def main():
    P, DV = load()
    idx = P.index
    me_all = month_ends(idx)
    mclose = P.loc[me_all]
    sma10 = mclose.rolling(10).mean()
    ret12 = mclose / mclose.shift(12) - 1
    stocks = [s for s in SECTOR if s in P]
    vol = P[stocks].pct_change().rolling(252).std()

    def liquid(t):
        dv = DV.loc[t, stocks].dropna()
        return list(dv.sort_values(ascending=False).index[:40])

    def trend_ok(t):
        return mclose.loc[t, "SPY"] > sma10.loc[t, "SPY"]

    def A(t):
        w = {}
        for s in ["SPY", "EFA", "EEM", "IEF", "TLT", "GLD", "VNQ"]:
            ok = pd.notna(sma10.loc[t, s]) and mclose.loc[t, s] > sma10.loc[t, s]
            k = s if ok else "SHY"
            w[k] = w.get(k, 0) + 1 / 7
        return w

    def B(t):
        r = ret12.loc[t]
        best = "SPY" if r["SPY"] >= r["EFA"] else "EFA"
        return {best: 1.0} if r[best] > r["SHY"] else {"IEF": 1.0}

    def C(t, filt=False):
        if filt and not trend_ok(t):
            return {"SHY": 1.0}
        i = idx.get_loc(t)
        if i < 260:
            return {}
        mom = P[stocks].iloc[i - 21] / P[stocks].iloc[i - 252] - 1
        names = [s for s in liquid(t) if pd.notna(mom.get(s))]
        top = mom[names].sort_values(ascending=False).index[:10]
        return {s: 1 / len(top) for s in top}

    def Dv(t, filt=False):
        if filt and not trend_ok(t):
            return {"SHY": 1.0}
        v = vol.loc[t, liquid(t)].dropna()
        top = v.sort_values().index[:10]
        return {s: 1 / len(top) for s in top}

    def combo(t):
        w = {}
        for f in (A, B, lambda t: C(t, True)):
            for s, x in f(t).items():
                w[s] = w.get(s, 0) + x / 3
        return w

    spy = P["SPY"]
    rs2 = rsi(spy, 2)
    s200, s5 = spy.rolling(200).mean(), spy.rolling(5).mean()
    pos, on = [], False
    for t in idx:
        if not on and spy[t] > s200[t] and rs2[t] < 10:
            on = True
        elif on and spy[t] > s5[t]:
            on = False
        pos.append(on)
    E_pos = pd.Series(pos, index=idx)
    # 월말·월초: 이번 달 마지막 4거래일 ~ 다음 달 3번째 거래일
    per = pd.Series(idx.to_period("M"), index=idx)
    rank_end = per.groupby(per).cumcount(ascending=False)          # 0 = 마지막 날
    rank_start = per.groupby(per).cumcount()                       # 0 = 첫날
    F_pos = (rank_end <= 3) | (rank_start <= 1)                    # 결정일 기준: 다음 날 수익을 받을지
    F_pos = F_pos.astype(bool)

    S = {
        "SPY 보유": lambda lo, hi: run_monthly(P, lambda t: {"SPY": 1.0}, lo, hi),
        "QQQ 보유": lambda lo, hi: run_monthly(P, lambda t: {"QQQ": 1.0}, lo, hi),
        "SPY 60 / IEF 40": lambda lo, hi: run_monthly(P, lambda t: {"SPY": 0.6, "IEF": 0.4}, lo, hi),
        "A 자산배분 추세": lambda lo, hi: run_monthly(P, A, lo, hi),
        "B 듀얼 모멘텀": lambda lo, hi: run_monthly(P, B, lo, hi),
        "C 종목 모멘텀 10": lambda lo, hi: run_monthly(P, C, lo, hi),
        "C2 종목 모멘텀 + 추세 필터": lambda lo, hi: run_monthly(P, lambda t: C(t, True), lo, hi),
        "D 저변동성 10": lambda lo, hi: run_monthly(P, Dv, lo, hi),
        "D2 저변동성 + 추세 필터": lambda lo, hi: run_monthly(P, lambda t: Dv(t, True), lo, hi),
        "E 단기 과매도 (RSI2)": lambda lo, hi: run_daily_pos(P, "SPY", E_pos, lo, hi)[0],
        "F 월말·월초 효과": lambda lo, hi: run_daily_pos(P, "SPY", F_pos, lo, hi)[0],
        "조합 A·B·C2 1/3씩": lambda lo, hi: run_monthly(P, combo, lo, hi),
    }
    full = (DESIGN[0], TEST[1])
    print("개인용 퀀트 전략 6가지 · 원래 규칙 그대로 · 배당 포함 · 비용 편도 0.1% · 일별 평가 낙폭\n")
    print(f"  {'전략':26} | {'2005~2014 연':>12} {'낙폭':>6} | {'2015~2026 연':>12} {'낙폭':>6} | {'전체 연':>7} {'낙폭':>6} {'1,000만원→':>12} | 손실해 | 최악의 해 | SPY 와 상관")
    spy_m = None
    res = {}
    for name, fn in S.items():
        a, b, f = fn(*DESIGN), fn(*TEST), fn(*full)
        x, y, z = stats(a), stats(b), stats(f)
        mret = f.resample("ME").last().pct_change().dropna()
        if spy_m is None:
            spy_m = mret
        corr = mret.corr(spy_m.reindex(mret.index))
        res[name] = (x, y, z, f)
        print(f"  {name:26} | {x['cagr']*100:+11.1f}% {x['mdd']*100:5.1f}% | {y['cagr']*100:+11.1f}% {y['mdd']*100:5.1f}% |"
              f" {z['cagr']*100:+6.1f}% {z['mdd']*100:5.1f}% {f.iloc[-1]*1e7:12,.0f} | {z['loss']:4}년 | {z['worst']*100:+7.1f}% | {corr:5.2f}", flush=True)
    _, inE = run_daily_pos(P, "SPY", E_pos, *full)
    _, inF = run_daily_pos(P, "SPY", F_pos, *full)
    print(f"\n  E 시장에 있는 날 {inE*100:.0f}% · F 시장에 있는 날 {inF*100:.0f}%")
    # 종목 모멘텀 이웃 값 (고르지 않고 안정성만 봄)
    print("\n  (안정성 점검) 종목 모멘텀 이웃 값 — 전체 연수익 / 낙폭")
    for n in (5, 10, 20):
        for lb in (126, 252):
            def Cn(t, n=n, lb=lb):
                i = idx.get_loc(t)
                if i < lb + 10:
                    return {}
                mom = P[stocks].iloc[i - 21] / P[stocks].iloc[i - lb] - 1
                names = [s for s in liquid(t) if pd.notna(mom.get(s))]
                top = mom[names].sort_values(ascending=False).index[:n]
                return {s: 1 / len(top) for s in top}
            z = stats(run_monthly(P, Cn, *full))
            print(f"     상위 {n:2} · {lb // 21}개월: 연 {z['cagr']*100:+.1f}% 낙폭 {z['mdd']*100:.0f}%")
    print("\n  연도별")
    names = ["SPY 보유", "A 자산배분 추세", "B 듀얼 모멘텀", "C2 종목 모멘텀 + 추세 필터", "E 단기 과매도 (RSI2)", "조합 A·B·C2 1/3씩"]
    print("  연도 | " + " | ".join(f"{n[:12]:>12}" for n in names))
    for yv in range(2005, 2027):
        row = []
        for n in names:
            e = res[n][3]
            g = e[e.index.year == yv]
            prev = e[e.index.year < yv]
            row.append(g.iloc[-1] / (prev.iloc[-1] if len(prev) else 1.0) - 1 if len(g) else np.nan)
        print(f"  {yv} | " + " | ".join(f"{v*100:+11.1f}%" for v in row))


if __name__ == "__main__":
    main()
