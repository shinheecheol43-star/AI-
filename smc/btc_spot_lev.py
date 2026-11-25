"""비트코인: 현물은 큰 하락에서 나눠 사서 사이클을 들고 가고, 레버리지는 상승 배열 돌파 때만 손절을 걸고 짧게 (일봉).

규칙과 후보 값은 결과를 보기 전에 정했다.
  현물: 사상 최고가 대비 −a/−b/−c% 에 현물 몫의 1/3 씩 (지정가, 저가가 닿으면 그 가격)
        후보 (−50,−65,−80) · (−60,−70,−80) · (−75,−80,−85)
        매도: '안 팖' / '사이클 종료' = 매수 때 최고가를 넘은 뒤 그 뒤 고점 대비 −30% 종가면 전부 매도 → 다시 대기
        현물 몫: 계좌 50% · 70% (나머지 현금 = 다음 분할·레버리지 담보)
  레버리지: 전날 종가 > 50일선 > 200일선 일 때 종가 20일 고점 첫 돌파 → 종가 선물 롱
        손절 ATR×2 · 추적 ATR×3 · 최대 60일, 거래당 위험 = 계좌 1% · 2% (후보 '없음' 포함), 담보 = 명목 / 3 (격리, 청산가 확인)
  비용: 현물 편도 0.1% · 선물 편도 0.05% · 펀딩비 하루 0.03% (명목 기준). 현금 이자 0. 2014년 이전 최고가 1,147 달러 반영.
고르기 = 2015~2020 '연수익 ÷ |최대 낙폭|', 채점 = 2021~2026-11. 시작 2,000만원.
사용: python -m smc.btc_spot_lev
"""
from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from .research import tf_features
from .stock_swing import fetch

DESIGN, TEST = ("2015-01-01", "2021-01-01"), ("2021-01-01", "2026-11-26")
SPOT_COST, FUT_COST, FUND, MMR = 0.001, 0.0005, 0.0003, 0.005
CAP = 2000  # 만원


def load():
    d = fetch("BTC-USD")
    d = d.set_index(d.time.dt.tz_localize(None))
    f = tf_features(d.reset_index(drop=True))
    f.index = d.index
    d["atr"], d["e50"], d["e200"] = f.atr, f.ema50, f.ema200
    st = ((d.close > d.e50) & (d.e50 > d.e200)).shift(1).fillna(False).astype(bool)
    d["up"] = st
    d["hh20"] = d.high.rolling(20).max().shift(1)
    d["ath"] = np.maximum(d.high.cummax().shift(1).fillna(1147), 1147)
    return d


def run(d, lo, hi, levels=(0.75, 0.80, 0.85), spot_exit="안 팖", spot_w=0.7, risk=0.0, log=None):
    s = d[(d.index >= lo) & (d.index < hi)]
    o, h, l, c, atr, up, hh, ath = (s[k].to_numpy() for k in ("open", "high", "low", "close", "atr", "up", "hh20", "ath"))
    cash, coin, eq = 1.0, 0.0, []
    budget = spot_w                                   # 이번 사이클 현물 예산 (계좌 비율 → 첫날 금액 기준 갱신)
    filled = [False] * 3
    cyc_ath, beyond, peak = ath[0], False, 0.0
    fut, liq, trades, funding = None, 0, [], 0.0
    budget_amt = spot_w * 1.0
    for i in range(len(s)):
        # --- 레버리지 포지션 관리
        if fut:
            ex = None
            if l[i] <= fut["liq"]:
                ex, why = None, "청산"
                cash += 0.0                                # 담보 전부 잃음
                liq += 1
                trades.append(-fut["margin"])
                fut = None
            else:
                if o[i] <= fut["stop"]:
                    ex = o[i]
                elif l[i] <= fut["stop"]:
                    ex = fut["stop"]
                else:
                    fut["ext"] = max(fut["ext"], h[i])
                    fut["stop"] = max(fut["stop"], fut["ext"] - 3 * atr[i])
                    if i - fut["i"] >= 60:
                        ex = c[i]
                fee = fut["notional"] * FUND
                fut and funding.__class__
                if fut:
                    fut["paid"] += fee
                if ex is not None:
                    pnl = fut["notional"] * (ex / fut["p0"] - 1) - fut["notional"] * FUT_COST * 2 - fut["paid"]
                    cash += fut["margin"] + pnl
                    trades.append(pnl)
                    funding += fut["paid"]
                    fut = None
        # --- 현물 분할 매수 (사이클 최고가 기준)
        if not any(filled):
            cyc_ath = ath[i]
        for k, lv in enumerate(levels):
            px = cyc_ath * (1 - lv)
            if not filled[k] and l[i] <= px:
                if k == 0 or not any(filled):
                    budget_amt = spot_w * (cash + coin * c[i] + (fut["margin"] if fut else 0))
                money = min(budget_amt / 3, cash)
                if money > 0:
                    coin += money * (1 - SPOT_COST) / px
                    cash -= money
                filled[k] = True
        # --- 현물 사이클 종료 매도
        if spot_exit == "사이클 종료" and coin > 0:
            if h[i] > cyc_ath:
                beyond = True
            if beyond:
                peak = max(peak, c[i])
                if c[i] <= peak * 0.7:
                    cash += coin * c[i] * (1 - SPOT_COST)
                    if log is not None:
                        log.append(("현물 매도", s.index[i].date(), round(c[i])))
                    coin, filled, beyond, peak = 0.0, [False] * 3, False, 0.0
        # --- 평가
        unreal = fut["margin"] + fut["notional"] * (c[i] / fut["p0"] - 1) - fut["paid"] if fut else 0.0
        E = cash + coin * c[i] + unreal
        eq.append(E)
        # --- 레버리지 진입
        if risk > 0 and fut is None and i > 0 and up[i] and np.isfinite(hh[i]) and c[i] > hh[i] and c[i - 1] <= hh[i - 1]:
            stop = c[i] - 2 * atr[i]
            notional = E * risk / ((c[i] - stop) / c[i])
            margin = notional / 3
            if margin <= cash and margin > 0:
                cash -= margin
                fut = dict(i=i, p0=c[i], notional=notional, margin=margin, stop=stop, ext=c[i], paid=0.0,
                           liq=c[i] * (1 - 1 / 3 + MMR))
    eq = pd.Series(eq, index=s.index)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    mdd = (eq / eq.cummax() - 1).min()
    t = np.array(trades)
    return dict(cagr=cagr, mdd=mdd, score=cagr / abs(mdd), final=eq.iloc[-1], eq=eq, liq=liq, n=len(t),
                win=(t > 0).mean() if len(t) else np.nan, fut_pnl=t.sum() if len(t) else 0.0, funding=funding)


def main():
    d = load()
    full = (DESIGN[0], TEST[1])
    rows = {}
    print("비트코인 현물 분할 보유 + 레버리지 돌파 매매 · 2,000만원 · 비용·펀딩 포함 · 일별 평가 낙폭\n")
    hdr = (f"  {'구성':44} | {'2015~2020 연':>12} {'낙폭':>6} {'점수':>5} | {'2021~2026 연':>12} {'낙폭':>6} | {'전체 최종':>10} {'낙폭':>6} |"
           f" 레버리지 {'건수':>4} {'승률':>5} {'손익(만원)':>10} 청산")

    def line(name, kw):
        f, b = run(d, *full, **kw), run(d, *TEST, **kw)
        e = f["eq"][f["eq"].index < DESIGN[1]]
        yrs = (e.index[-1] - e.index[0]).days / 365.25
        a = dict(cagr=e.iloc[-1] ** (1 / yrs) - 1, mdd=(e / e.cummax() - 1).min())
        a["score"] = a["cagr"] / abs(a["mdd"])
        rows[name] = (kw, a, b, f)
        print(f"  {name:44} | {a['cagr']*100:+11.1f}% {a['mdd']*100:5.1f}% {a['score']:5.2f} | {b['cagr']*100:+11.1f}% {b['mdd']*100:5.1f}% |"
              f" {f['final']*CAP:10,.0f} {f['mdd']*100:5.1f}% | {f['n']:4} {f['win']*100 if f['n'] else 0:4.0f}% {f['fut_pnl']*CAP:10,.0f} {f['liq']:3}", flush=True)

    print(hdr)
    line("현물 전부 첫날 매수 후 보유", dict(levels=(0.0, 0.0, 0.0), spot_w=1.0))
    line("레버리지 돌파만 (위험 2%, 현물 없음)", dict(levels=(2, 2, 2), spot_w=0.0, risk=0.02))
    for lv, ex, w, r in product(((0.50, 0.65, 0.80), (0.60, 0.70, 0.80), (0.75, 0.80, 0.85)), ("안 팖", "사이클 종료"), (0.5, 0.7), (0.0, 0.01, 0.02)):
        name = f"현물 −{int(lv[0]*100)}/−{int(lv[1]*100)}/−{int(lv[2]*100)} {int(w*100)}% {ex} · 레버리지 {'없음' if r == 0 else f'{r*100:.0f}%'}"
        line(name, dict(levels=lv, spot_exit=ex, spot_w=w, risk=r))
    cands = [n for n in rows if n.startswith("현물 −")]
    best = max(cands, key=lambda n: rows[n][1]["score"])
    print(f"\n  → 설계 점수로 고른 값: {best}")
    for key in ("레버리지 없음", "레버리지 1%", "레버리지 2%", "안 팖", "사이클 종료", " 50% ", " 70% "):
        g = [n for n in cands if key in n]
        print(f"     {key.strip():8} 평균: 설계 점수 {np.mean([rows[n][1]['score'] for n in g]):.2f} · 검증 연 {np.mean([rows[n][2]['cagr'] for n in g])*100:+.1f}% · 검증 낙폭 {np.mean([rows[n][2]['mdd'] for n in g])*100:.0f}%")
    kw = rows[best][0]
    log = []
    f = run(d, *full, **kw, log=log)
    print("  연도별: " + " ".join(f"{y}:{(g.iloc[-1] / (f['eq'][f['eq'].index.year < y].iloc[-1] if (f['eq'].index.year < y).any() else 1) - 1)*100:+.0f}%" for y, g in f["eq"].groupby(f["eq"].index.year)))
    for x in log:
        print("  ", *x)
    cur = d.iloc[-1]
    print(f"\n  지금: {d.index[-1].date()} 종가 {cur.close:,.0f} · 사상 최고 {d.high.max():,.0f} · 상승 배열 {'예' if (cur.close > cur.e50 > cur.e200) else '아니오'}")
    for lv in kw["levels"]:
        print(f"     현물 분할가 −{int(lv*100)}%: {d.high.max() * (1 - lv):,.0f} 달러")


if __name__ == "__main__":
    main()
