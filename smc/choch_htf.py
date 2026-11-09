"""사용자 조건(긴 꼬리 OB + 강한 공백)에 큰 시간 단위 추세 필터를 더하면 나아지는가.

규칙은 결과를 보기 전에 정했다.
기본 = CHoCH → OB → FVG 리테스트 (FVG 윗변 지정가, OB 꼬리 − 0.1 ATR 손절, 추적 3ATR), 15분·30분·1시간·4시간, 롱·숏
사용자 조건 = OB 꼬리 ≥ 캔들 길이 50% + FVG 높이 ≥ ATR × 1
큰 추세 (진입 시점에 확정된 값만)
  4시간 50EMA  : 4시간봉 종가가 50EMA 위면 상승 (4시간봉 매매는 일봉 장세로 대신)
  4시간 200EMA : 4시간봉 종가가 200EMA 위면 상승
  일봉 장세    : 전날까지 일봉 종가 > SMA200 이고 SMA50 > SMA200 이면 상승 (하락은 반대)
  각각 '같은 방향만'과 '반대 방향만' 비교
채점: BTC·ETH ~2021 (설계) / BTC·ETH 2022~ / SOL 전체 (처음 보는 코인), 같은 손절폭 무작위 진입(20번 평균)과 비교
판정 (미리 정함): 세 구간 모두 평균 R > 0, 2022~ 와 SOL 에서 무작위보다 0.05R 이상 높음 → 후보

사용:  python -m smc.choch_htf
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from itertools import product

import numpy as np
import pandas as pd

from .choch_loss import TFS, evaluate, trade_list
from .daytrade import SPLIT

HTF = {"4시간 50EMA": "htf", "4시간 200EMA": "htf200", "일봉 장세": "reg"}


def build(cfg):
    return trade_list(*cfg)


def stats(df, rng=None):
    if len(df) < 5:
        return None
    return evaluate(df, {}, rng)


def rand_mean(df, seeds=20):
    """무작위 진입 기준값: 표본이 작아 한 번은 크게 흔들리므로 20번 평균."""
    if len(df) < 5:
        return np.nan
    return float(np.mean([evaluate(df, {}, np.random.default_rng(s)).r.mean() for s in range(seeds)]))


def fmt(x, rr):
    if x is None or not len(x):
        return "   거래 없음"
    return f"{len(x):4}건 {x.r.mean():+.3f}R 승률 {(x.r > 0).mean()*100:3.0f}% (무작위 {rr:+.3f})"


def main():
    with ProcessPoolExecutor(4) as pool:
        T = pd.DataFrame([r for rows in pool.map(build, list(product(("BTC", "ETH", "SOL"), TFS, (1, -1)))) for r in rows])
    T = T.sort_values(["sym", "tf", "side", "e"]).reset_index(drop=True)
    T["test"] = T.time >= SPLIT
    user = (T.ob_wick >= 0.5) & (T.fvg_size >= 1.0)
    parts = {"BTC·ETH ~2021": T.sym.isin(["BTC", "ETH"]) & ~T.test, "BTC·ETH 2022~": T.sym.isin(["BTC", "ETH"]) & T.test,
             "SOL 전체": T.sym == "SOL"}
    print("사용자 조건 (긴 꼬리 OB + 강한 공백) + 큰 시간 단위 추세 · R 은 비용 뺀 값\n")
    print(f"  {'필터':24} | " + " | ".join(f"{p:^42}" for p in parts))
    rows = [("사용자 조건만", user)]
    for name, col in HTF.items():
        rows.append((f"+ {name} 같은 방향", user & (T[col] > 0.5)))
        rows.append((f"+ {name} 반대 방향", user & (T[col] <= 0.5)))
    res = {}
    for label, m in rows:
        cells = []
        for pn, pm in parts.items():
            sub = T[m & pm]
            x, rr = stats(sub), rand_mean(sub)
            res[(label, pn)] = (x, rr)
            cells.append(f"{fmt(x, rr):42}")
        print(f"  {label:24} | " + " | ".join(cells))

    print("\n■ 같은 방향 필터의 롱·숏, 봉별 (세 구간 합계)")
    for name, col in HTF.items():
        sub = T[user & (T[col] > 0.5)]
        x = stats(sub)
        if x is None:
            continue
        print(f"  {name:12} 롱 {x[x.side > 0].r.mean():+.3f}R ({(x.side > 0).sum()}) · 숏 {x[x.side < 0].r.mean():+.3f}R ({(x.side < 0).sum()}) · "
              + " ".join(f"{tf} {x[x.tf == tf].r.mean():+.2f}({(x.tf == tf).sum()})" for tf in TFS))
        x["y"] = x.time.dt.year
        print("    연도별 " + " ".join(f"{y}:{g.r.mean():+.2f}({len(g)})" for y, g in x.groupby("y")))

    print("\n■ 판정")
    for name in HTF:
        lab = f"+ {name} 같은 방향"
        xs = [res[(lab, p)] for p in parts]
        ok = all(x is not None and len(x) and x.r.mean() > 0 for x, _ in xs) and \
             all(x.r.mean() - rr >= 0.05 for x, rr in xs[1:])
        print(f"  {lab:24} {'✅ 후보' if ok else '–'}")


if __name__ == "__main__":
    main()
