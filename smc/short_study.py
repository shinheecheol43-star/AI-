"""숏을 언제 잡는 게 좋은가: 숏 전용 상황 5가지 × 청산 2가지 (4시간봉, BTC·ETH).

상황 (4시간봉 종가 기준, 일봉·펀딩비는 전날까지 확정 값)
  S1 하락 추세 이탈 : 종가가 직전 20봉 저점을 처음 이탈
  S2 하락장 반등 실패 : 일봉 국면 ≤ −1, 종가 < 4h 200EMA, 고가가 4h 50EMA에 닿고 50EMA 아래에서 음봉 마감
  S3 롱 과열(펀딩비)  : 전날 펀딩비가 최근 90일 중 상위 10%, 종가가 4h 20EMA를 처음 하향 이탈 (2019-10 이후)
  S4 급등 후 반전     : 전날 일봉 RSI ≥ 75, 종가가 직전 4h 봉 저가 아래로 마감
  S5 일봉 지지선 이탈 : 가장 최근 확정된 일봉 스윙 저점(좌우 5일)을 종가로 처음 이탈
청산
  고정 : 손절 진입가 + ATR(4h) × 2, 익절 손절폭 × 1.5 (지정가)
  추적 : 같은 손절, 최저가 + ATR × 3 추적, 최대 120봉
같은 상황·같은 코인은 포지션이 끝나기 전에 새로 진입하지 않는다.
비용: 진입·손절 시장가 0.055%, 익절 지정가 0.02%, 실제 펀딩비(숏은 양수 펀딩일 때 받음).

사용:  python -m smc.short_study
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import fetch_binance_archive, resample
from .detectors import pivots
from .regime import DEFAULT_FUNDING, fetch_funding, indicators as daily_indicators
from .research import MAKER, TAKER, rsi, tf_features
from .research_report import SPLIT

SETUPS = ["S1 하락 추세 이탈", "S2 하락장 반등 실패", "S3 롱 과열(펀딩비)", "S4 급등 후 반전", "S5 일봉 지지선 이탈"]


def context(sym: str) -> dict:
    h1 = fetch_binance_archive(sym + "USDT", "1h")
    d4 = resample(h1, "4h")
    dD = resample(h1, "1D")
    f = tf_features(d4)
    daily = daily_indicators(dD.set_index("time"))
    day = d4.time.dt.floor("D")
    score = daily.score.shift(1).reindex(day).to_numpy()
    drsi = rsi(dD.set_index("time").close).shift(1).reindex(day).to_numpy()
    fund = fetch_funding(sym + "USDT")
    frank = fund.rolling(90, min_periods=60).rank(pct=True).shift(1).reindex(day).to_numpy()
    # 일봉 스윙 저점: 확정(피벗 + 5일) 이후부터 쓸 수 있음
    _, lows = pivots(dD, 5)
    sup = pd.Series(np.nan, index=dD.time)
    for pj, pc, lvl in lows:
        if pc + 1 < len(dD):
            sup.iloc[pc + 1] = lvl                      # 확정된 다음 날부터
    sup = sup.ffill().reindex(day).to_numpy()
    days_all = pd.DatetimeIndex(day.unique())
    fser = fund.reindex(days_all).fillna(DEFAULT_FUNDING)
    return {"df": d4, "o": d4.open.to_numpy(), "h": d4.high.to_numpy(), "l": d4.low.to_numpy(), "c": d4.close.to_numpy(),
            "atr": f.atr.to_numpy(), "e20": f.ema20.to_numpy(), "e50": f.ema50.to_numpy(), "e200": f.ema200.to_numpy(),
            "score": score, "drsi": drsi, "frank": frank, "sup": sup,
            "ll20": d4.low.rolling(20).min().shift(1).to_numpy(),
            "fcum": np.r_[0.0, fser.cumsum().to_numpy()], "didx": pd.Index(fser.index).get_indexer(day) + 1}


def signal(X: dict, i: int, setup: str) -> bool:
    o, h, l, c = X["o"], X["h"], X["l"], X["c"]
    if setup == SETUPS[0]:
        return c[i] < X["ll20"][i] and c[i - 1] >= X["ll20"][i - 1]
    if setup == SETUPS[1]:
        return (X["score"][i] <= -1 and c[i] < X["e200"][i] and h[i] >= X["e50"][i] and c[i] < X["e50"][i] and c[i] < o[i])
    if setup == SETUPS[2]:
        return (X["df"].time.iat[i] >= pd.Timestamp("2019-10-01", tz="UTC") and X["frank"][i] >= 0.9
                and c[i] < X["e20"][i] and c[i - 1] >= X["e20"][i - 1])
    if setup == SETUPS[3]:
        return X["drsi"][i] >= 75 and c[i] < l[i - 1]
    if setup == SETUPS[4]:
        s = X["sup"][i]
        return np.isfinite(s) and c[i] < s and c[i - 1] >= s
    return False


def short_trade(X: dict, i: int, mode: str) -> dict:
    o, h, l, c, atr = X["o"], X["h"], X["l"], X["c"], X["atr"]
    n, p0 = len(c), c[i]
    risk = 2 * atr[i]
    stop, tp = p0 + risk, p0 - 1.5 * risk
    ext, ex, kind, ei = p0, None, None, None
    for t in range(i + 1, min(n, i + 121)):
        if o[t] >= stop:
            ex, kind, ei = o[t], "sl", t
            break
        if h[t] >= stop:
            ex, kind, ei = stop, "sl", t
            break
        if mode == "고정" and l[t] <= tp:
            ex, kind, ei = min(o[t], tp), "tp", t
            break
        if mode == "추적":
            ext = min(ext, l[t])
            stop = min(stop, ext + 3 * atr[t])
    if ex is None:
        ei = min(n - 1, i + 120)
        ex, kind = c[ei], "time"
    fund = (X["fcum"][X["didx"][ei]] - X["fcum"][X["didx"][i]]) * p0       # 양수면 숏이 받음
    pnl = (p0 - ex) - TAKER * p0 - (MAKER if kind == "tp" else TAKER) * ex + fund
    return {"r": pnl / risk, "exit_t": ei, "stop_pct": risk / p0}


def build() -> pd.DataFrame:
    rows = []
    for sym in ("BTC", "ETH"):
        X = context(sym)
        n = len(X["c"])
        for setup in SETUPS:
            for mode in ("고정", "추적"):
                busy = -1
                for i in range(201, n - 1):
                    if i <= busy or not np.isfinite(X["atr"][i]) or not signal(X, i, setup):
                        continue
                    r = short_trade(X, i, mode)
                    busy = r["exit_t"]
                    rows.append({"sym": sym, "setup": setup, "mode": mode, "entry": X["df"].time.iat[i] + pd.Timedelta("4h"),
                                 "exit": X["df"].time.iat[r["exit_t"]] + pd.Timedelta("4h"), "score": X["score"][i], **r})
    return pd.DataFrame(rows)


def cell(y: pd.DataFrame) -> str:
    return f"{y.r.mean():+.2f}({len(y)})" if len(y) >= 10 else f"  - ({len(y)})"


def main():
    x = build()
    x.to_pickle("reports/short_study.pkl")
    print(f"{'상황':16} {'청산':4} {'국면':8} | {'설계 BTC':>11} {'설계 ETH':>11} | {'검증 BTC':>11} {'검증 ETH':>11} | 전체 승률 평균R")
    for setup in SETUPS:
        for mode in ("고정", "추적"):
            for reg, m in (("전체", x.score == x.score), ("하락국면", x.score <= -1), ("상승국면", x.score >= 1)):
                y = x[(x.setup == setup) & (x["mode"] == mode) & m]
                if y.empty:
                    continue
                tr, te = y[y.entry < SPLIT], y[y.entry >= SPLIT]
                print(f"{setup:16} {mode:4} {reg:8} | {cell(tr[tr.sym=='BTC']):>11} {cell(tr[tr.sym=='ETH']):>11} |"
                      f" {cell(te[te.sym=='BTC']):>11} {cell(te[te.sym=='ETH']):>11} | {(y.r>0).mean()*100:4.0f}% {y.r.mean():+.2f}")
        print()


if __name__ == "__main__":
    main()
