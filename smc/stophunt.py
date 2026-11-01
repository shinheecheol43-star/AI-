"""스탑헌팅(유동성 사냥) 반전 매매 검증 (15분·1시간봉, BTC·ETH). 규칙은 결과를 보기 전에 정했다.

손절이 몰리는 자리(레벨) — 롱 기준 (숏은 고점 쪽으로 거꾸로)
  PDL   전날(UTC) 저가
  SWING 최근 96봉 최저가 (직전 3봉 제외 = 이미 만들어진 바닥)
  ASIA  오늘 아시아 시간(UTC 0~8시) 저가 — 런던·뉴욕 시간(8~20시)에 쓸고 올라올 때만
신호: 봉의 저가가 레벨 아래로 찍고(스탑 사냥), 종가는 레벨 위로 마감 → 다음 봉 시가 롱
  꼬리 조건 '강함' = 아래꼬리가 봉 전체 길이의 50% 이상
  장세 필터 = 일봉 상승장(전날까지 SMA50>SMA200 & 종가>SMA200)에서만 롱 (숏은 하락장)
  같은 레벨은 하루 한 번만
손절 = 사냥한 저점 − 0.1 ATR,  목표 1R · 2R · 3R · 반대편(전날 고가/최근 96봉 고가/아시아 고가)
최대 보유 15분봉 48봉(12시간), 1시간봉 24봉(하루). 같은 봉에서 손절·목표 둘 다면 손절.
비용: 진입·손절 0.075%, 목표 지정가 0.02% (R 로 환산)
비교 기준: 같은 개수의 무작위 시점에 같은 손절 폭(신호들의 손절 폭을 섞어 씀)으로 들어간 결과
판정 (미리 정함): 설계(~2021)에서 고른 설정으로 검증(2022~) 평균 R > 0, 100건 이상,
  무작위보다 0.05R 이상 높음, BTC·ETH 둘 다 > 0

사용:  python -m smc.stophunt
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from itertools import product

import numpy as np
import pandas as pd

from .daytrade import SPLIT
from .highwin import MAKER, TAKER, frame
from .highwin2 import regime

SYMS = ("BTC", "ETH")
HOLD = {"15min": 48, "1h": 24}
LEVELS = ("PDL", "SWING", "ASIA")
TARGETS = (1.0, 2.0, 3.0, "opp")


@lru_cache(maxsize=None)
def levels(sym: str, tf: str, side: int) -> dict:
    d = frame(sym, tf)
    s = side
    lo = (d.low if s > 0 else -d.high)
    hi = (d.high if s > 0 else -d.low)
    day = d.index.floor("1D")
    dl = lo.groupby(day).min()
    dh = hi.groupby(day).max()
    pdl = pd.Series(day, index=d.index).map(dl.shift(1))
    pdh = pd.Series(day, index=d.index).map(dh.shift(1))
    nsw = 96 if tf == "15min" else 72
    sw_l = lo.shift(3).rolling(nsw).min()
    sw_h = hi.shift(3).rolling(nsw).max()
    hour = d.index.hour
    asia = pd.Series(np.where(hour < 8, lo, np.nan), index=d.index)
    asia_l = pd.Series(np.where(hour >= 8, asia.groupby(day).transform("min"), np.nan), index=d.index)
    ah = pd.Series(np.where(hour < 8, hi, np.nan), index=d.index)
    asia_h = pd.Series(np.where(hour >= 8, ah.groupby(day).transform("max"), np.nan), index=d.index)
    asia_l[(hour >= 20)] = np.nan
    return {"PDL": (pdl, pdh), "SWING": (sw_l, sw_h), "ASIA": (asia_l, asia_h)}


def signals(sym, tf, side, level, wick, use_reg):
    d = frame(sym, tf)
    s = side
    lo = (d.low if s > 0 else -d.high).to_numpy()
    c = (d.close * s).to_numpy()
    lv, opp = (x.to_numpy() for x in levels(sym, tf, side)[level])
    rng = np.abs(d.high - d.low).to_numpy()
    lower_wick = np.minimum(c, (d.open * s).to_numpy()) - lo
    m = (lo < lv) & (c > lv) & ~np.isnan(lv)
    if wick:
        m &= lower_wick >= 0.5 * np.where(rng > 0, rng, np.inf)
    if use_reg:
        reg = regime(sym).reindex(d.index, method="ffill").fillna(0).to_numpy()
        m &= reg == side
    idx = np.flatnonzero(m)
    # 같은 레벨 하루 한 번
    day = d.index.floor("1D").to_numpy()
    keep, seen = [], set()
    for i in idx:
        key = (day[i], lv[i])
        if key in seen:
            continue
        seen.add(key)
        keep.append(i)
    idx = np.array(keep, int)
    return idx, lo, opp


def outcomes(sym, tf, side, idx, stop_px, tgt_spec, opp):
    d = frame(sym, tf)
    hold = HOLD[tf]
    s = side
    h = (d.high if s > 0 else -d.low).to_numpy()
    l = (d.low if s > 0 else -d.high).to_numpy()
    o, c = (d.open * s).to_numpy(), (d.close * s).to_numpy()
    ok = idx + 1 + hold < len(d)
    idx, stop_px = idx[ok], stop_px[ok]
    e = idx + 1
    entry = o[e]
    dist = entry - stop_px
    good = dist > 0
    idx, e, entry, stop_px, dist = idx[good], e[good], entry[good], stop_px[good], dist[good]
    if tgt_spec == "opp":
        tgt = opp[idx]
        g2 = np.isfinite(tgt) & (tgt > entry)
        idx, e, entry, stop_px, dist, tgt = idx[g2], e[g2], entry[g2], stop_px[g2], dist[g2], tgt[g2]
    else:
        tgt = entry + tgt_spec * dist
    if not len(idx):
        return pd.DataFrame(columns=["time", "r", "symbol"])
    win = e[:, None] + np.arange(hold)[None, :]
    big = hold + 1
    hs = l[win] <= stop_px[:, None]
    ht = h[win] >= tgt[:, None]
    fs = np.where(hs.any(1), hs.argmax(1), big)
    ft = np.where(ht.any(1), ht.argmax(1), big)
    rows = np.arange(len(e))
    spx = np.minimum(stop_px, o[win][rows, np.minimum(fs, hold - 1)])
    last = c[e + hold - 1]
    px = np.where(fs <= ft, np.where(fs < big, spx, last), tgt)
    px = np.where((fs >= big) & (ft >= big), last, px)
    cost = (TAKER + np.where(ft < fs, MAKER, TAKER)) * np.abs(entry)
    r = (px - entry - cost) / dist
    ex = e + np.minimum(np.minimum(fs, ft), hold - 1)
    keep, busy = [], -1
    for t in range(len(e)):
        if idx[t] <= busy:
            continue
        keep.append(t)
        busy = ex[t]
    k = np.array(keep, int)
    return pd.DataFrame({"time": d.index[e[k]], "r": r[k], "stop_pct": (dist / np.abs(entry))[k], "symbol": sym})


def job(cfg):
    tf, side, level, wick, use_reg = cfg
    res = []
    per = {}
    for sym in SYMS:
        d = frame(sym, tf)
        idx, lo, opp = signals(sym, tf, side, level, wick, use_reg)
        stop_px = lo[idx] - 0.1 * d.atr.to_numpy()[idx]
        per[sym] = (idx, stop_px, opp, lo)
    for tgt in TARGETS:
        xs, rs = [], []
        for sym, (idx, stop_px, opp, lo) in per.items():
            d = frame(sym, tf)
            x = outcomes(sym, tf, side, idx, stop_px, tgt, opp)
            xs.append(x)
            # 무작위: 같은 개수, 신호들의 손절 폭(%)을 섞어서
            rng = np.random.default_rng(11)
            n = max(len(idx), 300)
            ridx = np.sort(rng.choice(np.arange(300, len(d) - HOLD[tf] - 2), n, replace=False))
            o = (d.open * side).to_numpy()
            pct = (o[np.minimum(idx + 1, len(d) - 1)] - stop_px) / np.abs(o[np.minimum(idx + 1, len(d) - 1)]) if len(idx) else np.array([0.005])
            pct = pct[pct > 0] if (pct > 0).any() else np.array([0.005])
            rstop = o[ridx + 1] - np.abs(o[ridx + 1]) * rng.choice(pct, n)
            ropp = np.full(len(d), np.nan)
            ropp[ridx] = o[ridx + 1] + np.abs(o[ridx + 1]) * rng.choice(pct, n) * 2   # 반대편 목표 대용: 2R
            rs.append(outcomes(sym, tf, side, ridx, rstop, tgt if tgt != "opp" else "opp", ropp if tgt == "opp" else opp))
        res.append(((tf, side, level, wick, use_reg, tgt), pd.concat(xs, ignore_index=True), pd.concat(rs, ignore_index=True)))
    return res


def main():
    cfgs = list(product(HOLD, (1, -1), LEVELS, (False, True), (False, True)))
    with ProcessPoolExecutor(4) as pool:
        out = [r for chunk in pool.map(job, cfgs) for r in chunk]
    rows = []
    for key, x, rx in out:
        tr, te = x[x.time < SPLIT], x[x.time >= SPLIT]
        rows.append(dict(zip(("tf", "side", "level", "wick", "reg", "tgt"), key),
                         n_tr=len(tr), r_tr=tr.r.mean(), win_tr=(tr.r > 0).mean(),
                         n_te=len(te), r_te=te.r.mean(), win_te=(te.r > 0).mean(),
                         rand_te=rx[rx.time >= SPLIT].r.mean(), stop_te=te.stop_pct.median(),
                         btc=te[te.symbol == "BTC"].r.mean(), eth=te[te.symbol == "ETH"].r.mean(), x=x))
    R = pd.DataFrame(rows)
    print("스탑헌팅 반전 · BTC·ETH · 설계 ~2021 / 검증 2022~ · R 은 비용 뺀 값\n")
    print("■ 1. 레벨·봉·방향별로 설계 구간에서 고른 설정 → 검증 구간")
    print(f"{'봉':5} {'방향':2} {'레벨':5} | {'고른 설정':20} | {'설계 n':>5} {'R':>6} | {'검증 n':>5} {'승률':>4} {'R':>6} {'무작위':>6} {'BTC':>6} {'ETH':>6} {'손절폭':>6} | 판정")
    for (tf, side, level), g in R.groupby(["tf", "side", "level"], sort=False):
        g = g[g.n_tr >= 60]
        if not len(g):
            continue
        b = g.loc[g.r_tr.idxmax()]
        ok = b.r_te > 0 and b.n_te >= 100 and b.r_te - b.rand_te >= 0.05 and b.btc > 0 and b.eth > 0
        cfg = f"꼬리{'O' if b.wick else '-'} 장세{'O' if b.reg else '-'} 목표{b.tgt}"
        print(f"{tf:5} {'롱' if side > 0 else '숏':2} {level:5} | {cfg:20} | {b.n_tr:5} {b.r_tr:+6.3f} | {b.n_te:5} {b.win_te*100:3.0f}%"
              f" {b.r_te:+6.3f} {b.rand_te:+6.3f} {b.btc:+6.3f} {b.eth:+6.3f} {b.stop_te*100:5.2f}% | {'✅' if ok else '–'}")
    print("\n■ 2. 전체 평균: 스탑헌팅 신호 vs 무작위 (검증 구간, 같은 목표 규칙)")
    for tgt, g in R.groupby("tgt"):
        print(f"  목표 {tgt}: 신호 평균 {g.r_te.mean():+.3f}R (승률 {g.win_te.mean()*100:.0f}%) · 무작위 {g.rand_te.mean():+.3f}R")
    print("\n■ 3. 검증 구간 상위 5개 (참고만)")
    for t in R[R.n_te >= 100].sort_values("r_te", ascending=False).head(5).itertuples():
        print(f"  {t.tf} {'롱' if t.side > 0 else '숏'} {t.level} 꼬리{'O' if t.wick else '-'} 장세{'O' if t.reg else '-'} 목표{t.tgt} |"
              f" 설계 {t.r_tr:+.3f} ({t.n_tr}) 검증 {t.r_te:+.3f} ({t.n_te}) 승률 {t.win_te*100:.0f}%")
    R.drop(columns="x").to_csv("/tmp/stophunt.csv", index=False)


if __name__ == "__main__":
    main()
