"""레버리지 ETF(예: SOXL) 단타 검증: 손절을 짧게 잡고 그날 안에 끝내는 매매 (야후 1시간봉, 최근 약 2년).

검증 전에 정한 후보 (정규장만, 그날 종가에 무조건 청산)
  A 시가범위 돌파 롱 : 첫 1시간봉(09:30~10:30) 고가를 두 번째 봉 종가가 넘으면 그 종가에 매수
  B 시가범위 이탈 숏 : 첫 1시간봉 저가를 두 번째 봉 종가가 깨면 그 종가에 매도
  C 갭 하락 반등 롱  : 시가가 전날 종가보다 3% 이상 낮고 첫 봉이 양봉이면 첫 봉 종가에 매수
  D 갭 상승 실패 숏  : 시가가 전날 종가보다 3% 이상 높고 첫 봉이 음봉이면 첫 봉 종가에 매도
손절: ① 첫 봉 반대쪽 끝(범위)  ② 진입가 −1%  ③ 진입가 −2%    익절: 없음(종가 청산) / 손절폭 × 2
같은 봉에서 손절·익절이 모두 닿으면 손절로 본다. 비용: 진입·청산 각 0.1% (수수료 + 슬리피지).
설계 구간: 처음 1년, 검증 구간: 그 이후. 계좌: 거래당 1% 리스크, 복리, 레버리지 3배 이하.

사용:  python -m smc.intraday_etf SOXL
"""
from __future__ import annotations

import sys

import pandas as pd

COST = 0.001


def fetch_1h(sym: str) -> pd.DataFrame:
    import requests

    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}", params={"range": "730d", "interval": "1h"},
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    j = r.json()["chart"]["result"][0]
    q = j["indicators"]["quote"][0]
    d = pd.DataFrame({"time": pd.to_datetime(j["timestamp"], unit="s", utc=True), **{k: q[k] for k in ("open", "high", "low", "close")}})
    d = d.dropna()
    d["et"] = d.time.dt.tz_convert("America/New_York")
    d["day"] = d.et.dt.date
    return d.reset_index(drop=True)


def day_trades(h: pd.DataFrame, setup: str, stop_mode: str, tp_r: float | None) -> pd.DataFrame:
    rows, prev_close = [], None
    for day, g in h.groupby("day"):
        g = g.sort_values("time").reset_index(drop=True)
        if len(g) < 4:
            prev_close = g.close.iloc[-1]
            continue
        b0, b1 = g.iloc[0], g.iloc[1]
        side = k = None
        if setup == "A 시가범위 돌파 롱" and b1.close > b0.high:
            side, k, entry = 1, 1, b1.close
        elif setup == "B 시가범위 이탈 숏" and b1.close < b0.low:
            side, k, entry = -1, 1, b1.close
        elif prev_close and setup == "C 갭 하락 반등 롱" and b0.open <= prev_close * 0.97 and b0.close > b0.open:
            side, k, entry = 1, 0, b0.close
        elif prev_close and setup == "D 갭 상승 실패 숏" and b0.open >= prev_close * 1.03 and b0.close < b0.open:
            side, k, entry = -1, 0, b0.close
        prev_close = g.close.iloc[-1]
        if side is None:
            continue
        if stop_mode == "범위":
            stop = b0.low if side > 0 else b0.high
        else:
            stop = entry * (1 - side * float(stop_mode.rstrip("%")) / 100)
        risk = abs(entry - stop)
        if risk <= entry * 0.002:                      # 너무 좁은 범위는 건너뜀
            continue
        tp = entry + side * tp_r * risk if tp_r else None
        ex = None
        for _, b in g.iloc[k + 1:].iterrows():
            if (b.open <= stop) if side > 0 else (b.open >= stop):
                ex = b.open
                break
            if (b.low <= stop) if side > 0 else (b.high >= stop):
                ex = stop
                break
            if tp and ((b.high >= tp) if side > 0 else (b.low <= tp)):
                ex = tp
                break
        if ex is None:
            ex = g.close.iloc[-1]
        pnl = side * (ex - entry) - COST * (entry + ex)
        rows.append({"day": pd.Timestamp(day), "side": side, "r": pnl / risk, "ret": pnl / entry, "stop_pct": risk / entry})
    return pd.DataFrame(rows)


def account(x: pd.DataFrame, risk=0.01, max_lev=3.0) -> pd.Series:
    bal, out = 1000.0, []
    for t in x.itertuples():
        size = min(bal * risk / t.stop_pct, max_lev * bal)
        bal += size * t.ret
        out.append(bal)
    return pd.Series(out, index=x.day)


def main(sym: str = "SOXL"):
    h = fetch_1h(sym)
    days = sorted(h.day.unique())
    split = pd.Timestamp(days[0]) + pd.Timedelta(days=365)
    print(f"{sym} 1시간봉 {days[0]} ~ {days[-1]} ({len(days)}일), 설계 ~{split:%Y-%m-%d}, 비용 각 {COST:.1%}\n")
    print(f"{'전략':16} {'손절':4} {'익절':5} | {'거래':>4} {'승률':>5} {'평균R':>6} {'거래당':>7} | {'설계R':>6} {'검증R':>6} | "
          f"{'1% 리스크 계좌':>12} {'낙폭':>6}")
    for setup in ("A 시가범위 돌파 롱", "B 시가범위 이탈 숏", "C 갭 하락 반등 롱", "D 갭 상승 실패 숏"):
        for stop in ("범위", "1%", "2%"):
            for tp in (None, 2.0):
                x = day_trades(h, setup, stop, tp)
                if len(x) < 10:
                    continue
                a, b = x[x.day < split], x[x.day >= split]
                eq = account(x)
                mdd = (eq / eq.cummax() - 1).min()
                print(f"{setup:16} {stop:4} {'2R' if tp else '종가':5} | {len(x):4} {(x.r > 0).mean()*100:4.0f}% {x.r.mean():+.3f} {x.ret.mean()*100:+6.2f}% |"
                      f" {a.r.mean():+.3f} {b.r.mean():+.3f} | {(eq.iloc[-1] / 1000 - 1)*100:+10.1f}% {mdd*100:6.1f}%")
        print()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "SOXL")
