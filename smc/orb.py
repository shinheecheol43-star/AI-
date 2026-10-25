"""미국장 시가 범위 돌파 데이트레이딩 (작게 지고, 이기는 거래는 길게) + 보완 옵션.

기본 규칙 (daytrade2.py 시가범위 F0 과 같음)
  매매하는 날 : 4시간봉 200EMA 위 + 전날 일봉 국면 ≥ +1 (숏 옵션: 200EMA 아래 + 국면 ≤ −1)
  진입        : 미국장 개장 후 첫 30분 고가를 15분봉 종가로 돌파 → 시장가 (숏은 저가 이탈)
  손절        : 15분봉 ATR × 2, 추적 손절 1시간봉 ATR × 3
  미국장 마감  : 손실 중이면 청산, 수익 중이면 손절을 본절로 올리고 보유
  자금        : 거래당 리스크 risk, 레버리지 합계 3배 이하, 그날 실현 손실 −1% 이면 그날 신규 진입 중지
보완 옵션
  pyramid : 첫 진입가 + 1시간봉 ATR × 1 에 닿으면 같은 수량을 한 번 추가 (손절선은 그대로)
  reentry : 그날 거래가 끝난 뒤 시가 범위를 다시 돌파하면 한 번 더 진입
  short   : 하락 국면에서 숏도 매매

사용:  python -m smc.orb
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .daytrade import SPLIT, prepare, session_columns
from .daytrade2 import extra

TAKER = 0.00055
DAY_LOSS, MAX_LEV = 0.01, 3.0
END = pd.Timestamp("2026-10-01", tz="UTC")


def run(risk=0.005, pyramid=False, reentry=False, short=False, syms=("BTC", "ETH"), start=1000.0,
        long=True, short_score=-1, short_close_at_us=False, short_any=False) -> dict:
    D = {s: prepare(s).join(extra(s)) for s in syms}
    idx = D[syms[0]].index
    for s in syms[1:]:
        idx = idx.intersection(D[s].index)
    idx = idx[idx >= "2018-03-15"]
    S = {k: v.to_numpy() for k, v in session_columns(idx).items()}
    cols = ("open", "high", "low", "close", "atr", "atr1h", "trend4", "score", "fund_evt")
    A = {s: {k: D[s][k].reindex(idx).to_numpy() for k in cols} for s in syms}
    pos = {s: None for s in syms}
    bal, day, day_start, day_pnl = start, None, start, 0.0
    or_hi, or_lo = {s: np.nan for s in syms}, {s: np.nan for s in syms}
    n_today = {s: 0 for s in syms}
    trades, curve = [], []

    def close(s, p, px, t):
        nonlocal bal, day_pnl
        side = p["side"]
        pnl = sum(q * (side * (px - e) - fee * e - TAKER * px) for q, e, fee in p["legs"]) - p["fund"]
        bal += pnl
        day_pnl += pnl
        trades.append({"sym": s, "side": side, "entry_time": p["time"], "exit_time": idx[t], "pnl": pnl,
                       "r": pnl / p["risk_usd"], "overnight": p["overnight"], "added": len(p["legs"]) > 1})
        curve.append((idx[t], bal))
        pos[s] = None

    for t in range(1, len(idx)):
        if S["tday"][t] != day:
            day, day_start, day_pnl = S["tday"][t], bal, 0.0
            n_today = {s: 0 for s in syms}
        for s in syms:
            a = A[s]
            o, h, l, c = a["open"][t], a["high"][t], a["low"][t], a["close"][t]
            if np.isnan(c):
                continue
            p = pos[s]
            if p is not None:
                side = p["side"]
                qty = sum(q for q, _, _ in p["legs"])
                p["fund"] += side * a["fund_evt"][t] * qty * o
                # 불타기: 손절 확인 전에 추가가 닿았는지 (보수적으로 추가 후 손절도 확인)
                if pyramid and len(p["legs"]) == 1 and ((h >= p["add_px"]) if side > 0 else (l <= p["add_px"])):
                    px = max(o, p["add_px"]) if side > 0 else min(o, p["add_px"])
                    expo = sum(sum(q for q, _, _ in r["legs"]) * A[r["sym"]]["close"][t] for r in pos.values() if r)
                    q2 = min(p["legs"][0][0], max(0.0, (MAX_LEV * bal - expo) / px))
                    if q2 > 0:
                        p["legs"].append((q2, px, TAKER))
                stop = p["stop"]
                if (o <= stop) if side > 0 else (o >= stop):
                    close(s, p, o, t)
                elif (l <= stop) if side > 0 else (h >= stop):
                    close(s, p, stop, t)
                else:
                    p["ext"] = max(p["ext"], h) if side > 0 else min(p["ext"], l)
                    if np.isfinite(a["atr1h"][t]):
                        new = p["ext"] - side * 3 * a["atr1h"][t]
                        p["stop"] = max(p["stop"], new) if side > 0 else min(p["stop"], new)
                    if S["us_close_bar"][t]:
                        legs = p["legs"]
                        avg = sum(q * e for q, e, _ in legs) / sum(q for q, _, _ in legs)
                        if side * (c - avg) > 0 and not (side < 0 and short_close_at_us):
                            p["stop"] = max(p["stop"], avg) if side > 0 else min(p["stop"], avg)
                            p["overnight"] = True
                        else:
                            close(s, p, c, t)
            if S["us_open_bar"][t]:
                or_hi[s], or_lo[s] = h, l
            elif S["us_or_end"][t]:
                or_hi[s], or_lo[s] = max(or_hi[s], h), min(or_lo[s], l)
            # 신규 진입
            if day_pnl <= -DAY_LOSS * day_start or pos[s] is not None or not S["entry_ok"][t] or not S["after_or"][t]:
                continue
            if n_today[s] >= (2 if reentry else 1) or np.isnan(or_hi[s]):
                continue
            up = long and a["trend4"][t] > 0 and a["score"][t] >= 1
            down = short and (short_any or (a["trend4"][t] < 0 and a["score"][t] <= short_score))
            fresh = n_today[s] == 0 or (a["close"][t - 1] <= or_hi[s] if up else a["close"][t - 1] >= or_lo[s])
            side = 1 if (up and c > or_hi[s]) else (-1 if (down and c < or_lo[s]) else 0)
            if side < 0 and n_today[s] > 0 and not reentry:
                continue
            if side == 0 or not fresh:
                continue
            risk_px = 2 * a["atr"][t]
            q = bal * risk / risk_px
            expo = sum(sum(x for x, _, _ in r["legs"]) * A[r["sym"]]["close"][t] for r in pos.values() if r)
            q = min(q, max(0.0, (MAX_LEV * bal - expo) / c))
            if q <= 0:
                continue
            n_today[s] += 1
            add_px = c + side * a["atr1h"][t] if np.isfinite(a["atr1h"][t]) else np.inf * side
            pos[s] = {"sym": s, "side": side, "legs": [(q, c, TAKER)], "stop": c - side * risk_px, "ext": c,
                      "risk_usd": q * risk_px, "time": idx[t], "fund": 0.0, "overnight": False, "add_px": add_px}
    return {"trades": pd.DataFrame(trades),
            "curve": pd.Series([b for _, b in curve], index=pd.DatetimeIndex([t for t, _ in curve]), dtype=float)}


def report(res: dict, start=1000.0) -> dict:
    cv, tr = res["curve"], res["trades"]
    lo = pd.Timestamp("2018-03-15", tz="UTC")
    full = pd.concat([pd.Series([start], index=[lo]), cv])

    def seg(a, b):
        c = full[(full.index >= a) & (full.index < b)]
        b0 = full[full.index < a].iloc[-1] if (full.index < a).any() else start
        yrs = (b - a).days / 365.25
        allc = pd.concat([pd.Series([b0], index=[a]), c])
        return (c.iloc[-1] / b0) ** (1 / yrs) - 1, (allc / allc.cummax() - 1).min()

    years, prev = {}, start
    for y in range(2018, 2027):
        c = cv[cv.index.year == y]
        if len(c):
            years[y] = c.iloc[-1] / prev - 1
            prev = c.iloc[-1]
        else:
            years[y] = 0.0
    return {"full": seg(lo, END), "design": seg(lo, SPLIT), "test": seg(SPLIT, END), "years": years,
            "final": cv.iloc[-1], "per_year": len(tr) / ((END - lo).days / 365.25), "win": (tr.r > 0).mean()}


CONFIGS = {
    "기본 (리스크 0.5%)": {},
    "① 리스크 1%": {"risk": 0.01},
    "② 불타기": {"pyramid": True},
    "③ 재진입 1회": {"reentry": True},
    "④ 하락장 숏": {"short": True},
    "②+④ 불타기 + 숏": {"pyramid": True, "short": True},
    "②+③+④ 모두": {"pyramid": True, "reentry": True, "short": True},
    "②+④, 리스크 1%": {"pyramid": True, "short": True, "risk": 0.01},
}


def main():
    print(f"{'구성':20} | {'전체 연평균':>9} {'최대낙폭':>8} | {'설계 연평균':>9} | {'검증 연평균':>9} {'검증낙폭':>8} | {'$1,000→':>9} 연거래 승률")
    rows = {}
    for name, kw in CONFIGS.items():
        r = report(run(**kw))
        rows[name] = r
        print(f"{name:20} | {r['full'][0]*100:+8.1f}% {r['full'][1]*100:7.1f}% | {r['design'][0]*100:+8.1f}% |"
              f" {r['test'][0]*100:+8.1f}% {r['test'][1]*100:7.1f}% | ${r['final']:>8,.0f} {r['per_year']:4.0f}회 {r['win']*100:4.1f}%")
    print("\n연도별 수익률")
    print(f"{'구성':20} " + " ".join(f"{y:>7}" for y in range(2018, 2027)))
    for name, r in rows.items():
        print(f"{name:20} " + " ".join(f"{r['years'][y]*100:+6.1f}%" for y in range(2018, 2027)))


if __name__ == "__main__":
    main()
