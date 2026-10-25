"""스윙(롱 + 숏 S5·S2)과 데이트레이딩 롱(시가범위 돌파 + 전일 고점 위)을 한 계좌로.

각 전략의 거래 목록을 따로 만든 뒤, 진입 순서대로 한 잔고에서 크기를 정한다.
  크기 : 진입 시점 잔고 × 그 전략의 리스크 ÷ 손절폭, 열린 포지션 합계 레버리지 3배 이하
  손익 : 거래별 R × 진입 시점 리스크 금액 (수수료·펀딩비는 각 시뮬레이션에 이미 포함)
근사: 데이트레이딩 '하루 −1% 중단'은 데이트레이딩 단독 계좌 기준으로 이미 걸러진 거래를 쓴다.

사용:  python -m smc.combo_all
"""
from __future__ import annotations

import pandas as pd

from . import daytrade3, ls_combo
from .swing_ls import describe


def day_trades(**kw) -> pd.DataFrame:
    t = daytrade3.run(above_ph=True, **kw)["trades"]
    return pd.DataFrame({"symbol": t.sym, "side": t.side, "src": "D", "entry": t.entry_time, "exit": t.exit_time,
                         "r": t.r, "stop_pct": t.stop_pct, "p0": 0.0})


def monthly(cv: pd.Series) -> pd.Series:
    return cv.resample("ME").last().ffill().pct_change()


def main():
    P = ls_combo.closes()
    T = ls_combo.pool(P)
    D = day_trades()
    D15 = day_trades(stop_k=1.5)
    sw = {"스윙 L1 / S0.5": dict(long=0.01, s5=0.005, s2=0.005), "스윙 L0.75 / S0.75": dict(long=0.0075, s5=0.0075, s2=0.0075)}
    cfg = {}
    for name, kw in sw.items():
        cfg[name] = ls_combo.build(T, **kw)
    cfg["데이만 0.5%"] = D.assign(risk=0.005)
    cfg["데이만 1%"] = D.assign(risk=0.01)
    for name, kw in sw.items():
        for dr in (0.005, 0.0075, 0.01):
            cfg[f"{name} + 데이 {dr*100:.2f}%"] = pd.concat([ls_combo.build(T, **kw), D.assign(risk=dr)])
        cfg[f"{name} + 데이(손절1.5) 0.75%"] = pd.concat([ls_combo.build(T, **kw), D15.assign(risk=0.0075)])
    print(f"{'구성':34} | {'전체 연평균 낙폭 효율':^20} | {'설계 연평균 낙폭 효율':^20} | {'검증 연평균 낙폭 효율':^20} | 거래 | "
          + " ".join(f"{y:>5}" for y in range(2018, 2027)))
    curves = {}
    for name, x in cfg.items():
        ls_combo.line(name, x, P)
        curves[name] = ls_combo.curve(x, P)
    a, b = monthly(curves["스윙 L1 / S0.5"]), monthly(curves["데이만 0.5%"])
    m = pd.concat([a, b], axis=1).dropna()
    print(f"\n스윙 vs 데이 월간 수익률 상관계수: {m.corr().iloc[0, 1]:+.2f} ({len(m)}개월)")
    m.columns = ["sw", "day"]
    up = m.sw > 0
    print(f"스윙 손실 달 {(~up).sum()}개월: 데이 평균 {m.day[~up].mean()*100:+.2f}%, 데이도 손실 {(m.day[~up] < 0).mean()*100:.0f}%"
          f" | 스윙 수익 달: 데이 평균 {m.day[up].mean()*100:+.2f}%")
    d = describe(curves["스윙 L1 / S0.5 + 데이 0.75%"])
    worst = (curves["스윙 L1 / S0.5 + 데이 0.75%"].resample("ME").last().ffill().pct_change()).nsmallest(3)
    print("합친 계좌(L1/S0.5 + 데이 0.75%) 최악의 달:", ", ".join(f"{k:%Y-%m} {v*100:+.1f}%" for k, v in worst.items()),
          f"| $1,000 → ${d['final']:,.0f}")


if __name__ == "__main__":
    main()
