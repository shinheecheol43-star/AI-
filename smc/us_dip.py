"""미국: 평소엔 시가총액 상위 10종목 스윙, 조정이 오면 대표 지수(SPY·QQQ)를 크게 사서 길게 보유 (일봉, 평가금액 기준 낙폭).

규칙과 후보 값은 결과를 보기 전에 정했다.
  상위 10종목: 해마다 그해 1월 초 미국 시가총액 상위 10 (기억에 의한 근사 명단, 그해에만 새로 매수 가능). 지금 상위 종목으로 과거를 돌리는 편향을 피하려고
  스윙 (국내 균형형과 같은 틀): 시장 상태 = SPY 전날 종가 · 50/200 지수이평 배열
     상승 = 20일 돌파 · 손절 ATR×2 · 추적 ATR×3 / 박스 = 60일 돌파 · ATR×3 · ATR×5 / 하락 = 새 매수 없음 · 최대 60일
     근거 4개 중 3개 + 종목 120일 수익률 > SPY + 돌파일 종가가 캔들 위 25%, 위험 1% (SPY 20일선 아래면 0.5%), 최대 8종목
  조정 매수: 지수가 1년(250일) 고점 대비 −X% (그날 종가) → 계좌 × W 를 그날 종가에 매수, 손절 없음 (스윙보다 먼저 돈을 씀)
     지수: SPY · QQQ   X: 10 · 15 · 20 · 30%   W: 50 · 80 · 100%   매도: 고점 회복 / 1년 / 2년
     분할: −10 · −20 · −30% 에서 W/3 씩 (매도 = 고점 회복)
     다시 쓰려면 낙폭이 X/2 보다 작아진 뒤
  비용 편도 0.1%, 배당·현금 이자 제외, 레버리지 없음
고르기 = 설계 2005~2014 (2008 포함) '연수익 ÷ |최대 낙폭|', 채점 = 2015~2026-11.
사용: python -m smc.us_dip
"""
from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from .stock_swing import fetch
from .research import rsi, tf_features

TOP10 = {
    2005: "GE XOM MSFT C WMT PFE BAC JNJ AIG IBM", 2006: "XOM GE MSFT C BAC WMT PG JNJ PFE AIG",
    2007: "XOM GE MSFT C BAC PG WMT JNJ AIG T", 2008: "XOM GE MSFT T PG GOOG CVX JNJ WMT BAC",
    2009: "XOM WMT PG MSFT JNJ GE CVX T GOOG IBM", 2010: "XOM MSFT AAPL WMT GOOG BRK-B JNJ PG IBM JPM",
    2011: "XOM AAPL MSFT BRK-B GE WMT GOOG CVX IBM PG", 2012: "XOM AAPL MSFT IBM CVX GOOG WMT GE PG JNJ",
    2013: "AAPL XOM GOOG WMT MSFT GE IBM CVX BRK-B JNJ", 2014: "AAPL XOM GOOG MSFT BRK-B GE JNJ WFC WMT CVX",
    2015: "AAPL XOM MSFT BRK-B GOOG JNJ WFC GE WMT JPM", 2016: "AAPL GOOG MSFT BRK-B XOM AMZN META GE JNJ WFC",
    2017: "AAPL GOOG MSFT BRK-B XOM AMZN META JNJ JPM GE", 2018: "AAPL GOOG MSFT AMZN META BRK-B JPM JNJ XOM BAC",
    2019: "MSFT AAPL AMZN GOOG BRK-B META JNJ JPM XOM V", 2020: "AAPL MSFT GOOG AMZN META BRK-B JPM V JNJ WMT",
    2021: "AAPL MSFT AMZN GOOG META TSLA BRK-B V JPM JNJ", 2022: "AAPL MSFT GOOG AMZN TSLA META NVDA BRK-B UNH JPM",
    2023: "AAPL MSFT GOOG AMZN BRK-B NVDA TSLA XOM UNH JNJ", 2024: "AAPL MSFT GOOG AMZN NVDA META BRK-B TSLA LLY AVGO",
    2025: "AAPL NVDA MSFT GOOG AMZN META TSLA AVGO BRK-B LLY", 2026: "NVDA AAPL MSFT GOOG AMZN AVGO META TSLA BRK-B LLY",
}
TOP10 = {y: v.split() for y, v in TOP10.items()}
STOCKS = sorted({s for v in TOP10.values() for s in v})
COST = 0.001
DESIGN, TEST = ("2005-01-01", "2015-01-01"), ("2015-01-01", "2026-11-19")
FAST, SLOW = (20, 2.0, 3.0, 60), (60, 3.0, 5.0, 60)


def feats(d):
    f = tf_features(d.reset_index())
    f.index = d.index
    c = d.close
    s50, s200 = c.rolling(50).mean(), c.rolling(200).mean()
    f["score"] = (np.sign(c - s200) + np.sign(s50 - s200) + np.sign(c / c.shift(90) - 1)).shift(1)
    f["rsi"] = rsi(c)
    for n in (20, 60):
        f[f"hh{n}"] = d.high.rolling(n).max().shift(1)
    f["mom"] = (c / c.shift(120) - 1).shift(1)
    f["bars"] = np.arange(1, len(d) + 1)
    for k in ("open", "high", "low", "close"):
        f[k] = d[k]
    return f


def load():
    raw = {}
    for s in ["SPY", "QQQ", *STOCKS]:
        d = fetch(s)
        d["time"] = d.time.dt.tz_localize(None).dt.normalize()
        raw[s] = d.set_index("time")
    idx = raw["SPY"].index
    F = {s: feats(d[~d.index.duplicated()]).reindex(idx) for s, d in raw.items()}
    k = F["SPY"]
    st = pd.Series("박스", index=idx)
    st[(k.close > k.ema50) & (k.ema50 > k.ema200)] = "상승"
    st[(k.close < k.ema50) & (k.ema50 < k.ema200)] = "하락"
    return F, idx, st.shift(1).fillna("박스"), (k.close < k.ema20).shift(1).fillna(False).astype(bool)


def run(D, lo, hi, swing=True, ix="SPY", X=None, W=0.0, exit_rule="고점 회복", split=False):
    F, idx, st, weak = D
    i0, i1 = int(idx.searchsorted(pd.Timestamp(lo))), int(idx.searchsorted(pd.Timestamp(hi)))
    kc = F[ix].close
    peak = kc.rolling(250, min_periods=60).max()
    dd = (kc / peak - 1).to_numpy()
    cash, pos, dips, eq, last_exit = 1.0, [], [], [], {}
    armed = {10: True, 20: True, 30: True} if split else ({X: True} if X else {})
    n_dip = n_sw = 0
    for i in range(i0, i1):
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
        c = kc.iat[i]
        for d in list(dips):
            held = i - d["i"]
            if (exit_rule == "고점 회복" and c >= d["peak"]) or (exit_rule == "1년" and held >= 250) or (exit_rule == "2년" and held >= 500):
                cash += d["q"] * c * (1 - COST)
                dips.remove(d)
        for lv in armed:
            if not armed[lv] and dd[i] > -lv / 200 and not any(d["lv"] == lv for d in dips):
                armed[lv] = True
        val = sum(p["q"] * (F[p["s"]].close.iat[i] if np.isfinite(F[p["s"]].close.iat[i]) else p["p0"]) for p in pos) + sum(d["q"] * c for d in dips)
        E = cash + val
        eq.append(E)
        for lv in armed:
            if armed[lv] and dd[i] <= -lv / 100:
                money = min(E * (W / 3 if split else W), cash)
                if money > 0:
                    dips.append(dict(i=i, q=money / (c * (1 + COST)), peak=peak.iat[i], lv=lv))
                    cash -= money
                    n_dip += 1
                armed[lv] = False
        state = st.iat[i]
        if not swing or state == "하락" or len(pos) >= 8:
            continue
        N, sk, tk, hold = FAST if state == "상승" else SLOW
        kmom = F["SPY"].mom.iat[i]
        for s in TOP10.get(idx[i].year, []):
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
            r = 0.005 if weak.iat[i] else 0.01
            money = min(E * r / (sk * a / cl), cash)
            if money <= 0:
                continue
            pos.append(dict(s=s, i=i, p0=cl, q=money / (cl * (1 + COST)), stop=cl - sk * a, ext=cl, trail=tk, hold=hold))
            cash -= money
            n_sw += 1
    eq = pd.Series(eq, index=idx[i0:i1])
    return stats(eq) | {"eq": eq, "n_dip": n_dip, "n_sw": n_sw}


def stats(eq):
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1
    mdd = (eq / eq.cummax() - 1).min()
    return dict(cagr=cagr, mdd=mdd, score=cagr / abs(mdd) if mdd < 0 else 0, final=eq.iloc[-1] / eq.iloc[0])


def yearly(eq):
    out = {}
    for y, g in eq.groupby(eq.index.year):
        prev = eq[eq.index < f"{y}-01-01"]
        out[y] = g.iloc[-1] / (prev.iloc[-1] if len(prev) else eq.iloc[0]) - 1
    return out


def main():
    D = load()
    F, idx = D[0], D[1]
    full = (DESIGN[0], TEST[1])
    hold = lambda s: (lambda lo, hi: (lambda e: stats(e) | {"eq": e, "n_dip": 0, "n_sw": 0})(
        (F[s].close[(idx >= lo) & (idx < hi)] / F[s].close[(idx >= lo) & (idx < hi)].iloc[0])))
    cfg = [("SPY 보유", hold("SPY")), ("QQQ 보유", hold("QQQ")),
           ("상위10 스윙만", lambda lo, hi: run(D, lo, hi))]
    for ix, X, W, ex in product(("SPY", "QQQ"), (10, 15, 20, 30), (0.5, 0.8, 1.0), ("고점 회복", "1년", "2년")):
        cfg.append((f"스윙+{ix} −{X}% {int(W*100)}% {ex}", lambda lo, hi, a=(ix, X, W, ex): run(D, lo, hi, True, a[0], a[1], a[2], a[3])))
    for ix, W in product(("SPY", "QQQ"), (0.5, 0.8, 1.0)):
        cfg.append((f"스윙+{ix} 분할 {int(W*100)}% 고점회복", lambda lo, hi, a=(ix, W): run(D, lo, hi, True, a[0], None, a[1], split=True)))
    for ix in ("SPY", "QQQ"):
        cfg.append((f"(스윙 없이) {ix} −20% 100% 고점회복", lambda lo, hi, ix=ix: run(D, lo, hi, False, ix, 20, 1.0)))
    print("미국: 시가총액 상위 10 스윙 + 조정 때 지수 크게 매수 · 비용 편도 0.1% · 배당 제외 · 평가금액 기준 낙폭\n")
    print(f"  {'구성':30} | {'2005~2014 연':>12} {'낙폭':>6} {'점수':>5} | {'2015~2026 연':>12} {'낙폭':>6} | {'전체 연':>7} {'낙폭':>6} {'1,000만원→':>13} | 조정매수 | 손실해")
    rows = {}
    for name, fn in cfg:
        f, b = fn(*full), fn(*TEST)
        e = f["eq"][f["eq"].index < DESIGN[1]]
        a = stats(e)
        ys = yearly(f["eq"])
        rows[name] = (a, b, f, ys)
        print(f"  {name:30} | {a['cagr']*100:+11.1f}% {a['mdd']*100:5.1f}% {a['score']:5.2f} | {b['cagr']*100:+11.1f}% {b['mdd']*100:5.1f}% |"
              f" {f['cagr']*100:+6.1f}% {f['mdd']*100:5.1f}% {f['final']*1e7:13,.0f} | {f['n_dip']:4}번 | {sum(v < 0 for v in ys.values())}년", flush=True)
    cands = [n for n in rows if n.startswith("스윙+")]
    best = max(cands, key=lambda n: rows[n][0]["score"])
    top = sorted(cands, key=lambda n: -rows[n][0]["score"])[:5]
    print(f"\n  설계 점수 상위 5: " + " / ".join(f"{n} ({rows[n][0]['score']:.2f})" for n in top))
    print(f"  → 설계 점수로 고른 값: {best}")
    names = ["SPY 보유", "QQQ 보유", "상위10 스윙만", best]
    print("  연도 | " + " | ".join(f"{n[:22]:>22}" for n in names))
    for y in range(2005, 2027):
        print(f"  {y} | " + " | ".join(f"{rows[n][3].get(y, np.nan)*100:+21.1f}%" for n in names))


if __name__ == "__main__":
    main()
