"""미국 주도주 스윙: 주도 섹터 안의 강한 대형주 돌파 (국내 균형형 틀) + 선택: QQQ 큰 조정 매수 (일봉).

규칙과 후보 값은 결과를 보기 전에 정했다.
  후보: 미국 대형주 약 85개 (11 섹터, 지금은 작아진 옛 대형주 포함). 매일 '60일 평균 거래대금 상위 40' 만 매매 가능 (그 시점 대형주 근사)
     한계: 상장폐지·파산 종목(리먼 등)은 야후에 없어 빠짐 → 결과가 실제보다 조금 좋게 나올 수 있음
  시장 상태 SPY (전날, 50/200 지수이평 배열): 상승 = 20일 돌파·손절 ATR×2·추적 ×3 / 박스 = 60일·×3·×5 / 하락 = 새 매수 없음 · 최대 60일
  종목: 근거 4개 중 3개 + 120일 수익률 > SPY + 돌파일 종가가 캔들 위 25%
  후보 값: 주도 섹터 상위 3 / 제한 없음 · 섹터당 최대 2종목 / 제한 없음 · 위험 1% / 2% (SPY 20일선 아래면 절반) · 조정 매수 없음 / QQQ −10% 50% 2년
  최대 8종목, 비용 편도 0.1%, 배당 제외, 레버리지 없음
고르기 = 2005~2014 '연수익 ÷ |최대 낙폭|', 채점 = 2015~2026-11.
사용: python -m smc.us_leaders
"""
from __future__ import annotations

from itertools import product

import numpy as np
import pandas as pd

from .stock_swing import fetch
from .us_dip import COST, DESIGN, FAST, SLOW, TEST, feats, stats, yearly

SECTORS = {
    "기술": "AAPL MSFT NVDA AVGO ORCL CSCO INTC IBM QCOM TXN ADBE CRM AMD MU AMAT",
    "커뮤니케이션": "GOOG META NFLX DIS CMCSA T VZ",
    "경기소비재": "AMZN TSLA HD MCD NKE SBUX LOW BKNG",
    "필수소비재": "WMT PG KO PEP COST PM MO",
    "헬스케어": "JNJ UNH PFE MRK ABBV LLY AMGN TMO ABT BMY GILD",
    "금융": "JPM BAC WFC C GS MS AIG BRK-B V MA AXP",
    "에너지": "XOM CVX COP SLB OXY",
    "산업재": "GE BA CAT HON UNP MMM LMT UPS RTX",
    "소재": "FCX NEM DD",
    "유틸리티": "NEE DUK SO",
    "부동산": "AMT PLD SPG",
}
SECTOR = {s: sec for sec, v in SECTORS.items() for s in v.split()}


def load():
    raw = {}
    for s in ["SPY", "QQQ", *SECTOR]:
        try:
            d = fetch(s)
        except Exception as e:
            print("  받기 실패", s, e)
            continue
        d["time"] = d.time.dt.tz_localize(None).dt.normalize()
        raw[s] = d.set_index("time")
        raw[s] = raw[s][~raw[s].index.duplicated()]
    idx = raw["SPY"].index
    F = {s: feats(d).reindex(idx) for s, d in raw.items()}
    dv = pd.DataFrame({s: (raw[s].close * raw[s].volume).rolling(60).mean().shift(1).reindex(idx) for s in raw if s in SECTOR})
    elig = dv.rank(axis=1, ascending=False) <= 40
    mom = pd.DataFrame({s: F[s].mom for s in dv})
    secm = pd.DataFrame({sec: mom[[s for s in dv if SECTOR[s] == sec]].where(elig[[s for s in dv if SECTOR[s] == sec]]).mean(axis=1) for sec in SECTORS})
    srank = secm.rank(axis=1, ascending=False)
    k = F["SPY"]
    st = pd.Series("박스", index=idx)
    st[(k.close > k.ema50) & (k.ema50 > k.ema200)] = "상승"
    st[(k.close < k.ema50) & (k.ema50 < k.ema200)] = "하락"
    return dict(F=F, idx=idx, st=st.shift(1).fillna("박스"), weak=(k.close < k.ema20).shift(1).fillna(False).astype(bool),
                elig=elig, srank=srank, names=list(dv.columns))


def run(D, lo, hi, top_sec=3, sec_cap=None, risk=0.01, dip=False, log=None):
    F, idx, st, weak, elig, srank = D["F"], D["idx"], D["st"], D["weak"], D["elig"], D["srank"]
    i0, i1 = int(idx.searchsorted(pd.Timestamp(lo))), int(idx.searchsorted(pd.Timestamp(hi)))
    qc = F["QQQ"].close
    dd = (qc / qc.rolling(250, min_periods=60).max() - 1).to_numpy()
    cash, pos, dips, eq, last_exit, armed = 1.0, [], [], [], {}, True
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
                if log is not None:
                    log.append(dict(s=p["s"], sec=SECTOR[p["s"]], entry=idx[p["i"]], exit=idx[i], ret=ex / p["p0"] - 1 - 2 * COST, days=i - p["i"]))
        c = qc.iat[i]
        for d in list(dips):
            if i - d["i"] >= 500:
                cash += d["q"] * c * (1 - COST)
                dips.remove(d)
        if not armed and dd[i] > -0.05 and not dips:
            armed = True
        val = sum(p["q"] * (F[p["s"]].close.iat[i] if np.isfinite(F[p["s"]].close.iat[i]) else p["p0"]) for p in pos) + sum(d["q"] * c for d in dips)
        E = cash + val
        eq.append(E)
        if dip and armed and dd[i] <= -0.10:
            money = min(E * 0.5, cash)
            if money > 0:
                dips.append(dict(i=i, q=money / (c * (1 + COST))))
                cash -= money
            armed = False
        state = st.iat[i]
        if state == "하락" or len(pos) >= 8:
            continue
        N, sk, tk, hold = FAST if state == "상승" else SLOW
        r_ = risk / 2 if weak.iat[i] else risk
        kmom = F["SPY"].mom.iat[i]
        cands = []
        for s in D["names"]:
            if not elig[s].iat[i] or any(p["s"] == s for p in pos) or last_exit.get(s, -1) >= i:
                continue
            if top_sec and not srank[SECTOR[s]].iat[i] <= top_sec:
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
            if ev >= 3 and f.mom.iat[i] > kmom and cpos >= 0.75:
                cands.append((f.mom.iat[i], s, cl, a))
        for _, s, cl, a in sorted(cands, reverse=True):          # 같은 날이면 120일 수익률 강한 순
            if len(pos) >= 8:
                break
            if sec_cap and sum(SECTOR[p["s"]] == SECTOR[s] for p in pos) >= sec_cap:
                continue
            money = min(E * r_ / (sk * a / cl), cash)
            if money <= 0:
                continue
            pos.append(dict(s=s, i=i, p0=cl, q=money / (cl * (1 + COST)), stop=cl - sk * a, ext=cl, trail=tk, hold=hold))
            cash -= money
    eq = pd.Series(eq, index=idx[i0:i1])
    return stats(eq) | {"eq": eq}


def main():
    D = load()
    F, idx = D["F"], D["idx"]
    full = (DESIGN[0], TEST[1])
    print(f"미국 주도주 스윙 · 후보 {len(D['names'])}종목 중 그날 거래대금 상위 40 · 비용 편도 0.1% · 배당 제외 · 평가금액 낙폭\n")
    hdr = f"  {'구성':40} | {'2005~2014 연':>12} {'낙폭':>6} {'점수':>5} | {'2015~2026 연':>12} {'낙폭':>6} | {'전체 연':>7} {'낙폭':>6} {'1,000만원→':>13} | 손실해"
    print(hdr)
    rows = {}

    def line(name, fn):
        f, b = fn(*full), fn(*TEST)
        a = stats(f["eq"][f["eq"].index < DESIGN[1]])
        ys = yearly(f["eq"])
        rows[name] = (a, b, f, ys)
        print(f"  {name:40} | {a['cagr']*100:+11.1f}% {a['mdd']*100:5.1f}% {a['score']:5.2f} | {b['cagr']*100:+11.1f}% {b['mdd']*100:5.1f}% |"
              f" {f['cagr']*100:+6.1f}% {f['mdd']*100:5.1f}% {f['final']*1e7:13,.0f} | {sum(v < 0 for v in ys.values())}년", flush=True)

    for s in ("SPY", "QQQ"):
        line(f"{s} 보유", lambda lo, hi, s=s: (lambda e: stats(e) | {"eq": e})(F[s].close[(idx >= lo) & (idx < hi)] / F[s].close[(idx >= lo) & (idx < hi)].iloc[0]))
    for ts, cap, risk, dip in product((3, None), (None, 2), (0.01, 0.02), (False, True)):
        name = f"{'주도섹터3' if ts else '섹터무관'} · {'섹터당2' if cap else '분산제한X'} · 위험{risk*100:.0f}% · {'조정매수O' if dip else '조정매수X'}"
        line(name, lambda lo, hi, a=(ts, cap, risk, dip): run(D, lo, hi, *a))
    cands = [n for n in rows if "보유" not in n]
    best = max(cands, key=lambda n: rows[n][0]["score"])
    print(f"\n  → 설계 점수로 고른 값: {best}")
    for key in ("주도섹터3", "섹터무관", "섹터당2", "분산제한X", "위험1%", "위험2%", "조정매수O", "조정매수X"):
        g = [n for n in cands if key in n]
        print(f"     {key:8} 평균: 설계 점수 {np.mean([rows[n][0]['score'] for n in g]):.2f} · 검증 연 {np.mean([rows[n][1]['cagr'] for n in g])*100:+.1f}% · 검증 낙폭 {np.mean([rows[n][1]['mdd'] for n in g])*100:.1f}%")
    ts, cap, risk, dip = (3 if "주도섹터3" in best else None), (2 if "섹터당2" in best else None), (0.02 if "위험2%" in best else 0.01), ("조정매수O" in best)
    log = []
    run(D, *full, ts, cap, risk, dip, log=log)
    L = pd.DataFrame(log)
    print(f"\n  스윙 거래 {len(L)}건 · 승률 {(L.ret > 0).mean()*100:.0f}% · 평균 {L.ret.mean()*100:+.2f}% · 평균 보유 {L.days.mean():.0f}일")
    print("  섹터별: " + " · ".join(f"{k} {len(g)}건 {g.ret.mean()*100:+.1f}%" for k, g in L.groupby("sec")))
    top = L.groupby("s").ret.agg(["size", "sum"]).sort_values("sum", ascending=False)
    print("  수익 많이 낸 종목: " + " · ".join(f"{s}({int(r['size'])}건 {r['sum']*100:+.0f}%)" for s, r in top.head(8).iterrows()))
    print("  손실 많이 낸 종목: " + " · ".join(f"{s}({int(r['size'])}건 {r['sum']*100:+.0f}%)" for s, r in top.tail(5).iterrows()))
    q = F["QQQ"].close
    print("\n  연도 | 고른 값 | QQQ")
    for y, v in rows[best][3].items():
        b = q[(q.index >= f"{y}-01-01") & (q.index < f"{y + 1}-01-01")]
        print(f"  {y} | {v*100:+7.1f}% | {(b.iloc[-1]/b.iloc[0]-1)*100:+6.1f}%")


if __name__ == "__main__":
    main()
