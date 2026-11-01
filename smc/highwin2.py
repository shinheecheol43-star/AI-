"""고승률 전략 2차 탐색: 1차(highwin.py)가 2022년 장세 전환에서 무너진 것을 고친다. 규칙은 결과를 보기 전에 정했다.

바꾼 점
  ① 일봉 장세 필터: 전날까지의 일봉으로 '상승장' = 종가 > SMA200 이고 SMA50 > SMA200 → 롱(눌림 매수)만
                                         '하락장' = 종가 < SMA200 이고 SMA50 < SMA200 → 숏(반등 매도)만
     (같은 봉 추세 필터도 같이 쓸지 말지 비교)
  ② 일봉 추가 (보유 5·10일)
  ③ 고르는 조건 강화 (설계 구간 ~2021 만):
     거래 ≥ 100 (일봉 ≥ 40), 승률 ≥ 기준(75% / 85%), 기대값 > 0, BTC·ETH 각각 > 0,
     설계 4개 연도(2018~2021) 중 3개 이상 기대값 > 0
  ④ 레버리지 1·2·3·5배 중 설계 구간 복리 결과가 가장 좋은 것을 고르고 검증 구간에 그대로 적용
진입·청산·비용은 highwin.py 와 같다.
판정 (검증 구간 2022~): 승률 ≥ 기준, 기대값 > 0, BTC·ETH 둘 다 > 0, 고른 레버리지 계좌 최대 낙폭 > −30%

사용:  python -m smc.highwin2
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from itertools import product

import numpy as np
import pandas as pd

from .daytrade import SPLIT
from .highwin import CONDS, STOPS, SYMS, TARGETS, conds, frame, lev_curve, m5, trades
from .data import resample

TFS = {"15min": (16, 48), "1h": (12, 48), "4h": (6, 24), "1D": (5, 10)}
LEVS = (1.0, 2.0, 3.0, 5.0)


@lru_cache(maxsize=None)
def regime(sym: str) -> pd.Series:
    d = resample(m5(sym), "1D").set_index("time").close
    s50, s200 = d.rolling(50).mean(), d.rolling(200).mean()
    r = pd.Series(0, index=d.index)
    r[(d > s200) & (s50 > s200)] = 1
    r[(d < s200) & (s50 < s200)] = -1
    r.index = r.index + pd.Timedelta("1D")              # D 일 종가는 D+1 일 00:00 부터 사용
    return r


def job(cfg):
    tf, cond, same_tf_trend, side = cfg
    per = {}
    for sym in SYMS:
        d = frame(sym, tf)
        cs, trend = conds(d, side)
        reg = regime(sym).reindex(d.index, method="ffill").fillna(0).to_numpy()
        m = cs[cond] & (reg == side) & (trend if same_tf_trend else True)
        per[sym] = (d, np.flatnonzero(m))
    out = []
    for tgt, b, hold in product(TARGETS, STOPS, TFS[tf]):
        x = pd.concat([trades(d, idx, side, tgt, b, hold).assign(symbol=sym) for sym, (d, idx) in per.items()],
                      ignore_index=True)
        if len(x) >= 30:
            out.append(((tf, cond, same_tf_trend, side, tgt, b, hold), x))
    return out


def summary(x: pd.DataFrame, lev: float) -> dict:
    if not len(x):
        return dict(n=0, win=np.nan, ev=np.nan, btc=np.nan, eth=np.nan, g=np.nan, mdd=np.nan, cagr=np.nan)
    g, mdd = lev_curve(x, lev)
    yrs = max((x.exit.max() - x.time.min()).days / 365.25, 0.25)
    return dict(n=len(x), win=(x.ret > 0).mean(), ev=x.ret.mean(), btc=x[x.symbol == "BTC"].ret.mean(),
                eth=x[x.symbol == "ETH"].ret.mean(), g=g, mdd=mdd, cagr=max(g, 1e-9) ** (1 / yrs) - 1)


def main():
    cfgs = list(product(TFS, CONDS, (False, True), (1, -1)))
    with ProcessPoolExecutor(4) as pool:
        res = [r for chunk in pool.map(job, cfgs, chunksize=2) for r in chunk]
    rows = []
    for key, x in res:
        tr, te = x[x.time < SPLIT], x[x.time >= SPLIT]
        if len(tr) < 30:
            continue
        yr = tr.groupby(tr.time.dt.year).ret.mean()
        best_lev = max(LEVS, key=lambda v: lev_curve(tr, v)[0])
        a, b = summary(tr, best_lev), summary(te, best_lev)
        rows.append(dict(zip(("tf", "cond", "trend", "side", "tgt", "stop", "hold"), key), lev=best_lev,
                         good_years=int((yr > 0).sum()), **{f"{k}_tr": v for k, v in a.items()},
                         **{f"{k}_te": v for k, v in b.items()}, x=x))
    R = pd.DataFrame(rows)
    print(f"탐색한 설정 {len(R)}개 · 일봉 장세 필터 적용 (상승장 롱 / 하락장 숏) · 설계 ~2021 / 검증 2022~\n")
    for wmin in (0.85, 0.75):
        min_n = np.where(R.tf == "1D", 40, 100)
        sel = R[(R.n_tr >= min_n) & (R.win_tr >= wmin) & (R.ev_tr > 0) & (R.btc_tr > 0) & (R.eth_tr > 0) & (R.good_years >= 3)]
        print(f"■ 승률 기준 {wmin*100:.0f}%: 설계 조건 통과 {len(sel)}개 → 설계 복리 상위 10개의 검증 구간")
        print(f"{'봉':5} {'진입':9} {'추세':2} {'방향':2} {'목표':5} {'손절':4} {'보유':3} {'레버':4} | {'설계 n':>5} {'승률':>4} {'기대값':>7} {'연':>6} {'낙폭':>5} |"
              f" {'검증 n':>5} {'승률':>4} {'기대값':>7} {'BTC':>7} {'ETH':>7} {'연':>6} {'낙폭':>5} | 판정")
        for t in sel.sort_values("g_tr", ascending=False).head(10).itertuples():
            ok = t.win_te >= wmin and t.ev_te > 0 and t.btc_te > 0 and t.eth_te > 0 and t.mdd_te > -0.30
            print(f"{t.tf:5} {t.cond:9} {'O' if t.trend else '-':2} {'롱' if t.side > 0 else '숏':2} {str(t.tgt):5} {t.stop:4} {t.hold:3} {t.lev:3.0f}배 |"
                  f" {t.n_tr:5} {t.win_tr*100:3.0f}% {t.ev_tr*100:+6.3f}% {t.cagr_tr*100:+5.0f}% {t.mdd_tr*100:4.0f}% |"
                  f" {t.n_te:5} {t.win_te*100:3.0f}% {t.ev_te*100:+6.3f}% {t.btc_te*100:+6.3f}% {t.eth_te*100:+6.3f}%"
                  f" {t.cagr_te*100:+5.0f}% {t.mdd_te*100:4.0f}% | {'✅' if ok else '–'}")
        print()
    # 통과한 것 자세히
    allsel = R[(R.n_tr >= np.where(R.tf == "1D", 40, 100)) & (R.win_tr >= 0.75) & (R.ev_tr > 0) & (R.btc_tr > 0)
               & (R.eth_tr > 0) & (R.good_years >= 3)]
    passed = allsel[(allsel.win_te >= 0.75) & (allsel.ev_te > 0) & (allsel.btc_te > 0) & (allsel.eth_te > 0) & (allsel.mdd_te > -0.30)]
    print(f"■ 설계 조건을 통과한 {len(allsel)}개 중 검증 구간도 통과: {len(passed)}개 ({len(passed)/max(len(allsel),1)*100:.0f}%)")
    print("  (무작위로 뽑아도 일부는 통과하므로, 통과 비율과 이웃 설정의 일관성을 같이 본다)")
    for t in passed.sort_values("cagr_te", ascending=False).head(12).itertuples():
        x = t.x[t.x.time >= SPLIT]
        yr = x.groupby(x.time.dt.year).ret.agg(["count", "mean"])
        ys = " ".join(f"{y}:{m*100:+.2f}%({n})" for y, (n, m) in yr.iterrows())
        print(f"  {t.tf} {t.cond} {'추세O' if t.trend else '추세-'} {'롱' if t.side > 0 else '숏'} 목표{t.tgt} 손절{t.stop} 보유{t.hold} {t.lev:.0f}배 |"
              f" 승률 {t.win_te*100:.0f}% 연 {t.cagr_te*100:+.0f}% 낙폭 {t.mdd_te*100:.0f}% | {ys}")
    R.drop(columns="x").to_csv("/tmp/highwin2.csv", index=False)
    pd.to_pickle(passed, "/tmp/highwin2_passed.pkl")


if __name__ == "__main__":
    main()
