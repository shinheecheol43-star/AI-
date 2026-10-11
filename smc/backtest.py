"""오더블럭 / FVG / 거짓 돌파 전략 백테스트.

결과는 R(리스크 배수) 단위로 낸다. 1R = 진입가와 손절가 사이 거리만큼 잃는 것.
  +2R = 손절폭의 2배 이익, -1R = 손절.
체결 규칙(보수적):
  - 지정가 진입은 저가/고가가 진입가에 닿으면 체결. 시가가 이미 넘어가 있으면 시가에 체결.
  - 같은 캔들에서 손절과 익절이 모두 가능하면 손절로 본다.
  - 진입 캔들에서는 손절만 확인하고, 익절은 다음 캔들부터.
  - 수수료는 진입·청산 각각 fee 비율로 차감.

사용:  python -m smc.backtest                       (기본: data/ 의 BTC 1시간봉)
       python -m smc.backtest --resample 4h           (4시간봉으로 묶어서)
       python -m smc.backtest --source upbit --symbol KRW-BTC --count 5000
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd

from .data import DEFAULT_CSV, load, resample
from .detectors import Params, Zone, find_fakeouts, find_fvgs, find_order_blocks


@dataclass
class BTConfig:
    fee: float = 0.0005      # 한쪽 수수료 0.05% (바이낸스 기본 0.1%, 업비트 0.05%)
    max_wait: int = 48       # 존 생성 후 이 캔들 수 안에 안 닿으면 포기 (강의: 닿지 않으면 진입 안 함)
    max_hold: int = 240      # 진입 후 이 캔들 수가 지나면 종가 청산
    min_risk_pct: float = 0.001  # 손절폭이 진입가의 0.1%보다 작으면 수수료에 먹히므로 제외


@dataclass
class Trade:
    strategy: str
    side: int
    sweep: bool
    signal_i: int
    entry_i: int
    exit_i: int
    entry: float
    stop: float
    target: float
    exit: float
    outcome: str     # 'tp' | 'sl' | 'time'
    r: float         # 수수료 차감 후 R


def _manage(o, h, l, c, side, start, entry, stop, target, cfg: BTConfig):
    """진입 이후 청산 시뮬레이션. (exit_i, exit_price, outcome) 반환."""
    n = len(c)
    # 진입 캔들: 손절만 확인
    if (l[start] <= stop) if side > 0 else (h[start] >= stop):
        return start, stop, "sl"
    for t in range(start + 1, min(n, start + 1 + cfg.max_hold)):
        if side > 0:
            if o[t] <= stop:
                return t, o[t], "sl"
            if o[t] >= target:
                return t, o[t], "tp"
            if l[t] <= stop:
                return t, stop, "sl"
            if h[t] >= target:
                return t, target, "tp"
        else:
            if o[t] >= stop:
                return t, o[t], "sl"
            if o[t] <= target:
                return t, o[t], "tp"
            if h[t] >= stop:
                return t, stop, "sl"
            if l[t] <= target:
                return t, target, "tp"
    t = min(n - 1, start + cfg.max_hold)
    return t, c[t], "time"


def _r(side, entry, stop, exit_, fee):
    risk = abs(entry - stop)
    return (side * (exit_ - entry) - fee * (entry + exit_)) / risk


def trade_zone(df: pd.DataFrame, z: Zone, cfg: BTConfig) -> Trade | None:
    """존 하나를 기다렸다가 매매.

    익절 = '고점 탈환' (강의 1장 익절 1번, 2장 익절 첫 번째 기준):
      존이 생긴 뒤 가격이 되돌림 오기 전까지 만든 파동의 고점(하락형은 저점).
    """
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    n = len(c)
    side, entry, stop = z.side, z.entry, z.stop
    wave = h[z.confirm] if side > 0 else l[z.confirm]
    for t in range(z.confirm + 1, min(n, z.confirm + 1 + cfg.max_wait)):
        touched = l[t] <= entry if side > 0 else h[t] >= entry
        if not touched:
            wave = max(wave, h[t]) if side > 0 else min(wave, l[t])
            continue
        # 시가가 이미 손절선을 넘어선 경우: 존이 무너졌으므로 진입 안 함
        if (o[t] <= stop) if side > 0 else (o[t] >= stop):
            return None
        fill = min(o[t], entry) if side > 0 else max(o[t], entry)
        if abs(fill - stop) < cfg.min_risk_pct * fill:
            return None
        if side * (wave - fill) <= 0:
            return None
        ei, ex, oc = _manage(o, h, l, c, side, t, fill, stop, wave, cfg)
        return Trade(z.kind, side, z.sweep, z.confirm, t, ei, fill, stop, wave, ex, oc,
                     _r(side, fill, stop, ex, cfg.fee))
    return None


def trade_fakeouts(df: pd.DataFrame, p: Params, cfg: BTConfig) -> list[Trade]:
    """5장 전략 A: 복귀 캔들 종가에 진입, 이탈 꼬리 끝 손절, 가장 가까운 반대편 스윙에서 1차 익절."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    trades = []
    for f in find_fakeouts(df, p):
        if f.confirm + 1 >= len(c) or abs(f.entry - f.stop) < cfg.min_risk_pct * f.entry:
            continue
        ei, ex, oc = _manage(o, h, l, c, f.side, f.confirm + 1, f.entry, f.stop, f.targets[0], cfg)
        trades.append(Trade("FAKEOUT", f.side, f.trap, f.confirm, f.confirm, ei, f.entry, f.stop,
                            f.targets[0], ex, oc, _r(f.side, f.entry, f.stop, ex, cfg.fee)))
    return trades


def random_baseline(df: pd.DataFrame, trades: list[Trade], cfg: BTConfig, seeds: int = 20) -> list[float]:
    """같은 방향, 같은 손절폭(%), 같은 익절폭(%)으로 '아무 시점에나' 진입했을 때의 R.

    전략의 진입 '타이밍'에 실제로 의미가 있는지 보려는 대조군.
    """
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    rng = np.random.default_rng(0)
    out = []
    for _ in range(seeds):
        for tr in trades:
            t = int(rng.integers(50, len(c) - cfg.max_hold - 2))
            e = o[t]
            stop = e * (1 + (tr.stop - tr.entry) / tr.entry)
            target = e * (1 + (tr.target - tr.entry) / tr.entry)
            ei, ex, oc = _manage(o, h, l, c, tr.side, t, e, stop, target, cfg)
            out.append(_r(tr.side, e, stop, ex, cfg.fee))
    return out


def stats(rs) -> dict:
    rs = np.asarray(rs, dtype=float)
    if len(rs) == 0:
        return {"trades": 0}
    eq = np.cumsum(rs)
    dd = (eq - np.maximum.accumulate(np.r_[0, eq])[1:]).min()
    wins, losses = rs[rs > 0], rs[rs <= 0]
    pf = wins.sum() / -losses.sum() if losses.sum() < 0 else float("inf")
    return {
        "trades": int(len(rs)),
        "win_rate": round(float((rs > 0).mean()), 4),
        "avg_r": round(float(rs.mean()), 4),
        "total_r": round(float(rs.sum()), 2),
        "profit_factor": round(float(pf), 3),
        "max_dd_r": round(float(dd), 2),
        "avg_win_r": round(float(wins.mean()), 3) if len(wins) else 0.0,
        "avg_loss_r": round(float(losses.mean()), 3) if len(losses) else 0.0,
    }


def run(df: pd.DataFrame, p: Params = Params(), cfg: BTConfig = BTConfig()) -> dict:
    zones = {"OB": find_order_blocks(df, p), "FVG": find_fvgs(df, p)}
    trades = {k: [t for z in zs if (t := trade_zone(df, z, cfg))] for k, zs in zones.items()}
    trades["FAKEOUT"] = trade_fakeouts(df, p, cfg)

    years = pd.DatetimeIndex(df["time"]).year.to_numpy()
    report = {
        "data": {"bars": len(df), "start": str(df["time"].iloc[0]), "end": str(df["time"].iloc[-1]),
                 "buy_hold_pct": round(float(df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100, 1)},
        "params": asdict(p), "config": asdict(cfg),
        "signals": {k: len(v) for k, v in zones.items()} | {"FAKEOUT": len(trades["FAKEOUT"])},
        "results": {},
    }
    for name, ts in trades.items():
        rs = [t.r for t in ts]
        flag = "trap" if name == "FAKEOUT" else "sweep"
        res = {
            "all": stats(rs),
            "long": stats([t.r for t in ts if t.side > 0]),
            "short": stats([t.r for t in ts if t.side < 0]),
            f"with_{flag}": stats([t.r for t in ts if t.sweep]),
            f"without_{flag}": stats([t.r for t in ts if not t.sweep]),
            "by_year": {int(y): stats([t.r for t in ts if years[t.entry_i] == y]) for y in sorted(set(years))},
            "random_baseline": stats(random_baseline(df, ts, cfg)),
            "outcomes": pd.Series([t.outcome for t in ts]).value_counts().to_dict(),
        }
        report["results"][name] = res
    report["trades"] = {k: [asdict(t) for t in v] for k, v in trades.items()}
    return report


def _fmt(s: dict) -> str:
    if not s.get("trades"):
        return "   거래 없음"
    return (f"{s['trades']:>5}건  승률 {s['win_rate']*100:5.1f}%  평균 {s['avg_r']:+.3f}R  "
            f"누적 {s['total_r']:+8.1f}R  PF {s['profit_factor']:.2f}  MDD {s['max_dd_r']:.1f}R")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=str(DEFAULT_CSV), help="CSV 경로 | upbit | binance")
    ap.add_argument("--symbol")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--count", type=int, default=5000)
    ap.add_argument("--resample", help="상위 타임프레임으로 묶어서 테스트. 예: 4h")
    ap.add_argument("--fee", type=float, default=BTConfig.fee)
    ap.add_argument("--out", default="reports/backtest.json")
    a = ap.parse_args()

    df = load(a.source, a.symbol, a.interval, a.count)
    if a.resample:
        df = resample(df, a.resample)
    rep = run(df, cfg=BTConfig(fee=a.fee))
    d = rep["data"]
    print(f"데이터: {d['bars']}개 캔들, {d['start'][:10]} ~ {d['end'][:10]}, 같은 기간 단순 보유 {d['buy_hold_pct']:+.1f}%\n")
    for name, res in rep["results"].items():
        flag = "trap" if name == "FAKEOUT" else "sweep"
        print(f"[{name}]")
        print("  전체        ", _fmt(res["all"]))
        print("  매수만      ", _fmt(res["long"]))
        print("  매도만      ", _fmt(res["short"]))
        print(f"  {flag:5} 있음  ", _fmt(res[f"with_{flag}"]))
        print(f"  {flag:5} 없음  ", _fmt(res[f"without_{flag}"]))
        for y, s in res["by_year"].items():
            print(f"  {y}년      ", _fmt(s))
        print("  무작위 진입 ", _fmt(res["random_baseline"]))
        print()
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    print(f"상세 결과: {a.out}")


if __name__ == "__main__":
    main()
