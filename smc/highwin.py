"""승률 85~90% 이상 + 기대값 플러스 + 레버리지 5배를 견디는 전략 탐색 (BTC·ETH, 15분·1시간·4시간봉).

규칙은 결과를 보기 전에 정했다.
진입 (봉 마감 확인 → 다음 봉 시가 시장가, 롱 기준 · 숏은 거꾸로)
  rsi2_10   RSI(2) < 10            rsi2_3    RSI(2) < 3
  rsi14_25  RSI(14) < 25           srsi      스토캐스틱 RSI K < 0.05
  bb25      종가 < 볼린저(20, 2.5σ) 하단
  ema20_2   종가 < EMA20 − 2 ATR   ema20_3   종가 < EMA20 − 3 ATR
  down3/4/5 3·4·5 봉 연속 하락 마감
  drop3/5   최근 4봉 하락폭 ≥ 3·5 ATR
  각각 '추세 필터' 없이 / 있게 (종가 > EMA200 이고 EMA50 > EMA200 = 상승 추세 속 눌림만)
청산 (승률이 높게 나오는 구조)
  목표 a × ATR (a = 0.5·1·1.5, 지정가) 또는 sma5 (종가가 5봉 평균 위로 마감하면 그 종가에 청산)
  손절 b × ATR (b = 3·5·8), 최대 보유 H 봉 (15분 16·48 / 1시간 12·48 / 4시간 6·24) 뒤 종가 청산
비용: 진입 시장가 0.075%(수수료+미끄러짐), 목표 지정가 0.02%, 손절·시간·sma5 청산 0.075%
승리 = 비용 뺀 손익 > 0
고르기 (설계 구간 ~2021 만 사용):
  설계 거래 ≥ 100, 설계 승률 ≥ 85%, 설계 기대값(가격 %) > 0, BTC·ETH 각각 설계 기대값 > 0
  그중 '5배 레버리지 복리 성장'이 가장 큰 순으로 상위 10개
판정 (검증 구간 2022~): 승률 ≥ 85%, 기대값 > 0, BTC·ETH 둘 다 > 0, 5배 계좌 최대 낙폭 > −50%

사용:  python -m smc.highwin
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from itertools import product

import numpy as np
import pandas as pd

from .daytrade import SPLIT
from .data import ARCHIVE, load_csv, resample

TAKER, MAKER = 0.00075, 0.0002
SYMS = ("BTC", "ETH")
TFS = {"15min": (16, 48), "1h": (12, 48), "4h": (6, 24)}
TARGETS = (0.5, 1.0, 1.5, "sma5")
STOPS = (3.0, 5.0, 8.0)
CONDS = ("rsi2_10", "rsi2_3", "rsi14_25", "srsi", "bb25", "ema20_2", "ema20_3", "down3", "down4", "down5", "drop3", "drop5")
LEV = 5.0


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(c, n):
    dl = c.diff()
    g = dl.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    lo = (-dl.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + g / lo)


@lru_cache(maxsize=None)
def m5(sym):
    return load_csv(ARCHIVE / f"{sym}USDT_5m.csv.gz")


@lru_cache(maxsize=None)
def frame(sym: str, tf: str) -> pd.DataFrame:
    d = resample(m5(sym), tf).set_index("time")
    d = d[d.index >= pd.Timestamp("2018-01-01", tz="UTC")].copy()
    c = d.close
    pc = c.shift(1)
    tr = pd.concat([d.high - d.low, (d.high - pc).abs(), (d.low - pc).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    d["e20"], d["e50"], d["e200"] = ema(c, 20), ema(c, 50), ema(c, 200)
    d["sma5"] = c.rolling(5).mean()
    m, sd = c.rolling(20).mean(), c.rolling(20).std()
    d["bbl"], d["bbu"] = m - 2.5 * sd, m + 2.5 * sd
    d["r2"], r14 = rsi(c, 2), rsi(c, 14)
    d["r14"] = r14
    k = ((r14 - r14.rolling(14).min()) / (r14.rolling(14).max() - r14.rolling(14).min())).rolling(3).mean()
    d["k"] = k
    return d.dropna()


def conds(d: pd.DataFrame, side: int) -> dict[str, np.ndarray]:
    c = d.close
    if side > 0:
        dn = c < c.shift(1)
        mv = (c.shift(4) - c) / d.atr
        r = {"rsi2_10": d.r2 < 10, "rsi2_3": d.r2 < 3, "rsi14_25": d.r14 < 25, "srsi": d.k < 0.05, "bb25": c < d.bbl,
             "ema20_2": c < d.e20 - 2 * d.atr, "ema20_3": c < d.e20 - 3 * d.atr}
        trend = (c > d.e200) & (d.e50 > d.e200)
    else:
        dn = c > c.shift(1)
        mv = (c - c.shift(4)) / d.atr
        r = {"rsi2_10": d.r2 > 90, "rsi2_3": d.r2 > 97, "rsi14_25": d.r14 > 75, "srsi": d.k > 0.95, "bb25": c > d.bbu,
             "ema20_2": c > d.e20 + 2 * d.atr, "ema20_3": c > d.e20 + 3 * d.atr}
        trend = (c < d.e200) & (d.e50 < d.e200)
    for n in (3, 4, 5):
        r[f"down{n}"] = dn.rolling(n).sum() == n
    r["drop3"], r["drop5"] = mv >= 3, mv >= 5
    return {k: v.fillna(False).to_numpy(bool) for k, v in r.items()}, trend.to_numpy(bool)


def trades(d, idx, side, tgt, b, hold) -> pd.DataFrame:
    s = side
    h = (d.high if s > 0 else -d.low).to_numpy()
    l = (d.low if s > 0 else -d.high).to_numpy()
    o, c, sma = (d.open * s).to_numpy(), (d.close * s).to_numpy(), (d.sma5 * s).to_numpy()
    atr = d.atr.to_numpy()
    idx = idx[idx + 1 + hold < len(d)]
    if not len(idx):
        return pd.DataFrame()
    e = idx + 1
    entry = o[e]
    stop = entry - b * atr[idx]
    win = e[:, None] + np.arange(hold)[None, :]
    H, L, C, O = h[win], l[win], c[win], o[win]
    big = hold + 1
    hit_s = L <= stop[:, None]
    fs = np.where(hit_s.any(1), hit_s.argmax(1), big)
    if tgt == "sma5":
        hit_t = C > sma[win]
        ft = np.where(hit_t.any(1), hit_t.argmax(1), big)
        tpx = C[np.arange(len(e)), np.minimum(ft, hold - 1)]
        tcost = TAKER
    else:
        tp = entry + tgt * atr[idx]
        hit_t = H >= tp[:, None]
        ft = np.where(hit_t.any(1), hit_t.argmax(1), big)
        tpx = tp
        tcost = MAKER
    rows = np.arange(len(e))
    spx = np.minimum(stop, O[rows, np.minimum(fs, hold - 1)])
    last = C[:, -1]
    px = np.where(fs <= ft, np.where(fs < big, spx, last), tpx)
    px = np.where((fs >= big) & (ft >= big), last, px)
    xc = np.where((ft < fs), tcost, TAKER)
    ret = (px - entry) / entry - TAKER - xc            # 가격 기준 순수익 (1배)
    ex = e + np.minimum(np.minimum(fs, ft), hold - 1)
    keep, busy = [], -1
    for t in range(len(e)):
        if idx[t] <= busy:
            continue
        keep.append(t)
        busy = ex[t]
    k = np.array(keep, int)
    return pd.DataFrame({"time": d.index[e[k]], "exit": d.index[ex[k]], "ret": ret[k], "stop_dist": (b * atr[idx] / entry)[k]})


def lev_curve(x: pd.DataFrame, lev: float):
    x = x.sort_values("exit")
    r = np.maximum(x.ret.to_numpy() * lev, -1.0)
    eq = np.cumprod(1 + r)
    peak = np.maximum.accumulate(np.concatenate([[1.0], eq]))[1:]
    return eq[-1] if len(eq) else 1.0, (eq / peak - 1).min() if len(eq) else 0.0


def job(cfg):
    tf, cond, use_trend, side = cfg
    out = []
    per = {}
    for sym in SYMS:
        d = frame(sym, tf)
        cs, trend = conds(d, side)
        m = cs[cond] & (trend if use_trend else True)
        per[sym] = (d, np.flatnonzero(m))
    for tgt, b, hold in product(TARGETS, STOPS, TFS[tf]):
        xs = [trades(d, idx, side, tgt, b, hold).assign(symbol=sym) for sym, (d, idx) in per.items()]
        x = pd.concat(xs, ignore_index=True)
        if len(x) < 50:
            continue
        out.append(((tf, cond, use_trend, side, tgt, b, hold), x))
    return out


def stats(x):
    if not len(x):
        return dict(n=0, win=np.nan, ev=np.nan, btc=np.nan, eth=np.nan, g5=np.nan, mdd5=np.nan)
    g5, mdd5 = lev_curve(x, LEV)
    return dict(n=len(x), win=(x.ret > 0).mean(), ev=x.ret.mean(), btc=x[x.symbol == "BTC"].ret.mean(),
                eth=x[x.symbol == "ETH"].ret.mean(), g5=g5, mdd5=mdd5)


def main():
    cfgs = list(product(TFS, CONDS, (False, True), (1, -1)))
    with ProcessPoolExecutor(4) as pool:
        res = [r for chunk in pool.map(job, cfgs, chunksize=2) for r in chunk]
    rows = []
    for key, x in res:
        tr, te = x[x.time < SPLIT], x[x.time >= SPLIT]
        a, b = stats(tr), stats(te)
        rows.append(dict(zip(("tf", "cond", "trend", "side", "tgt", "stop", "hold"), key),
                         **{f"{k}_tr": v for k, v in a.items()}, **{f"{k}_te": v for k, v in b.items()},
                         yrs_te=(te.exit.max() - te.time.min()).days / 365.25 if len(te) else np.nan, x=x))
    R = pd.DataFrame(rows)
    print(f"탐색한 설정 {len(R)}개 (봉 3 × 진입 12 × 추세필터 2 × 방향 2 × 청산 24)\n")

    hw = R[R.win_tr >= 0.85]
    print("■ 1. 설계 구간 승률 85% 이상인 설정")
    print(f"  {len(hw)}개 · 그중 기대값 플러스 {int((hw.ev_tr > 0).sum())}개 · 검증 구간에서도 승률 85%↑ & 기대값 플러스 "
          f"{int(((hw.win_te >= 0.85) & (hw.ev_te > 0)).sum())}개")
    for tf in TFS:
        g = R[R.tf == tf]
        print(f"  {tf:5}: 승률 85%↑ {int((g.win_tr >= .85).sum()):4}개, 평균 기대값 {g[g.win_tr >= .85].ev_tr.mean()*100:+.3f}%"
              f" (승률 85%↑ 설정들의 평균 손절폭 {g[g.win_tr >= .85].stop.mean():.1f} ATR)")

    sel = R[(R.n_tr >= 100) & (R.win_tr >= 0.85) & (R.ev_tr > 0) & (R.btc_tr > 0) & (R.eth_tr > 0)]
    sel = sel.sort_values("g5_tr", ascending=False).head(10)
    print(f"\n■ 2. 설계 구간 기준으로 고른 상위 {len(sel)}개 → 검증 구간 (기대값 = 거래당 가격 수익, 비용 뺀 값)")
    print(f"{'봉':5} {'진입':9} {'추세':2} {'방향':2} {'목표':5} {'손절':4} {'보유':4} | {'설계 n':>6} {'승률':>4} {'기대값':>7} {'5배 성장':>9} |"
          f" {'검증 n':>6} {'승률':>4} {'기대값':>7} {'BTC':>7} {'ETH':>7} {'5배 결과':>9} {'5배 낙폭':>7} | 판정")
    for t in sel.itertuples():
        ok = t.win_te >= 0.85 and t.ev_te > 0 and t.btc_te > 0 and t.eth_te > 0 and t.mdd5_te > -0.5
        print(f"{t.tf:5} {t.cond:9} {'O' if t.trend else '-':2} {'롱' if t.side > 0 else '숏':2} {str(t.tgt):5} {t.stop:4} {t.hold:4} |"
              f" {t.n_tr:6} {t.win_tr*100:3.0f}% {t.ev_tr*100:+6.3f}% {t.g5_tr:8.2f}배 |"
              f" {t.n_te:6} {t.win_te*100:3.0f}% {t.ev_te*100:+6.3f}% {t.btc_te*100:+6.3f}% {t.eth_te*100:+6.3f}% {t.g5_te:8.2f}배"
              f" {t.mdd5_te*100:6.0f}% | {'✅' if ok else '–'}")

    print("\n■ 3. 검증 구간에서 승률 85%↑ & 5배 결과가 가장 좋았던 설정 (참고만: 검증 구간으로 고르면 과최적화)")
    top = R[(R.n_te >= 100) & (R.win_te >= 0.85)].sort_values("g5_te", ascending=False).head(5)
    for t in top.itertuples():
        print(f"  {t.tf:5} {t.cond:9} 추세{'O' if t.trend else '-'} {'롱' if t.side > 0 else '숏'} 목표{t.tgt} 손절{t.stop} 보유{t.hold} |"
              f" 설계 승률 {t.win_tr*100:.0f}% 기대값 {t.ev_tr*100:+.3f}% | 검증 {t.n_te}건 승률 {t.win_te*100:.0f}% 기대값 {t.ev_te*100:+.3f}%"
              f" 5배 {t.g5_te:.2f}배 낙폭 {t.mdd5_te*100:.0f}%")

    print("\n■ 4. 같은 기간 최악의 연속: 상위 설정의 검증 구간 최대 손실 거래 (가격 %, 5배면 × 5)")
    for t in sel.head(5).itertuples():
        x = t.x[t.x.time >= SPLIT]
        print(f"  {t.tf} {t.cond} {'롱' if t.side > 0 else '숏'}: 최대 손실 {x.ret.min()*100:.2f}% (5배 {x.ret.min()*500:.1f}%)"
              f" · 평균 이익 {x[x.ret > 0].ret.mean()*100:.2f}% · 평균 손실 {x[x.ret <= 0].ret.mean()*100:.2f}%")
    R.drop(columns="x").to_csv("/tmp/highwin.csv", index=False)


if __name__ == "__main__":
    main()
