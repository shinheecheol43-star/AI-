"""데이트레이딩 '손실은 짧게, 수익은 길게' 연구 (미국장 시가 범위 돌파, 15분봉, BTC·ETH 한 계좌).

진입과 사용자 규칙은 orb.py 기본과 같다
  매매하는 날 4시간봉 200EMA 위 + 전날 일봉 국면 ≥ +1, 미국장 첫 30분 고가를 15분봉 종가로 돌파 → 시장가
  미국장 마감에 손실 중이면 청산, 수익 중이면 손절을 본절 이상으로 두고 보유
  거래당 리스크 0.5%, 레버리지 합계 3배 이하, 그날 실현 손실 −1% 이면 그날 신규 진입 중지
바꿔 보는 것 (한 번에 하나씩, 그다음 좋은 것끼리 조합)
  stop_k     : 최초 손절 15분봉 ATR × k                         (기본 2)
  stop_or    : 최초 손절을 시가 범위 중간값에 (ATR × 0.5 ~ 3 사이로 제한)
  time_bars  : 진입 후 n 봉(15분) 지나도 수익이 없으면 그 봉 종가에 청산 (빠른 손절)
  be_r       : +be_r R 에 닿으면 손절을 본절로
  trail_k    : 추적 손절 1시간봉 ATR × k                        (기본 3)
  trail_from : +trail_from R 에 닿은 뒤부터 추적 시작 (그 전에는 최초 손절 유지)
  night_k    : 오버나잇 들어갈 때 손절을 max(본절, 종가 − 1시간봉 ATR × night_k) 로 조임
  max_days   : 오버나잇 n 번 넘기면 다음 미국장 마감에 무조건 청산 (스윙처럼 길어지지 않게)
  above_ph   : 롱은 돌파 종가가 전일(한국 09:00 기준) 고가 위일 때만 (숏은 전일 저가 아래)
  reentry    : 그날 같은 코인 재진입. None = 하루 한 번, "win" = 직전 거래가 수익으로 끝났을 때만, "any" = 손익 무관
               재진입은 종가가 시가 범위 고가 아래로 내려왔다가 다시 돌파할 때 (같은 자리 반복 진입 방지)
  max_entries: 코인당 하루 최대 진입 횟수 (재진입 포함)
  day_stop   : "start" = 그날 시작 잔고 대비 −1% 면 중단, "peak" = 그날 최고 손익에서 1% 반납하면 중단

사용:  python -m smc.daytrade3
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from .daytrade import SPLIT, prepare, session_columns
from .daytrade2 import extra

TAKER = 0.00055
DAY_LOSS, MAX_LEV = 0.01, 3.0
LO, END = pd.Timestamp("2018-03-15", tz="UTC"), pd.Timestamp("2026-10-01", tz="UTC")


def run(risk=0.005, stop_k=2.0, stop_or=False, time_bars=None, be_r=None, trail_k=3.0, trail_from=None,
        night_k=None, max_days=None, above_ph=False, reentry=None, max_entries=99, day_stop="start", short=False, long=True, syms=("BTC", "ETH"), start=1000.0) -> dict:
    D = {s: prepare(s).join(extra(s)) for s in syms}
    idx = D[syms[0]].index
    for s in syms[1:]:
        idx = idx.union(D[s].index)          # 상장 시기가 다른 코인도 (없는 구간은 건너뜀)
    idx = idx[idx >= LO]
    S = {k: v.to_numpy() for k, v in session_columns(idx).items()}
    cols = ("open", "high", "low", "close", "atr", "atr1h", "trend4", "score", "fund_evt", "prev_high")
    A = {s: {k: D[s][k].reindex(idx).to_numpy() for k in cols} for s in syms}
    for s in syms:
        A[s]["prev_low"] = D[s].low.groupby(D[s].index.floor("D")).transform("min").groupby(
            D[s].index.floor("D")).first().shift(1).reindex(idx.floor("D")).to_numpy()
    pos = {s: None for s in syms}
    bal, day, day_start, day_pnl = start, None, start, 0.0
    or_hi, or_lo = {s: np.nan for s in syms}, {s: np.nan for s in syms}
    n_today, last_win = {s: 0 for s in syms}, {s: False for s in syms}
    day_peak = 0.0
    trades, curve = [], []

    def close(s, p, px, t, why):
        nonlocal bal, day_pnl, day_peak
        side = p["side"]
        pnl = p["qty"] * (side * (px - p["entry"]) - TAKER * (p["entry"] + px)) - p["fund"]
        bal += pnl
        day_pnl += pnl
        day_peak = max(day_peak, day_pnl)
        last_win[s] = pnl > 0
        trades.append({"sym": s, "side": side, "entry_time": p["time"], "exit_time": idx[t], "pnl": pnl,
                       "r": pnl / p["risk_usd"], "nth": p["nth"], "stop_pct": p["risk_px"] / p["entry"], "mfe": p["mfe"], "overnight": p["nights"] > 0, "why": why})
        curve.append((idx[t], bal))
        pos[s] = None

    for t in range(1, len(idx)):
        if S["tday"][t] != day:
            day, day_start, day_pnl, day_peak = S["tday"][t], bal, 0.0, 0.0
            n_today = {s: 0 for s in syms}
        for s in syms:
            a = A[s]
            o, h, l, c = a["open"][t], a["high"][t], a["low"][t], a["close"][t]
            if np.isnan(c):
                continue
            p = pos[s]
            if p is not None:
                side, e, rp = p["side"], p["entry"], p["risk_px"]
                p["fund"] += side * a["fund_evt"][t] * p["qty"] * o
                p["bars"] += 1
                stop = p["stop"]
                if (o <= stop) if side > 0 else (o >= stop):
                    close(s, p, o, t, "손절")
                elif (l <= stop) if side > 0 else (h >= stop):
                    close(s, p, stop, t, "손절")
                else:
                    best = h if side > 0 else l
                    p["ext"] = max(p["ext"], h) if side > 0 else min(p["ext"], l)
                    p["mfe"] = max(p["mfe"], side * (best - e) / rp)
                    be = e + side * 2 * TAKER * e
                    tighten = lambda x: max(p["stop"], x) if side > 0 else min(p["stop"], x)
                    if be_r is not None and p["mfe"] >= be_r:
                        p["stop"] = tighten(be)
                    if np.isfinite(a["atr1h"][t]) and (trail_from is None or p["mfe"] >= trail_from):
                        k = night_k if (night_k is not None and p["nights"] > 0) else trail_k
                        p["stop"] = tighten(p["ext"] - side * k * a["atr1h"][t])
                    if time_bars is not None and p["bars"] == time_bars and side * (c - e) <= 0:
                        close(s, p, c, t, "시간")
                    elif S["us_close_bar"][t]:
                        if side * (c - e) > 0 and (max_days is None or p["nights"] < max_days):
                            p["stop"] = tighten(be)
                            if night_k is not None and np.isfinite(a["atr1h"][t]):
                                p["stop"] = tighten(c - side * night_k * a["atr1h"][t])
                            p["nights"] += 1
                        else:
                            close(s, p, c, t, "마감")
            if S["us_open_bar"][t]:
                or_hi[s], or_lo[s] = h, l
            elif S["us_or_end"][t]:
                or_hi[s], or_lo[s] = max(or_hi[s], h), min(or_lo[s], l)
            floor = (day_peak if day_stop == "peak" else 0.0) - DAY_LOSS * day_start
            if day_pnl <= floor or pos[s] is not None or n_today[s] >= max_entries:
                continue
            if n_today[s] > 0:
                if reentry is None or (reentry == "win" and not last_win[s]):
                    continue
                if not (a["close"][t - 1] <= or_hi[s] if long else a["close"][t - 1] >= or_lo[s]):
                    continue
            if not S["entry_ok"][t] or not S["after_or"][t] or np.isnan(or_hi[s]) or not np.isfinite(a["atr"][t]):
                continue
            up = long and a["trend4"][t] > 0 and a["score"][t] >= 1 and c > or_hi[s]
            down = short and a["trend4"][t] < 0 and a["score"][t] <= -3 and c < or_lo[s]
            if above_ph:
                up = up and c > a["prev_high"][t]
                down = down and c < a["prev_low"][t]
            if not (up or down):
                continue
            side = 1 if up else -1
            atr = a["atr"][t]
            risk_px = stop_k * atr
            if stop_or:
                risk_px = float(np.clip(side * (c - (or_hi[s] + or_lo[s]) / 2), 0.5 * atr, 3 * atr))
            q = bal * risk / risk_px
            expo = sum(r["qty"] * A[r["sym"]]["close"][t] for r in pos.values() if r)
            q = min(q, max(0.0, (MAX_LEV * bal - expo) / c))
            n_today[s] += 1
            if q <= 0:
                continue
            pos[s] = {"sym": s, "side": side, "entry": c, "qty": q, "stop": c - side * risk_px, "ext": c,
                      "risk_px": risk_px, "risk_usd": q * risk_px, "time": idx[t], "fund": 0.0, "bars": 0,
                      "nights": 0, "mfe": 0.0, "nth": n_today[s]}
    return {"trades": pd.DataFrame(trades), "open": {s: p for s, p in pos.items() if p},
            "curve": pd.Series([b for _, b in curve], index=pd.DatetimeIndex([t for t, _ in curve]), dtype=float)}


def stats(res: dict, start=1000.0) -> dict:
    cv, tr = res["curve"], res["trades"]
    full = pd.concat([pd.Series([start], index=[LO]), cv])

    def seg(a, b):
        c = full[(full.index >= a) & (full.index < b)]
        b0 = full[full.index < a].iloc[-1] if (full.index < a).any() else start
        allc = pd.concat([pd.Series([b0], index=[a]), c])
        return (c.iloc[-1] / b0) ** (365.25 / (b - a).days) - 1, (allc / allc.cummax() - 1).min()

    w, ls = tr[tr.r > 0], tr[tr.r <= 0]
    streak = (tr.r <= 0).astype(int).groupby((tr.r > 0).cumsum()).sum().max()
    years, prev = {}, start
    for y in range(2018, 2027):
        c = cv[cv.index.year == y]
        years[y] = (c.iloc[-1] / prev - 1) if len(c) else 0.0
        prev = c.iloc[-1] if len(c) else prev
    return {"full": seg(LO, END), "design": seg(LO, SPLIT), "test": seg(SPLIT, END), "n": len(tr),
            "win": (tr.r > 0).mean(), "avg_w": w.r.mean(), "avg_l": ls.r.mean(), "avg_r": tr.r.mean(),
            "hold": (tr.exit_time - tr.entry_time).dt.total_seconds().mean() / 3600, "streak": streak,
            "night": tr.overnight.mean(), "years": years}


CONFIGS = {
    "기준 (orb 기본)": {},
    "손절 ATR×1": {"stop_k": 1.0},
    "손절 ATR×1.5": {"stop_k": 1.5},
    "손절 ATR×3": {"stop_k": 3.0},
    "손절 시가범위 중간": {"stop_or": True},
    "시간 손절 1시간": {"time_bars": 4},
    "시간 손절 2시간": {"time_bars": 8},
    "시간 손절 4시간": {"time_bars": 16},
    "본절 +1R": {"be_r": 1.0},
    "본절 +2R": {"be_r": 2.0},
    "추적 ATR×2": {"trail_k": 2.0},
    "추적 ATR×4": {"trail_k": 4.0},
    "추적 ATR×5": {"trail_k": 5.0},
    "추적 +1R 부터": {"trail_from": 1.0},
    "추적 +2R 부터": {"trail_from": 2.0},
    "오버나잇 ATR×2 조임": {"night_k": 2.0},
    "오버나잇 ATR×1.5 조임": {"night_k": 1.5},
    "최대 1박": {"max_days": 1},
    "최대 2박": {"max_days": 2},
    "최대 3박": {"max_days": 3},
}


COMBOS = {
    "기준": {},
    "전일 고점 위만": {"above_ph": True},
    "손절 1.5 + 추적 5": {"stop_k": 1.5, "trail_k": 5.0},
    "전일고점 + 손절 1.5": {"above_ph": True, "stop_k": 1.5},
    "전일고점 + 추적 5": {"above_ph": True, "trail_k": 5.0},
    "전일고점 + 손절 1.5 + 추적 5": {"above_ph": True, "stop_k": 1.5, "trail_k": 5.0},
    "전일고점 + 추적 5, 리스크 1%": {"above_ph": True, "trail_k": 5.0, "risk": 0.01},
    "기준 + 숏(−3)": {"short": True},
    "전일고점 + 추적 5 + 숏": {"above_ph": True, "trail_k": 5.0, "short": True},
    "숏(−3)만, 기준 청산": {"long": False, "short": True},
    "숏(−3)만, 전일저점 + 추적 5": {"long": False, "short": True, "above_ph": True, "trail_k": 5.0},
}


REENTRY = {
    "하루 한 번 (현재)": {"above_ph": True},
    "수익 후 재진입 1번": {"above_ph": True, "reentry": "win", "max_entries": 2},
    "수익 후 계속 재진입": {"above_ph": True, "reentry": "win"},
    "손익 무관 재진입 1번": {"above_ph": True, "reentry": "any", "max_entries": 2},
    "손익 무관 계속 재진입": {"above_ph": True, "reentry": "any"},
    "수익 후 계속, 고점 대비 −1% 중단": {"above_ph": True, "reentry": "win", "day_stop": "peak"},
    "손익 무관 계속, 고점 대비 −1% 중단": {"above_ph": True, "reentry": "any", "day_stop": "peak"},
    "수익 후 계속, 재진입은 전일고점 무시": {"above_ph": False, "reentry": "win"},
}


def line(name: str, r: dict) -> str:
    f, a, b = r["full"], r["design"], r["test"]
    return (f"{name:22} | {f[0]*100:+6.1f}% {f[1]*100:6.1f}% {f[0]/-f[1]:5.2f} | {a[0]*100:+6.1f}% {b[0]*100:+6.1f}% {b[1]*100:6.1f}% |"
            f" {r['n']/8.55:4.0f} {r['win']*100:4.1f}% {r['avg_w']:+5.2f} {r['avg_l']:+5.2f} {r['avg_r']:+.3f} |"
            f" {r['hold']:5.1f}h {r['night']*100:3.0f}% {r['streak']:3} | "
            + " ".join(f"{r['years'][y]*100:+4.0f}%" for y in range(2018, 2027)))


HEAD = (f"{'구성':22} | {'연평균':>7} {'낙폭':>6} {'효율':>5} | {'설계':>7} {'검증':>7} {'검증낙폭':>6} |"
        f" {'연':>4} {'승률':>5} {'평균익':>5} {'평균손':>5} {'평균R':>6} | {'보유':>6} {'박':>4} {'연패':>3} | "
        + " ".join(f"{y:>5}" for y in range(2018, 2027)))


def _job(kw):
    return stats(run(**kw))


def grid(configs: dict) -> dict:
    with ProcessPoolExecutor(4) as ex:
        return dict(zip(configs, ex.map(_job, configs.values())))


def main():
    print(HEAD)
    print("— 하나씩 바꾸기")
    for name, r in grid(CONFIGS).items():
        print(line(name, r))
    print("— 좋은 것끼리 조합")
    for name, r in grid(COMBOS).items():
        print(line(name, r))


if __name__ == "__main__":
    main()
