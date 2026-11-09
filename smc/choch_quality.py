"""CHoCH → OB → FVG 리테스트에 '좋은 OB·FVG' 조건을 붙이면 나아지는가.

규칙은 결과를 보기 전에 정했다 (롱 기준, 숏은 가격을 뒤집어 같은 규칙 → 숏은 OB 윗꼬리)
  OB 꼬리      : OB 캔들의 아래꼬리 ÷ 캔들 길이 ≥ 0 (조건 없음) · 0.3 · 0.5
  급격한 공백  : 둘 중 하나로 정의
                 FVG 크기  = FVG 높이 ÷ ATR ≥ 0 · 0.5 · 1.0
                 급등 캔들 = FVG 가운데 캔들 몸통 ÷ ATR ≥ 0 · 1.0 · 1.5
  진입·손절·청산은 smc.choch_loss 기본과 같다 (FVG 윗변 지정가, OB 꼬리 − 0.1 ATR 손절, 추적 3ATR)
  비교로 고정 목표 2R 청산도 같이 본다.
봉: 15분·30분·1시간·4시간, BTC·ETH, 롱·숏. 설계 ~2021 / 검증 2022~
판정 (미리 정함): 봉마다 설계 구간에서 가장 좋았던 조건 조합(거래 60건 이상)을 골라 검증 구간에서
  평균 R > 0, 50건 이상, 같은 손절폭의 무작위 진입보다 0.05R 이상 높음, BTC·ETH 둘 다 > 0

사용:  python -m smc.choch_quality
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from itertools import product

import numpy as np
import pandas as pd

from .choch_loss import TFS, evaluate, trade_list
from .choch_ob_fvg import SYMS
from .daytrade import SPLIT

WICKS = (0.0, 0.3, 0.5)
GAPS = {"FVG 크기": (0.0, 0.5, 1.0), "급등 캔들": (0.0, 1.0, 1.5)}


def build(cfg):
    return trade_list(*cfg)


def main():
    cfgs = list(product(SYMS, TFS, (1, -1)))
    with ProcessPoolExecutor(4) as pool:
        T = pd.DataFrame([r for rows in pool.map(build, cfgs) for r in rows]).sort_values(["sym", "tf", "side", "e"])
    print("CHoCH → OB(꼬리) → FVG(급격한 공백) → 리테스트 · BTC·ETH · 설계 ~2021 / 검증 2022~ · R 은 비용 뺀 값\n")
    print(f"전체 신호 {len(T):,}건 · OB 꼬리 ≥0.3: {(T.ob_wick >= .3).mean()*100:.0f}% · ≥0.5: {(T.ob_wick >= .5).mean()*100:.0f}%"
          f" · FVG ≥0.5ATR: {(T.fvg_size >= .5).mean()*100:.0f}% · ≥1ATR: {(T.fvg_size >= 1).mean()*100:.0f}%"
          f" · 급등 캔들 ≥1ATR: {(T.disp >= 1).mean()*100:.0f}% · ≥1.5ATR: {(T.disp >= 1.5).mean()*100:.0f}%\n")
    rows = []
    rng = np.random.default_rng(21)
    for exit_name, rule in (("추적 3ATR", {}), ("고정 2R", {"fixed": 2.0})):
        for gname, gvals in GAPS.items():
            col = "fvg_size" if gname == "FVG 크기" else "disp"
            for w, gv in product(WICKS, gvals):
                sub = T[(T.ob_wick >= w) & (T[col] >= gv)]
                if len(sub) < 20:
                    continue
                x = evaluate(sub, rule)
                rx = evaluate(sub, rule, rng)
                x["test"] = x.time >= SPLIT
                rx["test"] = rx.time >= SPLIT
                for tf in TFS + ("전체",):
                    z = x if tf == "전체" else x[x.tf == tf]
                    rz = rx if tf == "전체" else rx[rx.tf == tf]
                    tr, te = z[~z.test], z[z.test]
                    rows.append(dict(exit=exit_name, gap=gname, wick=w, gv=gv, tf=tf, n_tr=len(tr), r_tr=tr.r.mean(),
                                     n_te=len(te), r_te=te.r.mean(), win_te=(te.r > 0).mean(), rand_te=rz[rz.test].r.mean(),
                                     btc=te[te.sym == "BTC"].r.mean(), eth=te[te.sym == "ETH"].r.mean(),
                                     long_te=te[te.side > 0].r.mean(), short_te=te[te.side < 0].r.mean()))
    R = pd.DataFrame(rows)
    print("■ 1. 조건을 강하게 할수록 (전체 봉 합계, 검증 구간 평균 R · 거래 수)")
    for exit_name in ("추적 3ATR", "고정 2R"):
        print(f"  [{exit_name}]")
        for gname, gvals in GAPS.items():
            g = R[(R.exit == exit_name) & (R.gap == gname) & (R.tf == "전체")]
            print(f"   {gname} → " + "  ".join(f"{v}ATR↑" for v in gvals) + "   (행: OB 꼬리 0 / 0.3 / 0.5 이상)")
            for w in WICKS:
                cells = []
                for v in gvals:
                    z = g[(g.wick == w) & (g.gv == v)]
                    cells.append(f"{z.r_te.iat[0]:+.3f}R({z.n_te.iat[0]:5})" if len(z) else "      –       ")
                print(f"     꼬리≥{w:.1f} | " + " | ".join(cells))
    print("\n■ 2. 봉별로 설계 구간에서 가장 좋았던 조건 → 검증 구간")
    print(f"  {'봉':6} | {'고른 조건':32} | {'설계 n':>5} {'R':>6} | {'검증 n':>5} {'승률':>4} {'R':>6} {'무작위':>6} {'롱':>6} {'숏':>6} {'BTC':>6} {'ETH':>6} | 판정")
    for tf in TFS:
        g = R[(R.tf == tf) & (R.n_tr >= 60)]
        b = g.loc[g.r_tr.idxmax()]
        ok = b.r_te > 0 and b.n_te >= 50 and b.r_te - b.rand_te >= 0.05 and b.btc > 0 and b.eth > 0
        cond = f"{b.exit}·꼬리≥{b.wick}·{b.gap}≥{b.gv}ATR"
        print(f"  {tf:6} | {cond:32} | {b.n_tr:5} {b.r_tr:+6.3f} | {b.n_te:5} {b.win_te*100:3.0f}% {b.r_te:+6.3f} {b.rand_te:+6.3f}"
              f" {b.long_te:+6.3f} {b.short_te:+6.3f} {b.btc:+6.3f} {b.eth:+6.3f} | {'✅' if ok else '–'}")
    base = R[(R.exit == "추적 3ATR") & (R.wick == 0) & (R.gv == 0) & (R.gap == "FVG 크기")]
    print("\n■ 3. 조건 없음(기본) 검증 구간: " + " · ".join(f"{t.tf} {t.r_te:+.3f}R" for t in base.itertuples()))
    print("\n■ 4. 검증 구간 상위 5개 (봉별, 30건 이상 · 참고만, 과최적화 주의)")
    for t in R[(R.n_te >= 30) & (R.tf != "전체")].sort_values("r_te", ascending=False).head(5).itertuples():
        print(f"  {t.tf} {t.exit}·꼬리≥{t.wick}·{t.gap}≥{t.gv}ATR | 설계 {t.r_tr:+.3f} ({t.n_tr}) 검증 {t.r_te:+.3f} ({t.n_te}) 무작위 {t.rand_te:+.3f}")


if __name__ == "__main__":
    main()
