"""스윙 롱·숏 한 계좌 운용을 더 효율적으로: 무엇을 바꾸면 수익/낙폭이 좋아지는가.

재료 (모두 4시간봉, BTC·ETH)
  롱  L  : swing_ls 강한 20봉 돌파 롱, 손절 ATR × 2, 추적 ATR × 3
  숏  S5 : 일봉 지지선 이탈 (short_study), S2 : 하락장 반등 실패 (short_study)
기준 : L 1% + S5·S2 각 0.5%, 숏 추적 청산, 같은 코인 롱·숏 동시 보유 허용, 레버리지 합계 3배 이하
비교 항목 (한 번에 하나씩 바꿔 기준과 비교)
  A 숏 청산     : 추적 / 고정(1.5R) / S5 고정 + S2 추적 ...
  B 숏 국면 필터 : S5 를 전날 일봉 국면 ≤ −1 일 때만
  C 충돌 처리   : 같은 코인 반대 포지션이 있을 때 동시 보유 / 새 신호 무시 / 기존 포지션 청산 후 전환
  D 국면 비중   : 신호 방향과 같은 국면 점수 3 → 1배, 1~2 → 0.5배, 반대 국면 → 0.25배
  E 리스크 배분 : 롱 0.75~1.5%, 숏 각 0.25~1%
  F 동시 보유   : 같은 방향 포지션을 동시에 k 개까지만
  G 숏 추가     : S1 하락 추세 이탈 숏을 더하기
판단: 효율 = 연평균 수익률 / |최대 낙폭|. 설계(2018–2021)에서 좋아지고 검증(2022–)에서도 유지되는지.

사용:  python -m smc.ls_combo
"""
from __future__ import annotations

import pandas as pd

from .data import fetch_binance_archive, resample
from .regime import indicators as daily_indicators
from .research import TAKER
from .swing_ls import describe, trades as swing_trades

SYMS = ("BTC", "ETH")


def closes() -> dict:
    out = {}
    for s in SYMS:
        h1 = fetch_binance_archive(s + "USDT", "1h")
        d4 = resample(h1, "4h").set_index("time")
        dD = resample(h1, "1D").set_index("time")
        out[s] = {"c4": d4.close, "score": daily_indicators(dD).score.shift(1)}
    return out


def pool(P: dict) -> pd.DataFrame:
    """모든 후보 거래를 한 표로 (진입가·국면 점수 포함)."""
    x = pd.read_pickle("reports/short_study.pkl")
    x = x[x.setup.str[:2].isin(["S1", "S2", "S5"])].rename(columns={"sym": "symbol"})
    x = x.assign(src=x.setup.str[:2] + "_" + x["mode"].map({"추적": "trail", "고정": "fixed"}), side=-1)
    L = swing_trades(sides=(1,)).assign(src="L")
    t = pd.concat([L, x], ignore_index=True)[["symbol", "side", "src", "entry", "exit", "r", "stop_pct"]]
    sig = t.entry - pd.Timedelta("4h")
    t["p0"] = [P[s]["c4"].get(k) for s, k in zip(t.symbol, sig)]
    t["score"] = [P[s]["score"].get(k.floor("D")) for s, k in zip(t.symbol, sig)]
    return t.sort_values("entry").reset_index(drop=True)


def curve(rows: pd.DataFrame, P: dict, conflict="both", start=1000.0, max_lev=3.0) -> pd.Series:
    """rows: symbol, side, entry, exit, r, stop_pct, p0, risk.  conflict: both | skip | flip"""
    bal, op, ev = start, [], []
    for _, t in rows.sort_values("entry").iterrows():
        for p in sorted([p for p in op if p["exit"] <= t.entry], key=lambda p: p["exit"]):
            bal += p["pnl"]
            op.remove(p)
            ev.append((p["exit"], bal))
        opp = [p for p in op if p["symbol"] == t.symbol and p["side"] != t.side]
        if opp and conflict == "skip":
            continue
        if opp and conflict == "flip":
            px = P[t.symbol]["c4"].get(t.entry - pd.Timedelta("4h"))
            for p in opp:                                   # 지금 가격에 시장가 청산 (펀딩은 생략)
                r = (p["side"] * (px - p["p0"]) - TAKER * (p["p0"] + px)) / (p["p0"] * p["stop_pct"])
                bal += p["pnl"] / p["r"] * r if p["r"] else 0.0
                op.remove(p)
                ev.append((t.entry, bal))
        if t.risk <= 0:
            continue
        planned = bal * t.risk / t.stop_pct
        n = min(planned, max_lev * bal - sum(p["notional"] for p in op))
        if n <= 0:
            continue
        op.append({"symbol": t.symbol, "side": t.side, "exit": t.exit, "p0": t.p0, "stop_pct": t.stop_pct, "r": t.r,
                   "pnl": bal * t.risk * n / planned * t.r, "notional": n})
    for p in sorted(op, key=lambda p: p["exit"]):
        bal += p["pnl"]
        ev.append((p["exit"], bal))
    return pd.Series([b for _, b in ev], index=pd.DatetimeIndex([e for e, _ in ev])).sort_index()


def build(T: pd.DataFrame, long=0.01, s5=0.005, s2=0.005, s5_mode="trail", s2_mode="trail", s5_bear=False,
          regime_size=False) -> pd.DataFrame:
    parts = [T[T.src == "L"].assign(risk=long), T[T.src == f"S5_{s5_mode}"].assign(risk=s5),
             T[T.src == f"S2_{s2_mode}"].assign(risk=s2)]
    x = pd.concat(parts)
    if s5_bear:
        x = x[~(x.src.str.startswith("S5") & ~(x.score <= -1))]
    if regime_size:
        aligned = x.score * x.side
        x = x.assign(risk=x.risk * aligned.map(lambda a: 1.0 if a >= 3 else (0.5 if a >= 1 else 0.25)))
    return x


def cap(rows: pd.DataFrame, k: int) -> pd.DataFrame:
    """같은 방향으로 동시에 열린 포지션이 k 개면 새 신호를 건너뛴다."""
    rows, keep, op = rows.sort_values("entry"), [], []
    for i, t in rows.iterrows():
        op = [o for o in op if o[1] > t.entry]
        if sum(1 for o in op if o[0] == t.side) >= k:
            continue
        op.append((t.side, t.exit))
        keep.append(i)
    return rows.loc[keep]


def line(name: str, x: pd.DataFrame, P: dict, conflict="both") -> dict:
    d = describe(curve(x, P, conflict))
    f, a, b = d["full"], d["design"], d["test"]
    print(f"{name:34} | {f[0]*100:+6.1f}% {f[1]*100:6.1f}% {f[0]/-f[1]:4.2f} | {a[0]*100:+6.1f}% {a[1]*100:6.1f}% {a[0]/-a[1]:4.2f} |"
          f" {b[0]*100:+6.1f}% {b[1]*100:6.1f}% {b[0]/-b[1]:4.2f} | {len(x):4} | "
          + " ".join(f"{d['years'][y]*100:+4.0f}%" for y in range(2018, 2027)))
    return d


def main():
    P = closes()
    T = pool(P)
    print(f"{'구성':34} | {'전체 연평균 낙폭 효율':^20} | {'설계 연평균 낙폭 효율':^20} | {'검증 연평균 낙폭 효율':^20} | 거래 | "
          + " ".join(f"{y:>5}" for y in range(2018, 2027)))
    print("— 기준")
    line("기준 L1% + S5·S2 0.5% (추적)", build(T), P)
    print("— A 숏 청산 방식")
    line("S5·S2 고정 1.5R", build(T, s5_mode="fixed", s2_mode="fixed"), P)
    line("S5 고정 + S2 추적", build(T, s5_mode="fixed"), P)
    line("S5 추적 + S2 고정", build(T, s2_mode="fixed"), P)
    print("— B 숏 국면 필터")
    line("S5 는 국면 ≤ −1 일 때만", build(T, s5_bear=True), P)
    print("— C 같은 코인 반대 포지션")
    line("새 반대 신호 무시", build(T), P, "skip")
    line("기존 포지션 청산 후 전환", build(T), P, "flip")
    print("— D 국면 점수로 비중 조절")
    line("국면 비중 (3→1, 1~2→0.5, 반대→0.25)", build(T, regime_size=True), P)
    print("— E 리스크 배분")
    for lr in (0.0075, 0.01, 0.015):
        for sr in (0.0025, 0.005, 0.0075, 0.01):
            line(f"롱 {lr*100:.2f}% / 숏 각 {sr*100:.2f}%", build(T, long=lr, s5=sr, s2=sr), P)
    print("— F 같은 방향 동시 보유 제한")
    for k in (1, 2, 3):
        line(f"같은 방향 동시 {k}개까지", cap(build(T), k), P)
    print("— G 숏 신호 추가")
    S1 = T[T.src == "S1_trail"]
    line("+ S1 추세 이탈 숏 0.25%", pd.concat([build(T), S1.assign(risk=0.0025)]), P)
    line("+ S1 (국면 ≤ −1) 0.5%", pd.concat([build(T), S1[S1.score <= -1].assign(risk=0.005)]), P)
    print("— 신호별 평균 R (설계 / 검증)")
    for src in ("L", "S5_trail", "S2_trail", "S1_trail"):
        y = T[T.src == src]
        print(f"{src:9} {len(y):4}회 승률 {(y.r > 0).mean()*100:3.0f}% 평균R {y.r.mean():+.2f}"
              f" ({y[y.entry < '2022'].r.mean():+.2f} / {y[y.entry >= '2022'].r.mean():+.2f})")


if __name__ == "__main__":
    main()
