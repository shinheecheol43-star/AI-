"""CHoCH → OB → FVG 리테스트 개선 연구: 후보 조건을 하나씩 더해 보고, 처음 보는 데이터(BTC·ETH 2022~, SOL 전체)로 확인.

규칙은 결과를 보기 전에 정했다.
기본: FVG 윗변 지정가 진입, 손절 OB 꼬리 − 0.1 ATR, 추적 3ATR (smc.choch_loss 기본). 15분·30분·1시간·4시간, 롱·숏.
후보 조건 (롱 기준, 숏은 뒤집어 같은 값)
  스윕        : OB 를 만든 바닥이 직전 60봉 저점을 한 번 깸 (유동성 사냥 뒤 CHoCH)
  할인 구간    : 진입가가 하락 파동(직전 60봉 고점 ~ 바닥)의 아래 절반
  거래 시간대  : 진입 시각 UTC 7~20시 (런던·뉴욕). 4시간봉은 조건 없음
  4시간 추세   : 4시간봉 종가가 50EMA 위 (4시간봉 자체는 일봉 장세)
  변동성 중간  : ATR/가격의 최근 500봉 백분위 20~80%
  강한 공백    : FVG 높이 ≥ ATR × 1
  긴 꼬리 OB   : OB 아래꼬리 ≥ 캔들 길이의 50%
  넉넉한 손절  : 손절폭 ≥ ATR × 1
  얕은 되돌림  : 되돌림 깊이 ≤ 50%
  강한 돌파    : 돌파 파동 ≥ ATR × 3
진행 (설계 = BTC·ETH ~2021 만 사용)
  1) 조건 하나씩: 설계 평균 R 변화
  2) 앞으로 더하기: 기본에서 시작해 설계 평균 R 을 가장 많이 올리는 조건을 하나씩 추가.
     설계 거래 150건 미만이 되거나, 0.02R 이상 오르지 않으면 멈춤
  3) 최종 조합을 처음 보는 데이터로 채점: BTC·ETH 2022~ 와 SOL 전체 기간 (SOL 은 연구에 한 번도 안 씀)
     같은 손절폭·같은 청산의 무작위 진입과 비교
판정 (미리 정함): BTC·ETH 2022~ 와 SOL 모두 평균 R > 0 이고 무작위보다 0.05R 이상 높으며 각각 50건 이상
덤: 지난번 사용자 조건(긴 꼬리 OB + 강한 공백)도 SOL 로 확인

사용:  python -m smc.choch_research
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from itertools import product

import numpy as np
import pandas as pd

from .choch_loss import TFS, evaluate, trade_list
from .daytrade import SPLIT

CANDS = {
    "스윕": lambda d: d.sweep > 0.5,
    "할인 구간": lambda d: d.disc <= 0.5,
    "거래 시간대": lambda d: (d.tf == "4h") | d.hour.between(7, 20),
    "4시간 추세": lambda d: d.htf > 0.5,
    "변동성 중간": lambda d: d.atr_pct.between(0.2, 0.8),
    "강한 공백": lambda d: d.fvg_size >= 1.0,
    "긴 꼬리 OB": lambda d: d.ob_wick >= 0.5,
    "넉넉한 손절": lambda d: d.stop_atr >= 1.0,
    "얕은 되돌림": lambda d: d.retrace <= 0.5,
    "강한 돌파": lambda d: d.break_power >= 3.0,
}
MIN_DESIGN, MIN_GAIN = 150, 0.02


def build(cfg):
    return trade_list(*cfg)


def score(T, mask, rng=None):
    sub = T[mask]
    if len(sub) < 10:
        return None
    x = evaluate(sub, {}, rng)
    return x


def summary(x):
    if x is None or not len(x):
        return (0, np.nan, np.nan)
    return (len(x), x.r.mean(), (x.r > 0).mean())


def main():
    cfgs = list(product(("BTC", "ETH", "SOL"), TFS, (1, -1)))
    with ProcessPoolExecutor(4) as pool:
        T = pd.DataFrame([r for rows in pool.map(build, cfgs) for r in rows]).sort_values(["sym", "tf", "side", "e"]).reset_index(drop=True)
    T["test"] = T.time >= SPLIT
    D = T[T.sym.isin(["BTC", "ETH"]) & ~T.test]                 # 설계
    V = T[T.sym.isin(["BTC", "ETH"]) & T.test]                  # 검증 1
    S = T[T.sym == "SOL"]                                       # 검증 2 (처음 보는 코인)
    print("CHoCH → OB → FVG 리테스트 개선 연구 · 설계 = BTC·ETH ~2021 · 채점 = BTC·ETH 2022~ 와 SOL 전체 · R 은 비용 뺀 값\n")
    nb, rb, wb = summary(evaluate(D, {}))
    print(f"기본 (설계): {nb}건 · 평균 {rb:+.3f}R · 승률 {wb*100:.0f}%   | SOL 신호 {len(S)}건 ({S.time.min():%Y-%m} ~)\n")

    print("■ 1. 조건 하나씩 붙였을 때 (설계 구간)")
    single = {}
    for name, f in CANDS.items():
        n, r, w = summary(score(D, f(D)))
        single[name] = r
        print(f"  {name:10} | {n:6}건 ({n/nb*100:3.0f}%) · 평균 {r:+.3f}R ({r - rb:+.3f}) · 승률 {w*100:.0f}%")

    print("\n■ 2. 앞으로 더하기 (설계 구간에서만 고름)")
    chosen, cur_mask, cur_r = [], pd.Series(True, index=D.index), rb
    while True:
        best = None
        for name, f in CANDS.items():
            if name in chosen:
                continue
            m = cur_mask & f(D)
            if m.sum() < MIN_DESIGN:
                continue
            n, r, w = summary(score(D, m))
            if n < MIN_DESIGN:
                continue
            if best is None or r > best[1]:
                best = (name, r, n, w, m)
        if best is None or best[1] - cur_r < MIN_GAIN:
            break
        chosen.append(best[0]); cur_mask = best[4]; cur_r = best[1]
        print(f"  + {best[0]:10} → 설계 {best[2]}건 · 평균 {best[1]:+.3f}R · 승률 {best[3]*100:.0f}%")
    if not chosen:
        print("  더할 조건이 없음 (어떤 조건도 0.02R 이상 올리지 못함)")

    def final_mask(df, names):
        m = pd.Series(True, index=df.index)
        for nm in names:
            m &= CANDS[nm](df)
        return m

    print(f"\n■ 3. 처음 보는 데이터로 채점: 고른 조합 = {' + '.join(chosen) if chosen else '기본'}")
    rng = np.random.default_rng(31)
    for label, df in (("BTC·ETH 2022~", V), ("SOL 전체", S)):
        for nm, names in (("기본", []), ("고른 조합", chosen), ("사용자 조건 (긴 꼬리 OB + 강한 공백)", ["긴 꼬리 OB", "강한 공백"])):
            m = final_mask(df, names)
            x, rx = score(df, m), score(df, m, rng)
            n, r, w = summary(x)
            rn, rr, _ = summary(rx)
            extra = ""
            if x is not None and len(x):
                extra = " · 롱 {:+.3f} 숏 {:+.3f} · ".format(x[x.side > 0].r.mean(), x[x.side < 0].r.mean()) + \
                        " ".join(f"{tf} {x[x.tf == tf].r.mean():+.2f}({(x.tf == tf).sum()})" for tf in TFS)
            print(f"  [{label}] {nm:32} | {n:5}건 · 평균 {r:+.3f}R · 승률 {w*100 if w == w else 0:3.0f}% · 무작위 {rr:+.3f}R{extra}")
    names = chosen
    ok = True
    for df in (V, S):
        m = final_mask(df, names)
        n, r, _ = summary(score(df, m))
        _, rr, _ = summary(score(df, m, np.random.default_rng(41)))
        ok &= n >= 50 and r > 0 and r - rr >= 0.05
    print(f"\n판정: {'✅ 두 채점 데이터 모두 통과' if ok and chosen else '– 통과 못 함'}")


if __name__ == "__main__":
    main()
