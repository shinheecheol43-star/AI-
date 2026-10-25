"""데이트레이딩 자동매매 시뮬레이션 (15분봉, BTC·ETH 동시, 계좌 하나).

사용자 규칙
  신규 진입 시간 : 한국 09:00 ~ 미국장 마감 3시간 전
  장 마감 처리   : 미국장 마감(뉴욕 16:00)에 청산. 단, 그 시각 수익 중이면 손절을 본절로 올리고 보유
  하루 손실 한도 : 거래일(한국 09:00 시작) 실현 손익이 그날 시작 잔고의 −1% 이하면 그날 신규 진입 중지
  하루 수익 목표 : 없음 / +1% / +2% / +3% 비교 (도달하면 그날 신규 진입 중지)
  거래당 리스크  : 잔고의 0.5%, 레버리지 합계 3배 이하
  방향          : 4시간봉 200 EMA + 전날 일봉 국면 점수가 같은 방향 (롱만 / 롱·숏)
진입 신호(15분봉 마감 기준)
  돌파   : 종가가 직전 20봉 최고가를 처음 넘음 (숏은 최저가)
  시가범위: 미국장 개장 후 첫 30분 고가 돌파 (숏은 저가 이탈). 미국 평일, 하루 한 번
  세션   : 미국장 개장 첫 15분봉 마감 때 그날 한국 09:00 가격보다 위면 롱(아래면 숏). 미국 평일, 하루 한 번
청산    : 최초 손절 ATR(15분,14) × 2, 추적 손절 최고가 − ATR × 3
비용    : 진입·청산 시장가 0.055%, 펀딩 정산(UTC 0·8·16시)을 지나면 그날 펀딩비의 1/3

사용:  python -m smc.daytrade
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from functools import lru_cache

from .data import load_csv, resample, ARCHIVE
from .regime import DEFAULT_FUNDING, fetch_funding, indicators as daily_indicators

TAKER = 0.00055
RISK, DAY_LOSS, MAX_LEV = 0.005, 0.01, 3.0
STOP_ATR, TRAIL_ATR = 2.0, 3.0
SPLIT = pd.Timestamp("2022-01-01", tz="UTC")


@lru_cache(maxsize=None)
def prepare(sym: str) -> pd.DataFrame:
    m5 = load_csv(ARCHIVE / f"{sym}USDT_5m.csv.gz")
    d = resample(m5, "15min").set_index("time")
    pc = d.close.shift(1)
    tr = pd.concat([d.high - d.low, (d.high - pc).abs(), (d.low - pc).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    d["hh"] = d.high.rolling(20).max().shift(1)
    d["ll"] = d.low.rolling(20).min().shift(1)
    # 4시간봉 추세: 마감된 4시간봉만
    h4 = resample(m5, "4h").set_index("time")
    trend4 = np.sign(h4.close - h4.close.ewm(span=200, adjust=False).mean())
    trend4.index = trend4.index + pd.Timedelta("4h")                # 마감 시각 기준
    end = d.index + pd.Timedelta("15min")
    d["trend4"] = trend4.reindex(end, method="ffill").to_numpy()
    daily = daily_indicators(resample(m5, "1D").set_index("time"))
    d["score"] = daily.score.shift(1).reindex(d.index.floor("D")).to_numpy()   # 전날까지
    fund = fetch_funding(f"{sym}USDT")
    d["fund_evt"] = 0.0
    evt = d.index.hour.isin([0, 8, 16]) & (d.index.minute == 0)             # 정산 시각에 시작하는 봉
    d.loc[evt, "fund_evt"] = (fund.reindex(d.index[evt].floor("D")).fillna(DEFAULT_FUNDING) / 3).to_numpy()
    return d


def session_columns(idx: pd.DatetimeIndex) -> pd.DataFrame:
    ny = idx.tz_convert("America/New_York")
    kst = idx.tz_convert("Asia/Seoul")
    s = pd.DataFrame(index=idx)
    nyt = ny.hour * 60 + ny.minute
    weekday = ny.weekday < 5
    s["us_open_bar"] = weekday & (nyt == 9 * 60 + 30)                    # 09:30~09:45 봉
    s["us_or_end"] = weekday & (nyt == 9 * 60 + 45)                      # 첫 30분의 두 번째 봉
    s["us_close_bar"] = nyt == 15 * 60 + 45                              # 15:45~16:00 봉 (매일)
    kday = (kst - pd.Timedelta("9h")).normalize()                        # 한국 09:00에 시작하는 거래일
    s["tday"] = kday.tz_localize(None)
    s["kst_open_bar"] = (kst.hour == 9) & (kst.minute == 0)
    minutes_to_close = (16 * 60 - nyt) % (24 * 60)
    s["entry_ok"] = ((kst.hour >= 9) | (kst.hour < 3)) & (minutes_to_close > 180)
    s["after_or"] = weekday & (nyt >= 10 * 60) & (nyt < 16 * 60)
    return s


def run(strategy: str, both_sides: bool, target: float | None, overnight_be: bool = True,
        start: float = 1000.0) -> dict:
    syms = ("BTC", "ETH")
    D = {s: prepare(s) for s in syms}
    idx = D["BTC"].index.intersection(D["ETH"].index)
    idx = idx[idx >= "2018-03-15"]
    S = {k: v.to_numpy() for k, v in session_columns(idx).items()}
    A = {s: {k: D[s][k].reindex(idx).to_numpy() for k in
             ("open", "high", "low", "close", "atr", "hh", "ll", "trend4", "score", "fund_evt")} for s in syms}
    pos = {s: None for s in syms}
    bal = start
    day, day_start_bal, day_pnl, day_stop = None, bal, 0.0, False
    or_hi = {s: np.nan for s in syms}
    or_lo = {s: np.nan for s in syms}
    kst_open_px = {s: np.nan for s in syms}
    fired = {s: set() for s in syms}
    trades, curve = [], []
    tday = S["tday"]
    for t in range(1, len(idx)):
        if tday[t] != day:                                    # 새 거래일
            day, day_start_bal, day_pnl, day_stop = tday[t], bal, 0.0, False
        for s in syms:
            a = A[s]
            o, h, l, c, atr = a["open"][t], a["high"][t], a["low"][t], a["close"][t], a["atr"][t]
            if np.isnan(c):
                continue
            p = pos[s]
            # 1) 보유 포지션 관리
            if p is not None:
                p["fund"] += p["side"] * a["fund_evt"][t] * p["qty"] * o
                side, stop = p["side"], p["stop"]
                exit_px = None
                if (o <= stop) if side > 0 else (o >= stop):
                    exit_px = o
                elif (l <= stop) if side > 0 else (h >= stop):
                    exit_px = stop
                if exit_px is None:
                    p["ext"] = max(p["ext"], h) if side > 0 else min(p["ext"], l)
                    new = p["ext"] - side * TRAIL_ATR * atr
                    p["stop"] = max(stop, new) if side > 0 else min(stop, new)
                    if S["us_close_bar"][t]:                  # 미국장 마감
                        in_profit = side * (c - p["entry"]) > 0
                        if overnight_be and in_profit:
                            p["stop"] = max(p["stop"], p["entry"]) if side > 0 else min(p["stop"], p["entry"])
                            p["overnight"] = True
                        else:
                            exit_px = c
                if exit_px is not None:
                    pnl = p["qty"] * (side * (exit_px - p["entry"]) - TAKER * (p["entry"] + exit_px)) - p["fund"]
                    bal += pnl
                    day_pnl += pnl
                    trades.append({"sym": s, "entry_time": p["time"], "exit_time": idx[t], "side": side,
                                   "pnl": pnl, "r": pnl / p["risk_usd"], "overnight": p.get("overnight", False)})
                    curve.append((idx[t], bal))
                    pos[s] = None
            # 2) 세션 기준값
            if S["kst_open_bar"][t]:
                kst_open_px[s] = o
                fired[s] = set()
            if S["us_open_bar"][t]:
                or_hi[s], or_lo[s] = h, l
            elif S["us_or_end"][t]:
                or_hi[s], or_lo[s] = max(or_hi[s], h), min(or_lo[s], l)
            # 3) 신규 진입
            if day_stop or pos[s] is not None or not S["entry_ok"][t] or np.isnan(atr):
                continue
            if day_pnl <= -DAY_LOSS * day_start_bal or (target is not None and day_pnl >= target * day_start_bal):
                day_stop = True
                continue
            regime = a["trend4"][t] if a["trend4"][t] == np.sign(a["score"][t]) else 0
            side = 0
            if strategy == "돌파":
                if c > a["hh"][t] and a["close"][t - 1] <= a["hh"][t - 1]:
                    side = 1
                elif c < a["ll"][t] and a["close"][t - 1] >= a["ll"][t - 1]:
                    side = -1
            elif strategy == "시가범위" and not np.isnan(or_hi[s]) and "or" not in fired[s]:
                after_or = S["after_or"][t]
                if after_or and c > or_hi[s]:
                    side = 1
                elif after_or and c < or_lo[s]:
                    side = -1
            elif strategy == "세션" and S["us_open_bar"][t] and not np.isnan(kst_open_px[s]):
                side = 1 if c > kst_open_px[s] else -1
            if side == 0 or side != regime or (side < 0 and not both_sides):
                continue
            if strategy in ("시가범위", "세션"):
                fired[s].add("or")
            risk_px = STOP_ATR * atr
            risk_usd = bal * RISK
            qty = risk_usd / risk_px
            exposure = sum(q["qty"] * A[q["sym"]]["close"][t] for q in pos.values() if q is not None)
            qty = min(qty, max(0.0, (MAX_LEV * bal - exposure) / c))
            if qty <= 0:
                continue
            pos[s] = {"sym": s, "side": side, "entry": c, "stop": c - side * risk_px, "ext": c, "qty": qty,
                      "risk_usd": qty * risk_px, "time": idx[t], "fund": 0.0}
    tr = pd.DataFrame(trades)
    cv = pd.Series([b for _, b in curve], index=[t for t, _ in curve], dtype=float)
    return {"trades": tr, "curve": cv, "final": bal}


def stats(res: dict, lo, hi, start_bal=None) -> dict:
    tr = res["trades"]
    tr = tr[(tr.entry_time >= lo) & (tr.entry_time < hi)]
    cv = res["curve"]
    cv = cv[(cv.index >= lo) & (cv.index < hi)]
    if cv.empty:
        return {}
    b0 = start_bal if start_bal is not None else cv.iloc[0] - tr.pnl.iloc[0]
    yrs = (cv.index[-1] - cv.index[0]).days / 365.25
    return {"cagr": (cv.iloc[-1] / b0) ** (1 / yrs) - 1, "mdd": (cv / cv.cummax() - 1).min(), "n": len(tr),
            "win": (tr.r > 0).mean(), "avg_r": tr.r.mean(), "per_day": len(tr) / max(1, (hi - lo).days),
            "overnight": tr.overnight.mean(), "growth": cv.iloc[-1] / b0}


def main():
    lo_all, hi_all = pd.Timestamp("2018-03-15", tz="UTC"), pd.Timestamp("2026-10-01", tz="UTC")
    print(f"{'전략':6} {'방향':6} {'수익목표':6} | {'설계 18–21 연평균/낙폭/평균R':>26} | {'검증 22–26 연평균/낙폭/평균R':>26} | 승률  하루거래  오버나잇")
    for strat in ("돌파", "시가범위", "세션"):
        for both in (False, True):
            for target in (None, 0.01, 0.02, 0.03):
                r = run(strat, both, target)
                a, b = stats(r, lo_all, SPLIT, 1000.0), stats(r, SPLIT, hi_all)
                if not a or not b:
                    continue
                tg = "없음" if target is None else f"+{target*100:.0f}%"
                print(f"{strat:6} {'롱·숏' if both else '롱만':6} {tg:6} | {a['cagr']*100:+7.1f}% {a['mdd']*100:6.1f}% {a['avg_r']:+.3f}R"
                      f" | {b['cagr']*100:+7.1f}% {b['mdd']*100:6.1f}% {b['avg_r']:+.3f}R | {b['win']*100:4.1f}% {b['per_day']:5.2f}  {b['overnight']*100:4.0f}%")


if __name__ == "__main__":
    main()
