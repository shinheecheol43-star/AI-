"""CHoCH → OB → FVG 리테스트: 손절폭(진입가 → OB 꼬리 손절, 가격 %) 상한을 두면 나아지는가.

규칙은 결과를 보기 전에 정했다.
  손절폭 상한: 없음 · 3% · 2% · 1.5% · 1%  (넘으면 진입하지 않음)
  규칙: 필터 없음 / 사용자 조건(OB 꼬리 ≥ 50% + FVG ≥ ATR×1) / + 4시간 50EMA 같은 방향 / + 4시간 200EMA 같은 방향
  진입·청산은 smc.choch_loss 기본 (FVG 윗변 지정가, OB 꼬리 − 0.1 ATR 손절, 추적 3ATR), 15분~4시간봉, 롱·숏
채점: BTC·ETH ~2021 / BTC·ETH 2022~ / SOL 전체 (평균 R) 와
      2025년 BTC·ETH 시작 $1,000 계좌 (매 거래 레버리지 3배 고정 / 거래당 위험 1%, 합계 레버리지 3배 이하)

사용:  python -m smc.choch_stopcap
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from itertools import product

import pandas as pd

from .bos_choch import arrays
from .choch_loss import TFS, run_trade, trade_list
from .choch_ob_fvg import HOLD
from .daytrade import SPLIT
from .dd_brake import curve

CAPS = (None, 0.03, 0.02, 0.015, 0.01)


def build(cfg):
    return trade_list(*cfg)


def trades(sub: pd.DataFrame) -> pd.DataFrame:
    """코인·봉·방향마다 한 번에 한 거래로 진행한 거래 목록 (진입·청산 시각, R, 손절폭%)."""
    out = []
    for (sym, tf, side), g in sub.groupby(["sym", "tf", "side"]):
        idx, o, h, l, c, atr, _ = arrays(sym, tf, side)
        hold, busy = HOLD[tf] * 3, -1
        for t in g.sort_values("e").itertuples():
            if t.e <= busy:
                continue
            r, ex, _, _ = run_trade(o, h, l, c, atr, int(t.e), t.px, t.stop, hold, {})
            busy = ex
            out.append(dict(sym=sym, tf=tf, side=side, entry=idx[int(t.e)], exit=idx[ex] + pd.Timedelta(tf), r=r,
                             stop_pct=(t.px - t.stop) / abs(t.px)))
    return pd.DataFrame(out, columns=["sym", "tf", "side", "entry", "exit", "r", "stop_pct"])


def account(x: pd.DataFrame, risk) -> tuple[float, float, float]:
    if not len(x):
        return 1000.0, 0.0, 0.0
    rk = 3 * x.stop_pct if risk == "3배" else risk
    cv, _ = curve(x.assign(risk=rk)[["entry", "exit", "r", "risk", "stop_pct"]])
    cv = pd.concat([pd.Series([1000.0], index=[pd.Timestamp("2025-01-01", tz="UTC")]), cv])
    worst = (3 * x.r * x.stop_pct).min() if risk == "3배" else (x.r * risk).min()
    return cv.iloc[-1], (cv / cv.cummax() - 1).min(), worst


def main():
    with ProcessPoolExecutor(4) as pool:
        T = pd.DataFrame([r for rows in pool.map(build, list(product(("BTC", "ETH", "SOL"), TFS, (1, -1)))) for r in rows])
    T["test"] = T.time >= SPLIT
    T["stop_pct"] = (T.px - T.stop) / T.px.abs()
    user = (T.ob_wick >= 0.5) & (T.fvg_size >= 1.0)
    rules = {"필터 없음": pd.Series(True, index=T.index), "사용자 조건": user,
             "+ 4시간 50EMA": user & (T.htf > 0.5), "+ 4시간 200EMA": user & (T.htf200 > 0.5)}
    parts = {"BTC·ETH ~2021": T.sym.isin(["BTC", "ETH"]) & ~T.test, "BTC·ETH 2022~": T.sym.isin(["BTC", "ETH"]) & T.test,
             "SOL 전체": T.sym == "SOL"}
    y25 = T.sym.isin(["BTC", "ETH"]) & (T.time >= "2025-01-01") & (T.time < "2026-01-01")
    print("손절폭 상한 (진입가 → OB 꼬리 손절, 가격 %) · R 은 비용 뺀 값\n")
    print("신호의 손절폭 분포 (BTC·ETH, 중간값): " + " · ".join(f"{tf} {T[T.tf == tf].stop_pct.median()*100:.2f}%" for tf in TFS) + "\n")
    for rname, rm in rules.items():
        print(f"■ {rname}")
        print(f"  {'상한':6} | " + " | ".join(f"{p:^24}" for p in parts) + " | 2025 BTC·ETH $1,000: 레버리지 3배 고정 / 위험 1%")
        for cap in CAPS:
            m = rm & ((T.stop_pct <= cap) if cap else True)
            cells = []
            for pm in parts.values():
                x = trades(T[m & pm])
                cells.append(f"{len(x):5}건 {x.r.mean():+.3f}R 승률 {(x.r > 0).mean()*100:3.0f}%" if len(x) else f"{'거래 없음':^24}")
            x25 = trades(T[m & y25])
            a3, d3, w3 = account(x25, "3배")
            a1, d1, w1 = account(x25, 0.01)
            label = "없음" if cap is None else f"{cap*100:g}%"
            print(f"  {label:6} | " + " | ".join(f"{c:24}" for c in cells) +
                  f" | {len(x25):4}건 3배 ${a3:,.0f} (낙폭 {d3*100:.0f}%, 최대 1회 {w3*100:.1f}%) · 1% ${a1:,.0f} (낙폭 {d1*100:.0f}%)")
        print()


if __name__ == "__main__":
    main()
