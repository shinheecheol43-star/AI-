"""국내 시장 포트폴리오: 숏은 KODEX 인버스, 롱 종목은 해마다 다시 고르기, ETF 만 쓰는 버전 (일봉, smc.stock_swing 규칙).

규칙은 결과를 보기 전에 정했다.
  숏 (KODEX 인버스 114800)
    조정장 스위치: KODEX 200 이 250일 최고가 대비 −10% 이상이면 켜짐, −5% 이내로 회복하면 꺼짐 (전날 종가 기준)
    방식 1 '지수 숏 신호 → 인버스 매수': 스위치가 켜졌을 때 KODEX 200 에 숏 신호(S5·S2)가 나오면
             같은 날 인버스를 사고 그 숏 거래가 끝나는 날 판다. 손익 = 인버스 가격 변화, 크기는 그 숏 거래의 손절폭 기준
    방식 2 '인버스에 롱 규칙': 스위치가 켜졌을 때만 인버스 ETF 자체에 스윙 롱 규칙 적용
  롱 종목 고르기 (해마다 1월 1일, 직전 1년 평균 거래대금 = 종가 × 거래량, 시가총액 대신)
    (가) 거래대금 상위 10  (나) 섹터별 상위 5  — 후보 풀은 아래 POOL (시기별 대형주, 지금은 작아진 종목 포함)
  ETF 만: KODEX 200 · 코스닥150 · 반도체 · 자동차 · 은행 · 2차전지산업 · 헬스케어 롱 + 인버스 숏
비용 편도: 주식 0.15%, ETF 0.05%. 계좌 1,000만원, 롱 거래당 1% · 숏 거래당 0.5%, 레버리지 없음
  (롱·숏 손익을 각각 계산해 더한 근사)

사용:  python -m smc.kr_portfolio
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import stock_swing as ss

CAP = 10_000_000
YEARS = range(2020, 2027)
POOL = {
    "반도체": {"005930": "삼성전자", "000660": "SK하이닉스", "009150": "삼성전기", "042700": "한미반도체"},
    "자동차": {"005380": "현대차", "000270": "기아", "012330": "현대모비스"},
    "금융": {"105560": "KB금융", "055550": "신한지주", "086790": "하나금융지주", "032830": "삼성생명", "316140": "우리금융지주"},
    "바이오": {"068270": "셀트리온", "207940": "삼성바이오로직스", "000100": "유한양행"},
    "인터넷·게임": {"035420": "NAVER", "035720": "카카오", "036570": "엔씨소프트", "251270": "넷마블"},
    "2차전지·화학": {"051910": "LG화학", "006400": "삼성SDI", "373220": "LG에너지솔루션", "096770": "SK이노베이션", "003670": "포스코퓨처엠"},
    "철강·소재": {"005490": "POSCO홀딩스", "010130": "고려아연"},
    "조선·방산": {"329180": "HD현대중공업", "009540": "HD한국조선해양", "012450": "한화에어로스페이스", "034020": "두산에너빌리티"},
    "통신·유틸": {"017670": "SK텔레콤", "030200": "KT", "015760": "한국전력"},
    "소비재": {"051900": "LG생활건강", "090430": "아모레퍼시픽", "033780": "KT&G"},
    "지주·전자": {"066570": "LG전자", "028260": "삼성물산", "034730": "SK", "003550": "LG"},
}
ETFS = {"069500": "KODEX 200", "229200": "KODEX 코스닥150", "091160": "KODEX 반도체", "091180": "KODEX 자동차",
        "091170": "KODEX 은행", "305720": "KODEX 2차전지산업", "266420": "KODEX 헬스케어"}
INVERSE = "114800"


def shares(code: str) -> float:
    """야후 연간 보통주 수 중 가장 이른 값 (2022년 무렵). 액면분할은 과거 주가가 이미 조정돼 있어 그대로 곱해도 됨."""
    import requests

    r = requests.get(f"https://query1.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/{code}.KS",
                     params={"type": "annualOrdinarySharesNumber", "period1": 1420070400, "period2": 1800000000},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    vals = [v for v in r.json()["timeseries"]["result"][0].get("annualOrdinarySharesNumber", []) if v]
    return float(vals[0]["reportedValue"]["raw"]) if vals else float("nan")


def load(code):
    d = ss.fetch(code + ".KS")
    return d[(d.close > 0) & (d.volume >= 0)].reset_index(drop=True)


def long_trades(d, cost, name):
    ss.COST = cost
    x = ss.trades(ss.context(d))
    return x[x.side > 0].assign(sym=name)


def gate(close: pd.Series) -> pd.Series:
    dd = close / close.rolling(250, min_periods=60).max() - 1
    state, out = False, []
    for v in dd.to_numpy():
        if not state and v <= -0.10:
            state = True
        elif state and v > -0.05:
            state = False
        out.append(state)
    return pd.Series(out, index=close.index).shift(1).fillna(False).astype(bool)


def account_year(longs: pd.DataFrame, shorts: pd.DataFrame, y: int) -> tuple[float, int, float]:
    bal, n, wins = CAP, 0, 0
    for df, risk in ((longs, 0.01), (shorts, 0.005)):
        z = df[(df.entry >= f"{y}-01-01") & (df.entry < f"{y + 1}-01-01")]
        if len(z):
            bal += ss.equity(z, risk=risk, start=CAP).iloc[-1] - CAP
            n += len(z)
            wins += int((z.r > 0).sum())
    return bal / CAP - 1, n, wins / n if n else float("nan")


def main():
    k = load("069500").set_index("time").close
    g = gate(k)
    inv = load(INVERSE)
    invc = inv.set_index("time").close
    # 숏 방식 1: 지수 숏 신호 → 인버스
    ss.COST = 0.0005
    kx = ss.trades(ss.context(load("069500")))
    ks = kx[(kx.side < 0) & g.reindex(kx.entry).fillna(False).to_numpy().astype(bool)].copy()
    rows = []
    for t in ks.itertuples():
        if t.entry not in invc.index or t.exit not in invc.index:
            continue
        ret = invc[t.exit] / invc[t.entry] - 1 - 2 * 0.0005
        rows.append(dict(entry=t.entry, exit=t.exit, r=ret / t.stop_pct, stop_pct=t.stop_pct, side=-1, sym="KODEX 인버스"))
    short1 = pd.DataFrame(rows)
    # 숏 방식 2: 인버스에 롱 규칙 (스위치 켜졌을 때만)
    ix = long_trades(inv, 0.0005, "KODEX 인버스")
    short2 = ix[g.reindex(ix.entry).fillna(False).to_numpy().astype(bool)].assign(side=-1)

    print("국내 시장 포트폴리오 · 숏 = KODEX 인버스 · 2020~2026 · R 은 비용 뺀 값\n")
    for lab, s in (("방식 1 지수 숏 신호 → 인버스", short1), ("방식 2 인버스에 롱 규칙", short2)):
        a, b = s[s.entry < ss.SPLIT], s[s.entry >= ss.SPLIT]
        print(f"  숏 {lab:24} | {len(s):4}건 승률 {(s.r > 0).mean()*100:3.0f}% 평균 {s.r.mean():+.2f}R | ~2019 {a.r.mean():+.2f}R ({len(a)}) | 2020~ {b.r.mean():+.2f}R ({len(b)})")
    short = short1

    # 후보 풀 데이터와 해마다 거래대금 순위
    data, sector_of, tv, cap = {}, {}, {}, {}
    for sec, members in POOL.items():
        for code, name in members.items():
            try:
                d = load(code)
            except Exception:
                continue
            if len(d) < 300:
                continue
            data[name], sector_of[name] = d, sec
            s = d.set_index("time")
            tv[name] = (s.close * s.volume).rolling(250, min_periods=200).mean()
            cap[name] = s.close * shares(code)
    TV = pd.DataFrame(tv)
    CAPS = pd.DataFrame(cap)
    top10, sec5, cap10 = {}, {}, {}
    for y in YEARS:
        row = TV[TV.index < f"{y}-01-01"].iloc[-1].dropna()
        top10[y] = list(row.sort_values(ascending=False).index[:10])
        crow = CAPS[CAPS.index < f"{y}-01-01"].iloc[-1].dropna()
        cap10[y] = list(crow.sort_values(ascending=False).index[:10])
        sec5[y] = [n for sec in POOL for n in row[[m for m in row.index if sector_of[m] == sec]].sort_values(ascending=False).index[:5]]
    print("\n  해마다 고른 시가총액 상위 10 (연초 직전 종가 × 상장주식수, 후보 풀 안에서):")
    for y in YEARS:
        print(f"   {y}: {', '.join(cap10[y])}")

    lt = {name: long_trades(d, 0.0015, name) for name, d in data.items()}

    def picked(sel):
        parts = []
        for y in YEARS:
            for name in sel[y]:
                x = lt[name]
                parts.append(x[(x.entry >= f"{y}-01-01") & (x.entry < f"{y + 1}-01-01")])
        return pd.concat(parts, ignore_index=True)

    etf_long = pd.concat([long_trades(load(c), 0.0005, n) for c, n in ETFS.items()], ignore_index=True)
    ports = {"ETF 만 (KODEX 7개 + 인버스)": (etf_long, short),
             "(다) 시가총액 상위 10 + 인버스": (picked(cap10), short),
             "(다) 시가총액 상위 10 롱만": (picked(cap10), short.iloc[0:0]),
             "(가) 거래대금 상위 10 + 인버스": (picked(top10), short),
             "(나) 섹터별 상위 5 + 인버스": (picked(sec5), short),
             "(가) 롱만 (숏 없음)": (picked(top10), short.iloc[0:0])}
    print("\n■ 1,000만원 계좌 연도별 (롱 1% · 인버스 0.5%) — 수익률 (거래 수 · 승률)")
    print(f"  {'구성':28} | " + " | ".join(f"{y}".center(19) for y in YEARS) + " | 누적")
    for name, (L, S) in ports.items():
        cells, tot = [], 1.0
        for y in YEARS:
            ret, n, w = account_year(L, S, y)
            tot *= 1 + ret
            cells.append(f"{ret*100:+6.1f}% ({n:3}·{w*100 if n else 0:3.0f}%)")
        print(f"  {name:28} | " + " | ".join(cells) + f" | {CAP*tot:,.0f}원")
    bh = []
    for y in YEARS:
        b = k[(k.index >= f"{y}-01-01") & (k.index < f"{y + 1}-01-01")]
        bh.append(b.iloc[-1] / b.iloc[0] - 1)
    print(f"  {'KODEX 200 보유':28} | " + " | ".join(f"{v*100:+6.1f}%".center(19) for v in bh) + f" | {CAP*np.prod([1 + v for v in bh]):,.0f}원")


if __name__ == "__main__":
    main()
