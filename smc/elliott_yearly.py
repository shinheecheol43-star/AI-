"""엘리어트 2파 반전 캔들 전략의 2023~2026 연도별 계좌 성과 (BTC, 롱, 손절 1파 시작점, 시작 1,000만원).

전략 (규칙은 smc.elliott_candle 과 같음, 결과를 보기 전에 정함)
  A  일봉 2파 구간 + 상승 장악형 또는 망치형 (구조마다 먼저 나온 신호 하나)
  B  A + 일봉 종가 > 200일 EMA
  C  4시간봉 2파 구간 + 샛별형
  D  C + 4시간봉 종가 > 200EMA
  A+C 두 전략을 한 계좌에서
계좌: 거래마다 손절 시 계좌의 2% (또는 1%) 를 잃도록 수량, 열린 포지션 합계 3배 이하, 해마다 1,000만원에서 새로 시작
비교: 같은 해 4시간봉 스윙 시스템 (거래당 0.5%, 백테스트 결과)

사용:  python -m smc.elliott_yearly
"""
from __future__ import annotations

import pandas as pd

from .dd_brake import curve
from .elliott_candle import TFS, run

CAP = 10_000_000
YEARS = (2023, 2024, 2025, 2026)
SWING = {2023: "+13%", 2024: "+10%", 2025: "+28%", 2026: "+12%"}     # smc.system 스윙만(롱+숏), 거래당 0.5%, 2026은 9월까지


def pick(R, tf, kinds, trend):
    g = R[(R.tf == tf) & (R.side > 0) & (R.stop == "1파 시작점") & R.kind.isin(kinds)]
    if trend:
        g = g[g.trend]
    return g.sort_values("time").groupby("struct", as_index=False).first()   # 구조 하나에 한 번


def year_stats(g, y, risk):
    z = g[(g.time >= f"{y}-01-01") & (g.time < f"{y + 1}-01-01")]
    if not len(z):
        return 0, float("nan"), 0.0
    rows = z.rename(columns={"time": "entry"}).assign(risk=risk)[["entry", "exit", "r", "risk", "stop_pct"]]
    cv, _ = curve(rows, start=CAP, max_lev=3.0)
    return len(z), (z.ret > 0).mean(), cv.iloc[-1] / CAP - 1


def main():
    R = pd.concat([run(tf, k) for tf, k in TFS.items()], ignore_index=True)
    S = {
        "A 일봉 장악형·망치형": pick(R, "1D", ["상승 장악형", "망치형"], False),
        "B A + 200일 EMA 위": pick(R, "1D", ["상승 장악형", "망치형"], True),
        "C 4시간 샛별형": pick(R, "4h", ["샛별형"], False),
        "D C + 4시간 200EMA 위": pick(R, "4h", ["샛별형"], True),
    }
    S["A+C 함께"] = pd.concat([S["A 일봉 장악형·망치형"], S["C 4시간 샛별형"]], ignore_index=True)
    for risk in (0.02, 0.01):
        print(f"\n■ 손절 시 계좌의 {risk*100:.0f}% ({CAP*risk:,.0f}원) 잃는 수량 · 시작 1,000만원 · 롱만")
        print(f"  {'전략':20} | " + " | ".join(f"{y}년 (거래·승률·수익률)".center(26) for y in YEARS) + " | 4년 합계")
        for name, g in S.items():
            cells, tot, n_all, w_all = [], 1.0, 0, []
            for y in YEARS:
                n, w, ret = year_stats(g, y, risk)
                tot *= 1 + ret
                n_all += n
                if n:
                    w_all.append(w * n)
                cells.append(f"{n:3}건 {w*100 if n else 0:3.0f}% {ret*100:+6.1f}% ({ret*CAP:+,.0f}원)" if n else f"{'거래 없음':^26}")
            print(f"  {name:20} | " + " | ".join(f"{c:26}" for c in cells) +
                  f" | {n_all}건 승률 {sum(w_all)/max(n_all,1)*100:.0f}% · 1,000만원 → {CAP*tot:,.0f}원 ({(tot-1)*100:+.1f}%)")
    print("\n■ 참고: 4시간봉 스윙 시스템 (거래당 0.5%) " + " · ".join(f"{y} {v}" for y, v in SWING.items()))


if __name__ == "__main__":
    main()
