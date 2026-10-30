"""주식(ETF) 일봉으로 스윙 규칙 검증 (야후 파이낸스 데이터). 코인용 4시간봉 규칙을 일봉으로 옮긴 것.

전략 (일봉 종가 판단, 다음 날 시가가 아니라 그날 종가에 진입)
  스윙 롱 : 종가가 직전 20일 고가를 처음 돌파 + 근거 4개 중 3개 이상
            (종가 > 200일 EMA, 국면 점수 +3, RSI(14) > 60, 20일 EMA 이격 > ATR × 1)
  숏 S5   : 종가가 가장 최근 확정된 스윙 저점(좌우 5일)을 처음 이탈
  숏 S2   : 국면 ≤ −1, 종가 < 200일 EMA, 고가가 50일 EMA 에 닿고 50일 EMA 아래 음봉 마감
청산: 손절 ATR(14) × 2, 추적 손절 최고가(숏은 최저가) ∓ ATR × 3, 최대 60일. 갭으로 손절선을 넘으면 시가 체결.
비용: 진입·청산 각 0.1% (수수료 + 슬리피지). 차입·펀딩 비용은 넣지 않음.
설계 구간 ~2019, 검증 구간 2020~.

사용:  python -m smc.stock_swing SOXL
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from .detectors import pivots
from .research import rsi, tf_features

COST, STOP_ATR, TRAIL_ATR, HOLD = 0.001, 2.0, 3.0, 60
SPLIT = pd.Timestamp("2020-01-01", tz="UTC")


def fetch(sym: str) -> pd.DataFrame:
    import requests

    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                     params={"period1": 0, "period2": 4102444800, "interval": "1d"}, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    j = r.json()["chart"]["result"][0]
    q = j["indicators"]["quote"][0]
    d = pd.DataFrame({"time": pd.to_datetime(j["timestamp"], unit="s", utc=True).normalize(),
                      **{k: q[k] for k in ("open", "high", "low", "close", "volume")}})
    return d.dropna().reset_index(drop=True)


def context(d: pd.DataFrame) -> dict:
    f = tf_features(d)
    c = d.close
    sma50, sma200 = c.rolling(50).mean(), c.rolling(200).mean()
    score = (np.sign(c - sma200) + np.sign(sma50 - sma200) + np.sign(c / c.shift(90) - 1)).shift(1)   # 전날까지
    _, lows = pivots(d, 5)
    sup = pd.Series(np.nan, index=d.index)
    for _, pc, lvl in lows:
        if pc + 1 < len(d):
            sup.iloc[pc + 1] = lvl
    return {"d": d, "o": d.open.to_numpy(), "h": d.high.to_numpy(), "l": d.low.to_numpy(), "c": c.to_numpy(),
            "atr": f.atr.to_numpy(), "e20": f.ema20.to_numpy(), "e50": f.ema50.to_numpy(), "e200": f.ema200.to_numpy(),
            "rsi": rsi(c).to_numpy(), "score": score.to_numpy(), "sup": sup.ffill().to_numpy(),
            "hh": d.high.rolling(20).max().shift(1).to_numpy()}


def evidence(X: dict, i: int) -> list[bool]:
    c = X["c"]
    return [bool(c[i] > X["e200"][i]), bool(X["score"][i] >= 3), bool(X["rsi"][i] > 60),
            bool((c[i] - X["e20"][i]) / X["atr"][i] > 1.0)]


def signal(X: dict, i: int, name: str) -> bool:
    o, h, c = X["o"], X["h"], X["c"]
    if name == "스윙 롱":
        return c[i] > X["hh"][i] and c[i - 1] <= X["hh"][i - 1] and sum(evidence(X, i)) >= 3
    if name == "숏 S5":
        s = X["sup"]
        return np.isfinite(s[i]) and c[i] < s[i] and c[i - 1] >= s[i - 1]
    if name == "숏 S2":
        return X["score"][i] <= -1 and c[i] < X["e200"][i] and h[i] >= X["e50"][i] and c[i] < X["e50"][i] and c[i] < o[i]
    return False


SIDES = {"스윙 롱": 1, "숏 S5": -1, "숏 S2": -1}


def trade(X: dict, i: int, side: int) -> dict:
    o, h, l, c, atr = X["o"], X["h"], X["l"], X["c"], X["atr"]
    n, p0 = len(c), c[i]
    stop = p0 - side * STOP_ATR * atr[i]
    one_r, ext, ex, ei = abs(p0 - stop), p0, None, None
    for t in range(i + 1, min(n, i + HOLD + 1)):
        if (o[t] <= stop) if side > 0 else (o[t] >= stop):
            ex, ei = o[t], t
            break
        if (l[t] <= stop) if side > 0 else (h[t] >= stop):
            ex, ei = stop, t
            break
        ext = max(ext, h[t]) if side > 0 else min(ext, l[t])
        new = ext - side * TRAIL_ATR * atr[t]
        stop = max(stop, new) if side > 0 else min(stop, new)
    still = ex is None and i + HOLD >= n - 1
    if ex is None:
        ei = min(n - 1, i + HOLD)
        ex = c[ei]
    r = (side * (ex - p0) - COST * (p0 + ex)) / one_r
    return {"r": r, "exit_t": ei, "stop_pct": one_r / p0, "open": still, "stop": stop, "p0": p0,
            "mfe": side * (ext - p0) / one_r}


def trades(X: dict) -> pd.DataFrame:
    rows, n = [], len(X["c"])
    for name, side in SIDES.items():
        busy = -1
        for i in range(201, n):
            if i <= busy or not np.isfinite(X["atr"][i]) or not signal(X, i, name):
                continue
            t = trade(X, i, side)
            busy = t["exit_t"] if not t["open"] else n
            rows.append({"src": name, "side": side, "entry": X["d"].time.iat[i], "exit": X["d"].time.iat[t["exit_t"]], **t})
    return pd.DataFrame(rows)


def equity(x: pd.DataFrame, risk=0.01, start=1000.0) -> pd.Series:
    bal, op, ev = start, [], []
    for _, t in x.sort_values("entry").iterrows():
        for p in sorted([p for p in op if p["exit"] <= t.entry], key=lambda p: p["exit"]):
            bal += p["pnl"]
            op.remove(p)
            ev.append((p["exit"], bal))
        n = min(bal * risk / t.stop_pct, 1.0 * bal - sum(p["notional"] for p in op))   # 레버리지 없이 (현물 기준)
        if n <= 0:
            continue
        op.append({"exit": t.exit, "pnl": n * t.stop_pct * t.r, "notional": n})
    for p in sorted(op, key=lambda p: p["exit"]):
        bal += p["pnl"]
        ev.append((p["exit"], bal))
    return pd.Series([b for _, b in ev], index=pd.DatetimeIndex([e for e, _ in ev])).sort_index()


def summary(cv: pd.Series, lo, hi, start=1000.0):
    c = cv[(cv.index >= lo) & (cv.index < hi)]
    b0 = cv[cv.index < lo].iloc[-1] if (cv.index < lo).any() else start
    allc = pd.concat([pd.Series([b0], index=[lo]), c])
    yrs = (hi - lo).days / 365.25
    return (c.iloc[-1] / b0) ** (1 / yrs) - 1 if len(c) else 0.0, (allc / allc.cummax() - 1).min()


def main(sym: str = "SOXL"):
    d = fetch(sym)
    X = context(d)
    x = trades(X)
    done = x[~x.open]
    lo, hi = d.time.iloc[201], d.time.iloc[-1]
    print(f"{sym} 일봉 {d.time.iloc[0]:%Y-%m-%d} ~ {d.time.iloc[-1]:%Y-%m-%d} ({len(d)}일)\n")
    print(f"{'전략':6} {'거래':>4} {'연':>4} {'승률':>6} {'평균R':>7} {'설계R':>7} {'검증R':>7} {'평균익':>6} {'평균손':>6} {'1R도달':>6} {'2R도달':>6}")
    yrs = (hi - lo).days / 365.25
    for name in SIDES:
        y = done[done.src == name]
        if y.empty:
            continue
        print(f"{name:6} {len(y):4} {len(y)/yrs:4.1f} {(y.r>0).mean()*100:5.0f}% {y.r.mean():+.3f} {y[y.entry<SPLIT].r.mean():+.3f}"
              f" {y[y.entry>=SPLIT].r.mean():+.3f} {y[y.r>0].r.mean():+6.2f} {y[y.r<=0].r.mean():+6.2f}"
              f" {(y.mfe>=1).mean()*100:5.0f}% {(y.mfe>=2).mean()*100:5.0f}%")
    print("\n■ 계좌 ($1,000, 거래당 1% 리스크, 레버리지 없음)")
    for lab, srcs in (("롱만", ["스윙 롱"]), ("숏만", ["숏 S5", "숏 S2"]), ("롱 + 숏", list(SIDES))):
        cv = equity(done[done.src.isin(srcs)])
        if cv.empty:
            continue
        f, a, b = summary(cv, lo, hi), summary(cv, lo, SPLIT), summary(cv, SPLIT, hi)
        print(f"{lab:8} 전체 {f[0]*100:+6.1f}%/년 낙폭 {f[1]*100:6.1f}% | 설계 {a[0]*100:+6.1f}% | 검증 {b[0]*100:+6.1f}% 낙폭 {b[1]*100:6.1f}% | ${cv.iloc[-1]:,.0f}")
    print("\n■ 연도별 R 합")
    print(done.assign(y=done.entry.dt.year).groupby(["y", "src"]).r.sum().unstack().round(1).fillna(0).to_string())
    i = len(d) - 1
    print(f"\n■ 지금 ({d.time.iloc[-1]:%Y-%m-%d} 종가 {X['c'][i]:.2f})")
    print(f"  국면 점수(전날 기준) {X['score'][i]:+.0f} · 200일 EMA {X['e200'][i]:.2f} · 50일 EMA {X['e50'][i]:.2f} · 20일 EMA {X['e20'][i]:.2f}"
          f" · RSI {X['rsi'][i]:.0f} · ATR {X['atr'][i]:.2f} ({X['atr'][i]/X['c'][i]*100:.1f}%)")
    print(f"  스윙 롱: 종가 > 20일 고가 {d.high.iloc[-20:].max():.2f} + 근거 {sum(evidence(X, i))}/4 (3개 이상 필요)")
    print(f"  숏 S5: 지지선 {X['sup'][i]:.2f} 첫 이탈 · 숏 S2: 국면 ≤ −1 이고 50일 EMA {X['e50'][i]:.2f} 터치 후 음봉")
    for t in x[x.open].itertuples():
        print(f"  진행 중: {t.src} {t.entry:%Y-%m-%d} @ {t.p0:.2f}, 현재 손절 {t.stop:.2f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "SOXL")
