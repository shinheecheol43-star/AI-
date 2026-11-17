"""국내 시장: 주도 섹터만 / 시장보다 강한 종목만 롱 신호를 받으면 나아지는가 (일봉, smc.stock_swing 규칙).

규칙은 결과를 보기 전에 정했다. 모든 값은 진입 전날 종가까지로 계산.
  종목 강도   = 최근 120거래일(약 6개월) 수익률
  섹터 강도   = 그 섹터 후보 종목들의 종목 강도 평균 (smc.kr_portfolio.POOL 의 11개 섹터)
  주도 섹터   = 섹터 강도 상위 3개
  상대 강도   = 종목 강도 > KODEX 200 의 120일 수익률
구성 (롱 거래당 1%, 숏은 KODEX 인버스 0.5% — smc.kr_portfolio 와 같음)
  기준   시가총액 상위 10 (해마다)
  ①     후보 풀 전체 중 주도 섹터 3개 종목만
  ②     시가총액 상위 10 + 상대 강도
  ③     후보 풀 전체 + 주도 섹터 + 상대 강도
  ④     후보 풀 전체 + 상대 강도만
덤: NAVER·카카오처럼 제자리였던 종목에서 시스템이 신호를 얼마나 냈고, 상대 강도 필터가 무엇을 걸렀는지

사용:  python -m smc.kr_rotation
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import stock_swing as ss
from .kr_portfolio import CAP, INVERSE, POOL, YEARS, account_year, gate, load, long_trades, shares

LOOK = 120


def main():
    kd = load("069500")
    k = kd.set_index("time").close
    kmom = (k / k.shift(LOOK) - 1).shift(1)
    g = gate(k)
    # 인버스 숏 (kr_portfolio 방식 1)
    invc = load(INVERSE).set_index("time").close
    ss.COST = 0.0005
    kx = ss.trades(ss.context(kd))
    ks = kx[(kx.side < 0) & g.reindex(kx.entry).fillna(False).to_numpy().astype(bool)]
    short = pd.DataFrame([dict(entry=t.entry, exit=t.exit, r=(invc[t.exit] / invc[t.entry] - 1 - 0.001) / t.stop_pct,
                               stop_pct=t.stop_pct, side=-1) for t in ks.itertuples() if t.entry in invc.index and t.exit in invc.index])

    mom, cap, trades, sector_of, price = {}, {}, [], {}, {}
    for sec, members in POOL.items():
        for code, name in members.items():
            try:
                d = load(code)
            except Exception:
                continue
            if len(d) < 300:
                continue
            c = d.set_index("time").close
            price[name] = c
            mom[name] = (c / c.shift(LOOK) - 1).shift(1)
            cap[name] = c * shares(code)
            sector_of[name] = sec
            trades.append(long_trades(d, 0.0015, name))
    M, C = pd.DataFrame(mom), pd.DataFrame(cap)
    X = pd.concat(trades, ignore_index=True)
    secmom = pd.DataFrame({sec: M[[n for n in M if sector_of[n] == sec]].mean(axis=1) for sec in POOL})
    rank = secmom.rank(axis=1, ascending=False)
    X["smom"] = [M[n].get(t, np.nan) for n, t in zip(X.sym, X.entry)]
    X["kmom"] = kmom.reindex(X.entry).to_numpy()
    X["rs"] = X.smom > X.kmom
    X["lead"] = [bool(rank[sector_of[n]].get(t, 99) <= 3) for n, t in zip(X.sym, X.entry)]
    top10 = {}
    for y in range(2012, 2027):
        row = C[C.index < f"{y}-01-01"].iloc[-1].dropna()
        top10[y] = set(row.sort_values(ascending=False).index[:10])
    X["top10"] = [n in top10.get(t.year, set()) for n, t in zip(X.sym, X.entry)]

    variants = {"기준: 시가총액 상위 10": X.top10, "① 주도 섹터 3개": X.lead, "② 상위 10 + 상대 강도": X.top10 & X.rs,
                "③ 주도 섹터 + 상대 강도": X.lead & X.rs, "④ 상대 강도만 (풀 전체)": X.rs}
    print("국내 시장 · 주도 섹터·상대 강도 필터 · 롱 1% + KODEX 인버스 0.5% · R 은 비용 뺀 값\n")
    print(f"  {'구성':22} | {'2012~2019 평균R (건수)':>22} | {'2020~ 평균R (건수)':>18}")
    for name, m in variants.items():
        a = X[m & (X.entry >= "2012-01-01") & (X.entry < ss.SPLIT)]
        b = X[m & (X.entry >= ss.SPLIT)]
        print(f"  {name:22} | {a.r.mean():+10.3f}R ({len(a):5}) | {b.r.mean():+8.3f}R ({len(b):4})")

    print("\n■ 1,000만원 계좌 연도별 — 수익률 (거래 수 · 승률)")
    print(f"  {'구성':22} | " + " | ".join(f"{y}".center(19) for y in YEARS) + " | 누적")
    for name, m in variants.items():
        L = X[m]
        cells, tot = [], 1.0
        for y in YEARS:
            ret, n, w = account_year(L, short, y)
            tot *= 1 + ret
            cells.append(f"{ret*100:+6.1f}% ({n:3}·{w*100 if n else 0:3.0f}%)")
        print(f"  {name:22} | " + " | ".join(cells) + f" | {CAP*tot:,.0f}원")

    print("\n■ 해마다 1월 초 주도 섹터 (6개월 강도 상위 3)")
    for y in YEARS:
        r = rank[rank.index < f"{y}-01-01"].iloc[-1].sort_values()
        print(f"   {y}: {', '.join(r.index[:3])}")

    print("\n■ 제자리였던 종목에서 시스템은? (2020~)")
    print(f"  {'종목':12} | {'2020→현재 주가':>13} | {'롱 신호':>6} {'평균R':>6} | {'상대 강도 통과':>12} {'평균R':>6} | {'걸러진 신호':>10} {'평균R':>6}")
    for n in ["NAVER", "카카오", "LG생활건강", "엔씨소프트", "삼성전자", "SK하이닉스", "한화에어로스페이스"]:
        if n not in price:
            continue
        p = price[n]
        p = p[p.index >= "2020-01-01"]
        z = X[(X.sym == n) & (X.entry >= ss.SPLIT)]
        a, b = z[z.rs], z[~z.rs]
        print(f"  {n:12} | {(p.iloc[-1] / p.iloc[0] - 1)*100:+12.0f}% | {len(z):6} {z.r.mean():+6.2f} | {len(a):12} {a.r.mean():+6.2f} | {len(b):10} {b.r.mean():+6.2f}")


if __name__ == "__main__":
    main()
