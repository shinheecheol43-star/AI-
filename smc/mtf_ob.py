"""멀티 타임프레임 오더블럭: 일봉 상승 OB 구간 안에서 하위봉(4h·1h·15m) 상승 OB가 생기면 롱.

자리   : 일봉 상승 OB(강의 1장 규칙, 몸통 존). 확정 후 90일까지 유효, 일봉 종가가 존 아래로 마감하면 무효
타이밍 : 하위봉 상승 OB의 존이 살아 있는 일봉 OB 존과 겹치면, 하위봉 OB 확정 캔들 종가에 시장가 진입
손절   : '좁게' = 하위봉 OB 패턴 꼬리 끝 / '넓게' = 일봉 OB 패턴 꼬리 끝
청산   : '2R' = 손절폭 2배 지정가 익절 / '추적' = 최고가 − 4시간봉 ATR × 3, 최대 20일
비교   : 같은 하위봉 OB 중 일봉 존 밖(대조군), 일봉 존에 처음 닿을 때 바로 진입(하위봉 확인 없음)
청산 계산은 모두 15분봉으로 한다. 수수료: 진입·손절 시장가 0.055%, 익절 지정가 0.02%. 펀딩비 반영.

사용:  python -m smc.mtf_ob
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import ARCHIVE, load_csv, resample
from .ob_lecture import find as find_ob
from .regime import DEFAULT_FUNDING, fetch_funding, indicators as daily_indicators
from .research import MAKER, TAKER
from .split_entry import portfolio

SPLIT = pd.Timestamp("2022-01-01", tz="UTC")
ZONE_DAYS, HOLD_DAYS = 90, 20
STEP = {"4h": pd.Timedelta("4h"), "1h": pd.Timedelta("1h"), "15m": pd.Timedelta("15min")}


def load(sym: str) -> dict:
    m5 = load_csv(ARCHIVE / f"{sym}USDT_5m.csv.gz")
    m5 = m5[m5.time >= "2017-09-01"].reset_index(drop=True)
    tf = {"1D": resample(m5, "1D"), "4h": resample(m5, "4h"), "1h": resample(m5, "1h"), "15m": resample(m5, "15min")}
    q = tf["15m"]
    h4 = tf["4h"].set_index("time")
    pc = h4.close.shift(1)
    trr = pd.concat([h4.high - h4.low, (h4.high - pc).abs(), (h4.low - pc).abs()], axis=1).max(axis=1)
    atr4 = trr.ewm(alpha=1 / 14, adjust=False).mean()
    atr4.index = atr4.index + pd.Timedelta("4h")                       # 마감된 4시간봉 값만
    days = q.time.dt.floor("D")
    fund = fetch_funding(f"{sym}USDT").reindex(pd.DatetimeIndex(days.unique())).fillna(DEFAULT_FUNDING)
    return {"tf": tf, "o": q.open.to_numpy(), "h": q.high.to_numpy(), "l": q.low.to_numpy(), "c": q.close.to_numpy(),
            "t": q.time, "atr4": atr4.reindex(q.time + pd.Timedelta("15min"), method="ffill").to_numpy(),
            "fcum": np.r_[0.0, fund.cumsum().to_numpy()], "didx": pd.Index(fund.index).get_indexer(days) + 1}


def daily_zones(dD: pd.DataFrame) -> list[dict]:
    c = dD.close.to_numpy()
    out = []
    for b in find_ob(dD):
        if b.side < 0:
            continue
        start = dD.time.iat[b.confirm] + pd.Timedelta("1D")             # 일봉 마감 후부터 유효
        broken = next((dD.time.iat[k] + pd.Timedelta("1D") for k in range(b.confirm + 1, len(c)) if c[k] < b.bottom), None)
        end = min(start + pd.Timedelta(days=ZONE_DAYS), broken) if broken is not None else start + pd.Timedelta(days=ZONE_DAYS)
        out.append({"start": start, "end": end, "top": b.top, "bottom": b.bottom, "stop": b.stop})
    return out


def manage(X: dict, k0: int, entry: float, stop: float, exit_mode: str, fee_in: float) -> dict | None:
    """15분봉 인덱스 k0 의 종가에 진입했다고 보고 청산까지 계산."""
    o, h, l, c, atr4 = X["o"], X["h"], X["l"], X["c"], X["atr4"]
    risk = entry - stop
    if risk <= 0.001 * entry:
        return None
    tp = entry + 2 * risk
    ext, ex, kind, ke = entry, None, None, None
    n = len(c)
    for k in range(k0 + 1, min(n, k0 + 1 + HOLD_DAYS * 96)):
        if o[k] <= stop:
            ex, kind, ke = o[k], "sl", k
            break
        if l[k] <= stop:
            ex, kind, ke = stop, "sl", k
            break
        if exit_mode == "2R" and h[k] >= tp:
            ex, kind, ke = max(o[k], tp), "tp", k
            break
        if exit_mode == "추적":
            ext = max(ext, h[k])
            if np.isfinite(atr4[k]):
                stop = max(stop, ext - 3 * atr4[k])
    if ex is None:
        ke = min(n - 1, k0 + HOLD_DAYS * 96)
        ex, kind = c[ke], "time"
    fund = (X["fcum"][X["didx"][ke]] - X["fcum"][X["didx"][k0]]) * entry
    pnl = ex - entry - fee_in * entry - (MAKER if kind == "tp" else TAKER) * ex - fund
    return {"r": pnl / risk, "stop_pct": risk / entry, "exit": X["t"].iat[ke] + pd.Timedelta("15min")}


def signals(X: dict, zones: list[dict]) -> list[dict]:
    """하위봉 상승 OB와 일봉 존 겹침 여부 + 일봉 존 첫 터치."""
    q_time = X["t"]
    k_of = {t: k for k, t in enumerate(q_time)}
    out = []
    for tf in ("4h", "1h", "15m"):
        d = X["tf"][tf]
        for b in find_ob(d):
            if b.side < 0:
                continue
            t_close = d.time.iat[b.confirm] + STEP[tf]
            live = [z for z in zones if z["start"] <= t_close < z["end"] and b.bottom <= z["top"] and b.top >= z["bottom"]]
            k0 = k_of.get(t_close - pd.Timedelta("15min"))                # 같은 시각에 마감하는 15분봉
            if k0 is None:
                continue
            z = max(live, key=lambda z: z["start"]) if live else None
            out.append({"kind": "일봉 존 안" if z else "일봉 존 밖", "tf": tf, "k0": k0, "time": t_close,
                        "entry": d.close.iat[b.confirm], "stop_narrow": b.stop, "stop_wide": z["stop"] if z else None})
    # 일봉 존에 처음 닿는 15분봉 (하위봉 확인 없이 존 윗변 지정가)
    starts = [int(q_time.searchsorted(z["start"])) for z in zones]
    for z, s in zip(zones, starts):
        for k in range(s, len(q_time)):
            if q_time.iat[k] >= z["end"]:
                break
            if X["l"][k] <= z["top"]:
                out.append({"kind": "일봉 존 첫 터치", "tf": "1D", "k0": k, "time": q_time.iat[k] + pd.Timedelta("15min"),
                            "entry": min(X["o"][k], z["top"]), "stop_narrow": z["stop"], "stop_wide": z["stop"], "limit": True})
                break
    return out


def main():
    rows = []
    rng = np.random.default_rng(0)
    for sym in ("BTC", "ETH"):
        X = load(sym)
        zones = daily_zones(X["tf"]["1D"])
        # 일봉 국면 점수: 진입 시각 기준 '전날까지' 확정된 값
        score = daily_indicators(X["tf"]["1D"].set_index("time"))["score"].shift(1)
        sig = signals(X, zones)
        outside = [s for s in sig if s["kind"] == "일봉 존 밖"]
        keep = [s for s in sig if s["kind"] != "일봉 존 밖"]
        # 대조군은 타임프레임별로 최대 3,000개만 무작위로 뽑아 계산 시간을 줄인다
        for tf in ("4h", "1h", "15m"):
            pool = [s for s in outside if s["tf"] == tf]
            keep += [pool[i] for i in rng.choice(len(pool), size=min(3000, len(pool)), replace=False)]
        print(f"{sym}: 일봉 상승 OB {len(zones)}개, 존 안 하위봉 OB "
              + ", ".join(f"{tf} {sum(1 for s in sig if s['kind'] == '일봉 존 안' and s['tf'] == tf)}개" for tf in ("4h", "1h", "15m")))
        for s in keep:
            for stop_mode in ("좁게", "넓게"):
                stop = s["stop_narrow"] if stop_mode == "좁게" else s["stop_wide"]
                if stop is None or stop >= s["entry"]:
                    continue
                for exit_mode in ("2R", "추적"):
                    r = manage(X, s["k0"], s["entry"], stop, exit_mode, MAKER if s.get("limit") else TAKER)
                    if r:
                        rows.append({"sym": sym, "kind": s["kind"], "tf": s["tf"], "stop": stop_mode, "exit_mode": exit_mode,
                                     "entry": s["time"], "score": score.get(s["time"].floor("D"), np.nan), **r})
    x = pd.DataFrame(rows)
    x.to_pickle(ARCHIVE.parent.parent / "reports" / "mtf_ob.pkl")
    for flt, fm in (("국면 필터 없음", x.score == x.score), ("일봉 국면 ≥ +1", x.score >= 1), ("일봉 국면 = +3", x.score >= 3)):
        print(f"\n■ {flt}")
        print(f"{'구분':12} {'봉':4} {'손절':4} {'청산':4} | {'설계 n/승률/R':>20} | {'검증 n/승률/R':>20} | {'검증 BTC/ETH':>13} | 검증 $1,000→ 낙폭")
        for (kind, tf, stop, ex), y in x[fm].groupby(["kind", "tf", "stop", "exit_mode"]):
            a, b = y[y.entry < SPLIT], y[y.entry >= SPLIT]
            if len(b) < 20 or len(a) < 20 or (kind == "일봉 존 밖" and stop == "넓게"):
                continue
            p = portfolio(b.sort_values("entry"))
            print(f"{kind:12} {tf:4} {stop:4} {ex:4} | {len(a):5} {(a.r>0).mean()*100:5.1f}% {a.r.mean():+.3f} | {len(b):5} {(b.r>0).mean()*100:5.1f}% {b.r.mean():+.3f}"
                  f" | {b[b.sym=='BTC'].r.mean():+.2f}/{b[b.sym=='ETH'].r.mean():+.2f} | ${p['final']:>8,.0f} {p['mdd']*100:5.1f}%")


if __name__ == "__main__":
    main()
