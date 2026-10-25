"""데이트레이딩 개선안 검증 (15분봉, BTC·ETH 한 계좌, 롱만).

진입 방식
  시가범위 : 미국장 개장 후 첫 30분 고가를 15분봉 종가로 돌파 → 시장가 (하루 한 번)
  VWAP눌림 : 한국 09:00(=UTC 00:00)부터 계산한 당일 VWAP까지 내려오면 지정가 매수 (하루 한 번).
             직전 15분봉 종가가 VWAP 위였을 때만 주문을 건다
  전일고점 : 1시간봉 종가(정시에 끝나는 15분봉 종가)가 전일 고가를 처음 넘으면 시장가 (하루 한 번)
걸러내기
  F0 : 4시간봉 200EMA 위 + 전날 일봉 국면 ≥ +1
  F1 : 4시간봉 200EMA 위 + 전날 일봉 국면 = +3
  F2 : F1 + 전날 일봉 변동폭(고−저)/종가 가 최근 365일 중 상위 절반
공통 (사용자 규칙)
  신규 진입 한국 09:00 ~ 미국장 마감 3시간 전. 미국장 마감에 청산, 수익 중이면 손절을 본절로 올려 보유
  거래당 리스크 0.5%, 레버리지 합계 3배 이하, 그날(한국 09:00 기준) 실현 손익이 −1% 이하면 그날 신규 진입 중지
  최초 손절 15분봉 ATR × 2, 추적 손절 최고가 − 1시간봉 ATR × 3
  비용: 시장가 0.055%, 지정가 0.02%, 펀딩 정산 시각을 지나면 펀딩비

사용:  python -m smc.daytrade2
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from .daytrade import SPLIT, prepare, session_columns
from .data import ARCHIVE, load_csv, resample

TAKER, MAKER = 0.00055, 0.0002
RISK, DAY_LOSS, MAX_LEV = 0.005, 0.01, 3.0


@lru_cache(maxsize=None)
def extra(sym: str) -> pd.DataFrame:
    d = prepare(sym)
    m5 = load_csv(ARCHIVE / f"{sym}USDT_5m.csv.gz")
    e = pd.DataFrame(index=d.index)
    # 1시간봉 ATR: 마감된 1시간봉 값만
    h1 = resample(m5, "1h").set_index("time")
    pc = h1.close.shift(1)
    tr = pd.concat([h1.high - h1.low, (h1.high - pc).abs(), (h1.low - pc).abs()], axis=1).max(axis=1)
    a1 = tr.ewm(alpha=1 / 14, adjust=False).mean()
    a1.index = a1.index + pd.Timedelta("1h")
    e["atr1h"] = a1.reindex(d.index + pd.Timedelta("15min"), method="ffill").to_numpy()
    # 전일(UTC = 한국 09:00 기준) 고가와 변동폭 순위
    day = resample(m5, "1D").set_index("time")
    rng = (day.high - day.low) / day.close
    rank = rng.rolling(365, min_periods=120).rank(pct=True)
    e["prev_high"] = day.high.shift(1).reindex(d.index.floor("D")).to_numpy()
    e["vol_rank"] = rank.shift(1).reindex(d.index.floor("D")).to_numpy()
    # 당일 VWAP (그 봉까지 포함), 주문에는 '직전 봉까지'의 값을 쓴다
    tp = (d.high + d.low + d.close) / 3
    g = d.index.floor("D")
    e["vwap"] = (tp * d.volume).groupby(g).cumsum() / d.volume.groupby(g).cumsum()
    return e


def run(entry: str, flt: str, start: float = 1000.0, trail: float = 3.0, syms: tuple = ("BTC", "ETH")) -> dict:
    D = {s: prepare(s).join(extra(s)) for s in syms}
    idx = D[syms[0]].index
    for s in syms[1:]:
        idx = idx.intersection(D[s].index)
    idx = idx[idx >= "2018-03-15"]
    S = {k: v.to_numpy() for k, v in session_columns(idx).items()}
    hour_end = (idx.minute == 45)
    cols = ("open", "high", "low", "close", "atr", "atr1h", "trend4", "score", "fund_evt", "prev_high", "vol_rank", "vwap")
    A = {s: {k: D[s][k].reindex(idx).to_numpy() for k in cols} for s in syms}
    pos = {s: None for s in syms}
    bal, day, day_start, day_pnl, halted = start, None, start, 0.0, False
    or_hi = {s: np.nan for s in syms}
    done_today = {s: False for s in syms}
    trades, curve = [], []
    for t in range(1, len(idx)):
        if S["tday"][t] != day:
            day, day_start, day_pnl, halted = S["tday"][t], bal, 0.0, False
            done_today = {s: False for s in syms}
        for s in syms:
            a = A[s]
            o, h, l, c = a["open"][t], a["high"][t], a["low"][t], a["close"][t]
            if np.isnan(c):
                continue
            p = pos[s]
            if p is not None:                                    # 보유 관리
                p["fund"] += a["fund_evt"][t] * p["qty"] * o
                ex = None
                if o <= p["stop"]:
                    ex = o
                elif l <= p["stop"]:
                    ex = p["stop"]
                if ex is None:
                    p["ext"] = max(p["ext"], h)
                    if np.isfinite(a["atr1h"][t]):
                        p["stop"] = max(p["stop"], p["ext"] - trail * a["atr1h"][t])
                    if S["us_close_bar"][t]:
                        if c > p["entry"]:
                            p["stop"], p["overnight"] = max(p["stop"], p["entry"]), True
                        else:
                            ex = c
                if ex is not None:
                    pnl = p["qty"] * (ex - p["entry"] - p["fee_in"] * p["entry"] - TAKER * ex) - p["fund"]
                    bal += pnl
                    day_pnl += pnl
                    trades.append({"sym": s, "entry_time": p["time"], "exit_time": idx[t], "pnl": pnl,
                                   "r": pnl / p["risk_usd"], "overnight": p.get("overnight", False)})
                    curve.append((idx[t], bal))
                    pos[s] = None
            if S["us_open_bar"][t]:
                or_hi[s] = h
            elif S["us_or_end"][t]:
                or_hi[s] = max(or_hi[s], h)
            # 신규 진입 판단
            if day_pnl <= -DAY_LOSS * day_start:
                halted = True
            if halted or pos[s] is not None or done_today[s] or not S["entry_ok"][t]:
                continue
            ok = a["trend4"][t] > 0 and a["score"][t] >= (1 if flt == "F0" else 3)
            if flt == "F2":
                ok = ok and a["vol_rank"][t] >= 0.5
            if not ok:
                continue
            fill = fee = None
            if entry == "시가범위" and S["after_or"][t] and not np.isnan(or_hi[s]) and c > or_hi[s]:
                fill, fee = c, TAKER
            elif entry == "전일고점" and hour_end[t] and c > a["prev_high"][t] and a["close"][t - 1] <= a["prev_high"][t]:
                fill, fee = c, TAKER
            elif entry == "VWAP눌림":
                lim = a["vwap"][t - 1]
                if np.isfinite(lim) and a["close"][t - 1] > lim and l <= lim:
                    fill, fee = min(o, lim), MAKER
            if fill is None:
                continue
            done_today[s] = True
            atr = a["atr"][t - 1] if entry == "VWAP눌림" else a["atr"][t]
            risk_px = 2 * atr
            qty = bal * RISK / risk_px
            expo = sum(q["qty"] * A[q["sym"]]["close"][t] for q in pos.values() if q is not None)
            qty = min(qty, max(0.0, (MAX_LEV * bal - expo) / fill))
            if qty <= 0:
                continue
            p = {"sym": s, "entry": fill, "stop": fill - risk_px, "ext": fill, "qty": qty, "risk_usd": qty * risk_px,
                 "time": idx[t], "fund": 0.0, "fee_in": fee}
            # 지정가는 같은 봉 안에서 손절까지 갔을 수 있다 (보수적으로 확인)
            if entry == "VWAP눌림" and l <= p["stop"]:
                pnl = qty * (p["stop"] - fill - fee * fill - TAKER * p["stop"])
                bal += pnl
                day_pnl += pnl
                trades.append({"sym": s, "entry_time": idx[t], "exit_time": idx[t], "pnl": pnl, "r": pnl / p["risk_usd"],
                               "overnight": False})
                curve.append((idx[t], bal))
                continue
            pos[s] = p
    return {"trades": pd.DataFrame(trades),
            "curve": pd.Series([b for _, b in curve], index=pd.DatetimeIndex([t for t, _ in curve]), dtype=float)}


def summary(res: dict) -> dict:
    tr, cv = res["trades"], res["curve"]
    out = {}
    for name, lo, hi in (("설계", pd.Timestamp("2018-03-15", tz="UTC"), SPLIT), ("검증", SPLIT, pd.Timestamp("2026-10-01", tz="UTC"))):
        c = cv[(cv.index >= lo) & (cv.index < hi)]
        t = tr[(tr.entry_time >= lo) & (tr.entry_time < hi)]
        if c.empty:
            out[name] = None
            continue
        before = cv[cv.index < lo]
        b0 = before.iloc[-1] if len(before) else 1000.0
        yrs = (hi - lo).days / 365.25
        allc = pd.concat([pd.Series([b0], index=[lo]), c])
        out[name] = {"cagr": (c.iloc[-1] / b0) ** (1 / yrs) - 1, "mdd": (allc / allc.cummax() - 1).min(),
                     "per_year": len(t) / yrs, "win": (t.r > 0).mean(), "avg_r": t.r.mean()}
    years, prev = {}, 1000.0
    for y in range(2018, 2027):
        c = cv[cv.index.year == y]
        if len(c):
            years[y] = c.iloc[-1] / prev - 1
            prev = c.iloc[-1]
    out["years"] = years
    return out


def main():
    print(f"{'진입':8} {'필터':3} | {'설계 연평균/낙폭/연거래/평균R':>30} | {'검증 연평균/낙폭/연거래/평균R':>30}")
    keep = {}
    for entry in ("시가범위", "VWAP눌림", "전일고점"):
        for flt in ("F0", "F1", "F2"):
            sm = summary(run(entry, flt))
            keep[(entry, flt)] = sm
            a, b = sm["설계"], sm["검증"]
            f = lambda z: f"{z['cagr']*100:+6.1f}% {z['mdd']*100:6.1f}% {z['per_year']:5.0f}회 {z['avg_r']:+.3f}R" if z else "거래 없음"
            print(f"{entry:8} {flt:3} | {f(a):>30} | {f(b):>30}")
    print("\n연도별 수익률")
    print(f"{'진입':8} {'필터':3} " + " ".join(f"{y:>7}" for y in range(2018, 2027)))
    for (entry, flt), sm in keep.items():
        print(f"{entry:8} {flt:3} " + " ".join(f"{sm['years'].get(y, 0)*100:+6.1f}%" for y in range(2018, 2027)))


if __name__ == "__main__":
    main()
