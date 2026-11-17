"""국내 시장(코스피·코스닥 ETF, 대형주)에 스윙 시스템 적용 (일봉, 야후 파이낸스).

규칙은 smc.stock_swing (코인 4시간봉 스윙 규칙을 일봉으로 옮긴 것, 이전에 미국 ETF 용으로 정함) 그대로. 국내 데이터를 보고 바꾸지 않았다.
  스윙 롱: 종가가 직전 20일 고가를 처음 돌파 + 근거 4개 중 3개 (200일 EMA 위, 일봉 국면 +3, RSI > 60, 20일 EMA 이격 > ATR)
  숏 S5·S2: 참고로만 (개인 공매도가 어려워 실제로는 인버스 ETF 로 대신해야 함)
  손절 ATR×2, 추적 ATR×3, 최대 60일. 비용 편도: 주식 0.15% (수수료+거래세+미끄러짐), ETF 0.05%
종목 (미리 정함): KODEX 200, KODEX 코스닥150, 삼성전자, SK하이닉스, 현대차, NAVER, LG화학, 셀트리온, POSCO홀딩스, KB금융, 카카오, 기아
계좌: 1,000만원, 거래당 손절 시 1% 손실 수량, 레버리지 없음(현물), 모든 종목 한 계좌. 설계 ~2019 / 검증 2020~
비교: KODEX 200 사서 들고 있기

사용:  python -m smc.kr_swing
"""
from __future__ import annotations

import pandas as pd

from . import stock_swing as ss

UNIVERSE = {"069500.KS": ("KODEX 200", 0.0005), "229200.KS": ("KODEX 코스닥150", 0.0005),
            "005930.KS": ("삼성전자", 0.0015), "000660.KS": ("SK하이닉스", 0.0015), "005380.KS": ("현대차", 0.0015),
            "035420.KS": ("NAVER", 0.0015), "051910.KS": ("LG화학", 0.0015), "068270.KS": ("셀트리온", 0.0015),
            "005490.KS": ("POSCO홀딩스", 0.0015), "105560.KS": ("KB금융", 0.0015), "035720.KS": ("카카오", 0.0015),
            "000270.KS": ("기아", 0.0015)}
CAP = 10_000_000
YEARS = range(2020, 2027)


def main():
    allx, bh = [], None
    print("국내 시장 스윙 시스템 (일봉) · 설계 ~2019 / 검증 2020~ · R 은 비용 뺀 값\n")
    print(f"  {'종목':14} {'기간':>11} | {'롱 거래':>6} {'승률':>4} {'평균R':>6} {'설계R':>6} {'검증R':>6} | {'숏(참고) 거래':>10} {'평균R':>6}")
    for sym, (name, cost) in UNIVERSE.items():
        d = ss.fetch(sym)
        d = d[d.close > 0].reset_index(drop=True)
        ss.COST = cost
        x = ss.trades(ss.context(d))
        x = x[~x.open].assign(sym=name)
        L, S = x[x.side > 0], x[x.side < 0]
        print(f"  {name:14} {d.time.iloc[0]:%Y}~{d.time.iloc[-1]:%Y} | {len(L):6} {(L.r > 0).mean()*100:3.0f}% {L.r.mean():+6.2f}"
              f" {L[L.entry < ss.SPLIT].r.mean():+6.2f} {L[L.entry >= ss.SPLIT].r.mean():+6.2f} | {len(S):10} {S.r.mean():+6.2f}")
        allx.append(x)
        if sym == "069500.KS":
            bh = d.set_index("time").close
    X = pd.concat(allx, ignore_index=True)
    L = X[X.side > 0]
    print(f"\n  롱 전체 {len(L)}건 · 승률 {(L.r > 0).mean()*100:.0f}% · 평균 {L.r.mean():+.3f}R · 설계 {L[L.entry < ss.SPLIT].r.mean():+.3f}R"
          f" · 검증 {L[L.entry >= ss.SPLIT].r.mean():+.3f}R")

    print("\n■ 한 계좌 (1,000만원, 거래당 1%, 레버리지 없음) · 롱만 · 연도별")
    print(f"  {'연도':4} | {'거래':>4} {'승률':>4} {'수익률':>7} {'연말 잔고':>13} | {'KODEX 200 보유':>13}")
    for y in YEARS:
        z = L[(L.entry >= f"{y}-01-01") & (L.entry < f"{y + 1}-01-01")]
        if not len(z):
            continue
        cv = ss.equity(z, risk=0.01, start=CAP)
        ret = cv.iloc[-1] / CAP - 1
        b = bh[(bh.index >= f"{y}-01-01") & (bh.index < f"{y + 1}-01-01")]
        bret = b.iloc[-1] / b.iloc[0] - 1
        print(f"  {y} | {len(z):4} {(z.r > 0).mean()*100:3.0f}% {ret*100:+6.1f}% {CAP*(1+ret):13,.0f}원 | {bret*100:+12.1f}%")
    cv = ss.equity(L[L.entry >= ss.SPLIT], risk=0.01, start=CAP)
    lo, hi = ss.SPLIT, cv.index[-1]
    cagr, mdd = ss.summary(cv, lo, hi, start=CAP)
    b = bh[bh.index >= lo]
    bc = (b.iloc[-1] / b.iloc[0]) ** (365.25 / (b.index[-1] - b.index[0]).days) - 1
    bm = (b / b.cummax() - 1).min()
    print(f"\n  2020~ 전체: 스윙 롱 연 {cagr*100:+.1f}% (최대 낙폭 {mdd*100:.1f}%) · 1,000만원 → {cv.iloc[-1]:,.0f}원"
          f"  |  KODEX 200 보유 연 {bc*100:+.1f}% (최대 낙폭 {bm*100:.1f}%)")
    for r in (0.02,):
        cv2 = ss.equity(L[L.entry >= ss.SPLIT], risk=r, start=CAP)
        c2, m2 = ss.summary(cv2, lo, hi, start=CAP)
        print(f"  거래당 {r*100:.0f}% 로 키우면: 연 {c2*100:+.1f}% (최대 낙폭 {m2*100:.1f}%) · 1,000만원 → {cv2.iloc[-1]:,.0f}원")


if __name__ == "__main__":
    main()
