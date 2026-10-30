"""델타 트레이딩 두 가지 검증 (BTC·ETH).

A. 델타 중립 펀딩비 차익: 현물 1개 롱 + 무기한 선물 1개 숏 (가격 변동 상쇄, 펀딩비를 받음)
   자본 = 현물 금액 + 선물 증거금(선물 3배 → 명목의 1/3). 수익 = 숏이 받는 펀딩비 ÷ 자본
   비용: 들어가고 나올 때 현물 0.1% + 선물 0.055% (양쪽), 가격이 마지막 조정 시점 대비 ±25% 움직이면
         선물 증거금을 다시 맞추느라 0.2% 비용 (현물 일부 팔아 증거금으로 옮긴다고 가정)
   ① 항상 보유  ② 최근 7일 평균 펀딩비가 플러스일 때만 보유 (전날까지 값으로 판단)
   위험 확인: 선물 숏 3배는 조정 시점 대비 약 +30% 급등하면 청산 위험 → 그런 날이 몇 번이었나
B. 거래량 델타(CVD): 시장가 매수 − 시장가 매도
   근거 (검증 전에 정함, 신호 방향 기준으로 바꿔 계산)
     봉 델타 비율     = 신호 4시간봉의 델타 ÷ 거래량
     20봉 델타 비율   = 최근 20개 4시간봉 델타 합 ÷ 거래량 합
     가격·CVD 일치   = 최근 20봉 가격 변화와 CVD 변화의 방향이 같은가 (다르면 '다이버전스')
   1) 스윙 거래(smc.system: 스윙 롱·숏 S5·숏 S2)의 평균 R 을 근거 구간별로 비교 (기준값은 설계 구간 3분위)
   2) 델타만으로 다음 24시간 수익을 예측할 수 있나 (10분위)
   3) '가격·CVD 일치' 를 필터로 붙인 한 계좌 결과
설계 구간 ~2021, 검증 구간 2022~.

사용:  python -m smc.delta_study
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import system as S
from .dd_brake import curve
from .flow import fetch_flow, to_tf
from .regime import fetch_funding
from .research_report import SPLIT
from .swing_ls import describe

SPOT_FEE, PERP_FEE, REBAL_COST, REBAL_MOVE, PERP_LEV = 0.001, 0.00055, 0.002, 0.25, 3.0


# ---------------------------------------------------------------- A. 펀딩비 차익
def carry(sym: str) -> pd.DataFrame:
    fund = fetch_funding(sym + "USDT")
    h = fetch_flow(sym + "USDT")
    day = h.set_index("time").resample("1D").agg({"high": "max", "close": "last"}).dropna()
    day = day[day.index >= fund.index[0]]
    fund = fund.reindex(day.index).fillna(0.0)
    cap = 1 + 1 / PERP_LEV
    on7 = fund.rolling(7).mean().shift(1) > 0
    out = {}
    for name, hold in (("항상 보유", pd.Series(True, index=day.index)), ("7일 평균 플러스일 때만", on7.fillna(False))):
        ret, ref, danger, rebal = [], None, 0, 0
        prev = False
        for t in day.index:
            r = 0.0
            h_ = bool(hold[t])
            if h_ != prev:
                r -= (SPOT_FEE + PERP_FEE) / cap          # 들어가거나 나올 때 한쪽 비용
                ref = day.close[t] if h_ else None
            if h_:
                r += fund[t] / cap                        # 숏이 받는 펀딩비 (마이너스면 냄)
                if day.high[t] >= ref * (1 + 1 / PERP_LEV - 0.03):
                    danger += 1
                if abs(day.close[t] / ref - 1) >= REBAL_MOVE:
                    r -= REBAL_COST / cap
                    ref, rebal = day.close[t], rebal + 1
            ret.append(r)
            prev = h_
        out[name] = (pd.Series(ret, index=day.index), danger, rebal, hold.mean())
    return out, fund


def report_carry():
    print("■ A. 델타 중립 펀딩비 차익 (현물 롱 + 선물 숏 3배, 자본 = 현물 + 선물 증거금)")
    for sym in ("BTC", "ETH"):
        res, fund = carry(sym)
        print(f"\n{sym}  펀딩비 {fund.index[0]:%Y-%m} ~ {fund.index[-1]:%Y-%m} · 펀딩비가 마이너스인 날 {(fund < 0).mean()*100:.0f}%"
              f" · 하루 평균 {fund.mean()*100:.3f}%")
        print(f"{'방식':22} | {'연 수익':>7} {'최대 낙폭':>8} {'최악 30일':>9} | {'보유율':>5} {'재조정':>5} {'청산 근접일':>8} | 연도별")
        for name, (r, danger, rebal, held) in res.items():
            eq = (1 + r).cumprod()
            yrs = (r.index[-1] - r.index[0]).days / 365.25
            worst30 = (eq / eq.shift(30) - 1).min()
            years = " ".join(f"{y}:{(1 + g).prod()*100-100:+.1f}%" for y, g in r.groupby(r.index.year))
            print(f"{name:22} | {eq.iloc[-1]**(1/yrs)*100-100:+6.1f}% {(eq/eq.cummax()-1).min()*100:7.1f}% {worst30*100:8.1f}% |"
                  f" {held*100:4.0f}% {rebal:5} {danger:8} | {years}")


# ---------------------------------------------------------------- B. 거래량 델타
def flow_features(sym: str) -> pd.DataFrame:
    d = to_tf(fetch_flow(sym + "USDT"), "4h")
    d["cvd"] = d.delta.cumsum()
    d["dr1"] = d.delta / d.volume
    d["dr20"] = d.delta.rolling(20).sum() / d.volume.rolling(20).sum()
    d["agree"] = np.sign(d.close - d.close.shift(20)) == np.sign(d.cvd - d.cvd.shift(20))
    d["fwd6"] = d.close.shift(-6) / d.close - 1
    return d.set_index("time")


def report_flow():
    print("\n\n■ B. 거래량 델타(CVD)")
    F = {s: flow_features(s) for s in S.SYMS}
    print("\n1) 델타만으로 다음 24시간 수익 예측 (4시간봉, 20봉 델타 비율 10분위)")
    for sym, d in F.items():
        x = d.dropna(subset=["dr20", "fwd6"])
        q = pd.qcut(x.dr20.rank(method="first"), 10, labels=False) + 1
        g = x.groupby(q).fwd6.mean() * 100
        a = x[x.index < SPLIT].groupby(q[x.index < SPLIT]).fwd6.mean() * 100
        b = x[x.index >= SPLIT].groupby(q[x.index >= SPLIT]).fwd6.mean() * 100
        print(f"  {sym} 전체 " + " ".join(f"{v:+.2f}" for v in g) + "  (1분위=매도 우세 … 10분위=매수 우세, 단위 %)")
        print(f"  {sym} 설계 " + " ".join(f"{v:+.2f}" for v in a))
        print(f"  {sym} 검증 " + " ".join(f"{v:+.2f}" for v in b))
    Xs = {s: S.context(s) for s in S.SYMS}
    sw = pd.concat([S.swing_trades(X) for X in Xs.values()], ignore_index=True)
    sw = sw[~sw.open.astype(bool)].copy()
    sw = sw.assign(risk=sw.src.map(S.RISK), r=sw.r - 2 * S.SLIP / sw.stop_pct)
    sig = sw.entry - pd.Timedelta("4h")
    for col in ("dr1", "dr20", "agree"):
        sw[col] = [F[s][col].get(t, np.nan) for s, t in zip(sw.symbol, sig)]
    sw["dr1"] *= sw.side
    sw["dr20"] *= sw.side
    print("\n2) 스윙 거래를 델타 근거로 나눈 평균 R (방향 기준: 값이 클수록 신호 방향으로 체결이 몰림)")
    print(f"{'전략':6} {'근거':12} | {'하위 1/3':>16} {'중간':>16} {'상위 1/3':>16} | 상위−하위 (설계 / 검증)")
    for src in ("스윙 롱", "숏 S5", "숏 S2"):
        y = sw[sw.src == src]
        for col in ("dr1", "dr20"):
            tr = y[y.entry < SPLIT][col]
            q1, q2 = tr.quantile([1 / 3, 2 / 3])
            b = pd.cut(y[col], [-np.inf, q1, q2, np.inf], labels=["하", "중", "상"])
            cell = lambda z: f"{len(z):3} {(z.r>0).mean()*100:3.0f}% {z.r.mean():+.2f}"
            diff = lambda m: y[m & (b == "상")].r.mean() - y[m & (b == "하")].r.mean()
            print(f"{src:6} {col:12} | {cell(y[b=='하']):>16} {cell(y[b=='중']):>16} {cell(y[b=='상']):>16} |"
                  f" {diff(y.entry < SPLIT):+.2f} / {diff(y.entry >= SPLIT):+.2f}")
        for v, lab in ((True, "일치"), (False, "다이버전스")):
            z = y[y.agree == v]
            print(f"{src:6} 가격·CVD {lab:6} | {len(z):3}건 승률 {(z.r>0).mean()*100:3.0f}% 평균 {z.r.mean():+.2f}R"
                  f" (설계 {z[z.entry<SPLIT].r.mean():+.2f} / 검증 {z[z.entry>=SPLIT].r.mean():+.2f})")
    print("\n3) '가격·CVD 일치' 필터를 붙인 BTC+ETH 한 계좌 (리스크 그대로)")
    for name, y in (("필터 없음 (지금)", sw), ("일치할 때만 진입", sw[sw.agree == True])):  # noqa: E712
        cv, _ = curve(y)
        d = describe(cv)
        f, a, b = d["full"], d["design"], d["test"]
        print(f"  {name:18} | {f[0]*100:+6.1f}% 낙폭 {f[1]*100:6.1f}% 효율 {f[0]/-f[1]:.2f} | 설계 {a[0]*100:+6.1f}% | 검증 {b[0]*100:+6.1f}% | {len(y)}건")


def main():
    report_carry()
    report_flow()


if __name__ == "__main__":
    main()
