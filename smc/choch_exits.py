"""CHoCH → OB → FVG 리테스트 진입에서 '익절 방식'만 바꿔 보기 (5분·15분·30분·1시간·4시간봉, BTC·ETH, 롱·숏).

진입은 smc.choch_ob_fvg 와 같다 (CHoCH, OB 있음, FVG 에 지정가). 손절은 OB 꼬리(저가) − 0.1 ATR 로 고정.
규칙은 결과를 보기 전에 정했다. 익절 방식 (롱 기준, 숏은 거꾸로)
  직전 고점  : CHoCH 로 깨진 스윙 고점 이전 60봉의 최고가 (하락 구간 위에 쌓인 손절 물량 = 유동성). 진입가 위일 때만
  파동 고점  : 마지막 저점부터 진입 직전까지 상승 파동이 찍은 최고가. 진입가 위일 때만
  추적 2ATR  : 목표 없음. 진입 뒤 최고가 − ATR×2 (최초 손절 아래로는 안 내림)
  추적 3ATR  : 같은 방식, ATR×3
  분할       : 1R 에서 절반 익절, 나머지는 손절을 본절(+수수료)로 올리고 추적 3ATR
  최대 보유  : 목표형은 choch_ob_fvg 와 같음 (5분 288 · 15분 96 · 30분 96 · 1시간 48 · 4시간 30봉),
               추적·분할형은 그 3배 (추세를 길게 따라가도록)
비용: 진입·목표 지정가 0.02%, 손절·추적·시간 청산 0.075%
비교: 같은 손절폭(%)으로 무작위 시점에 들어가 같은 익절 방식을 쓴 결과
       (직전 고점·파동 고점은 신호들의 '목표까지 거리 ÷ 손절폭' 분포를 섞어 씀)
판정 (미리 정함): 봉·방향마다 설계(~2021)에서 고른 설정으로 검증(2022~)
  평균 R > 0, 100건 이상, 무작위보다 0.05R 이상 높음, BTC·ETH 둘 다 > 0

사용:  python -m smc.choch_exits
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from itertools import product

import numpy as np
import pandas as pd

from .bos_choch import arrays
from .choch_ob_fvg import HOLD, SYMS, WAIT, one_at_a_time, setups
from .daytrade import SPLIT
from .highwin import MAKER, TAKER

EXITS = ("직전 고점", "파동 고점", "추적 2ATR", "추적 3ATR", "분할")
PRIOR = 60


def entries(sym, tf, side, S, entry_mode, use_reg, strict):
    idx, o, h, l, c, atr, _ = arrays(sym, tf, side)
    n, hold = len(c), HOLD[tf] * 3
    rows = []
    for s in S:
        if use_reg and not s["reg"]:
            continue
        if strict and not s["bot"] > s["ob_hi"]:
            continue
        stop = s["ob_lo"] - 0.1 * s["atr"]
        limit = s["top"] if entry_mode == "FVG 윗변" else (s["top"] + s["bot"]) / 2
        if not (0.3 * s["atr"] <= limit - stop <= 6 * s["atr"]):
            continue
        e = next((u for u in range(s["start"], min(n - hold - 1, s["start"] + WAIT)) if l[u] <= limit), None)
        if e is None:
            continue
        px = limit if o[e] <= stop else min(limit, o[e])
        lo_i = s["ob"]
        prior_hi = h[max(0, s["t"] - PRIOR):s["t"]].max()          # 돌파 봉 이전 하락 구간의 최고가
        leg_hi = h[lo_i:e].max() if e > lo_i else np.nan              # 진입 직전까지 파동 고점
        rows.append((e, px, stop, prior_hi, leg_hi))
    if not rows:
        return {k: np.array([]) for k in ("e", "px", "stop", "prior", "leg")}
    a = np.array(rows, float)
    return {"e": a[:, 0].astype(int), "px": a[:, 1], "stop": a[:, 2], "prior": a[:, 3], "leg": a[:, 4]}


def simulate(sym, tf, side, e, px, stop, mode, tgt=None):
    """R(비용 포함)와 청산 봉. tgt: 목표형일 때 목표가 배열."""
    idx, o, h, l, c, atr, _ = arrays(sym, tf, side)
    if not len(e):
        return np.array([]), np.array([], int)
    target_mode = mode in ("직전 고점", "파동 고점")
    hold = HOLD[tf] * (1 if target_mode else 3)
    dist = px - stop
    win = e[:, None] + np.arange(hold)[None, :]
    H, L, O, C = h[win], l[win], o[win], c[win]
    rows = np.arange(len(e))
    big = hold + 1
    if target_mode:
        hs = L <= stop[:, None]
        ht = H >= tgt[:, None]
        ht[:, 0] = False
        fs = np.where(hs.any(1), hs.argmax(1), big)
        ft = np.where(ht.any(1), ht.argmax(1), big)
        won = ft < fs
        spx = np.minimum(stop, O[rows, np.minimum(fs, hold - 1)])
        exit_px = np.where(won, tgt, np.where(fs < big, spx, C[:, -1]))
        fee = (MAKER + np.where(won, MAKER, TAKER)) * np.abs(px)
        return (exit_px - px - fee) / dist, e + np.minimum(np.minimum(fs, ft), hold - 1)
    k = 2.0 if mode == "추적 2ATR" else 3.0
    a = atr[e][:, None]
    best = np.maximum.accumulate(H, axis=1)
    prev_best = np.concatenate([px[:, None], best[:, :-1]], axis=1)
    prev_best = np.maximum(prev_best, px[:, None])
    trail = np.maximum(stop[:, None], prev_best - k * a)
    half = 0.0
    if mode == "분할":
        one_r = px + dist
        h1 = H >= one_r[:, None]
        h1[:, 0] = False
        f1 = np.where(h1.any(1), h1.argmax(1), big)
        be = px + 2 * TAKER * np.abs(px)
        after = np.arange(hold)[None, :] > f1[:, None]                 # 1R 닿은 다음 봉부터 본절 이상
        trail = np.where(after, np.maximum(trail, be[:, None]), trail)
        # 1R 전에 손절되면 분할 없음
        hs0 = L <= trail
        fs0 = np.where(hs0.any(1), hs0.argmax(1), big)
        took = f1 < fs0
        half = np.where(took, 0.5 * (dist - (MAKER + MAKER) * np.abs(px)), 0.0)
    hs = L <= trail
    fs = np.where(hs.any(1), hs.argmax(1), big)
    j = np.minimum(fs, hold - 1)
    tp = trail[rows, j]
    exit_px = np.where(fs < big, np.minimum(tp, O[rows, j]), C[:, -1])
    rest = (exit_px - px - (MAKER + TAKER) * np.abs(px))
    if mode == "분할":
        rest = np.where(took, 0.5 * rest, rest)
    return (half + rest) / dist, e + j


def job(cfg):
    tf, side = cfg
    S = {sym: setups(sym, tf, side) for sym in SYMS}
    rng = np.random.default_rng(5)
    out = []
    for entry_mode, use_reg, strict in product(("FVG 윗변", "FVG 중간"), (False, True), (False, True)):
        per = {sym: entries(sym, tf, side, S[sym], entry_mode, use_reg, strict) for sym in SYMS}
        for mode in EXITS:
            xs, rs = [], []
            for sym, d in per.items():
                idx, o, h, l, c, atr, _ = arrays(sym, tf, side)
                e, px, st = d["e"], d["px"], d["stop"]
                tgt = None
                if mode in ("직전 고점", "파동 고점") and len(e):
                    tgt = d["prior"] if mode == "직전 고점" else d["leg"]
                    ok = np.isfinite(tgt) & (tgt > px)
                    e, px, st, tgt = e[ok], px[ok], st[ok], tgt[ok]
                r, ex = simulate(sym, tf, side, e, px, st, mode, tgt)
                kk = one_at_a_time(e, ex) if len(e) else np.array([], int)
                xs.append(pd.DataFrame({"time": idx[e[kk]] if len(kk) else pd.DatetimeIndex([], tz="UTC"), "r": r[kk] if len(kk) else [],
                                        "symbol": sym}))
                # 무작위
                pct = (px - st) / np.abs(px) if len(e) else np.array([0.01])
                ratio = (tgt - px) / (px - st) if tgt is not None and len(e) else np.array([2.0])
                m = max(len(e), 300)
                hold = HOLD[tf] * 3
                re_ = np.sort(rng.choice(np.arange(500, len(c) - hold - 2), m, replace=False))
                rp = o[re_]
                rst = rp - np.abs(rp) * rng.choice(pct, m)
                rt = rp + (rp - rst) * rng.choice(ratio, m) if mode in ("직전 고점", "파동 고점") else None
                rr, rex = simulate(sym, tf, side, re_, rp, rst, mode, rt)
                rk = one_at_a_time(re_, rex)
                rs.append(pd.DataFrame({"time": idx[re_[rk]], "r": rr[rk]}))
            x = pd.concat(xs, ignore_index=True)
            x["time"] = pd.to_datetime(x.time, utc=True)
            x["r"] = x.r.astype(float)
            rx = pd.concat(rs, ignore_index=True)
            tr, te = x[x.time < SPLIT], x[x.time >= SPLIT]
            out.append(dict(tf=tf, side=side, entry=entry_mode, reg=use_reg, strict=strict, exit=mode,
                            n_tr=len(tr), r_tr=tr.r.mean(), n_te=len(te), r_te=te.r.mean(), win_te=(te.r > 0).mean(),
                            rand_te=rx[rx.time >= SPLIT].r.mean(),
                            btc=te[te.symbol == "BTC"].r.mean(), eth=te[te.symbol == "ETH"].r.mean(),
                            yrs=te.groupby(te.time.dt.year).r.mean().round(2).to_dict()))
    return out


def main():
    cfgs = list(product(HOLD, (1, -1)))
    with ProcessPoolExecutor(4) as pool:
        R = pd.DataFrame([r for rows in pool.map(job, cfgs) for r in rows])
    print("CHoCH → OB → FVG 리테스트 · 손절 OB 꼬리 아래 고정 · 익절 방식 비교 · 설계 ~2021 / 검증 2022~ · R 은 비용 뺀 값\n")
    print("■ 1. 익절 방식별 평균 (검증 구간, 모든 진입 설정 평균)")
    print(f"{'봉':6} {'방향':2} | " + " | ".join(f"{m:^16}" for m in EXITS) + f" | {'무작위(추적3)':>12}")
    for (tf, side), g in R.groupby(["tf", "side"], sort=False):
        cells = []
        for m in EXITS:
            z = g[g.exit == m]
            cells.append(f"{z.r_te.mean():+.3f}R {z.win_te.mean()*100:3.0f}%".center(16))
        print(f"{tf:6} {'롱' if side > 0 else '숏':2} | " + " | ".join(cells) + f" | {g[g.exit == '추적 3ATR'].rand_te.mean():+12.3f}")
    print("\n■ 2. 봉·방향별: 설계 구간에서 고른 설정 → 검증 구간")
    print(f"{'봉':6} {'방향':2} | {'고른 설정':30} | {'설계 n':>5} {'R':>6} | {'검증 n':>5} {'승률':>4} {'R':>6} {'무작위':>6} {'BTC':>6} {'ETH':>6} | 판정 | 연도별")
    for (tf, side), g in R.groupby(["tf", "side"], sort=False):
        g2 = g[g.n_tr >= 60]
        if not len(g2):
            continue
        b = g2.loc[g2.r_tr.idxmax()]
        ok = b.r_te > 0 and b.n_te >= 100 and b.r_te - b.rand_te >= 0.05 and b.btc > 0 and b.eth > 0
        cfg = f"{b.exit}·{b.entry}·장세{'O' if b.reg else '-'}·엄격{'O' if b.strict else '-'}"
        ys = " ".join(f"{y}:{v:+.2f}" for y, v in b.yrs.items())
        print(f"{tf:6} {'롱' if side > 0 else '숏':2} | {cfg:30} | {b.n_tr:5} {b.r_tr:+6.3f} | {b.n_te:5} {b.win_te*100:3.0f}%"
              f" {b.r_te:+6.3f} {b.rand_te:+6.3f} {b.btc:+6.3f} {b.eth:+6.3f} | {'✅' if ok else '–'} | {ys}")
    print("\n■ 3. 익절 방식별 '전략 − 무작위' (검증 구간, 모든 봉·방향·설정 평균): 진입 신호가 우위를 주는가")
    for m in EXITS:
        z = R[R.exit == m]
        print(f"  {m:8} 전략 {z.r_te.mean():+.3f}R · 무작위 {z.rand_te.mean():+.3f}R · 차이 {(z.r_te - z.rand_te).mean():+.3f}R")
    print("\n■ 4. 검증 구간 상위 5개 (참고만, 과최적화 주의)")
    for t in R[R.n_te >= 100].sort_values("r_te", ascending=False).head(5).itertuples():
        print(f"  {t.tf} {'롱' if t.side > 0 else '숏'} {t.exit}·{t.entry}·장세{'O' if t.reg else '-'}·엄격{'O' if t.strict else '-'} |"
              f" 설계 {t.r_tr:+.3f} ({t.n_tr}) 검증 {t.r_te:+.3f} ({t.n_te}) 무작위 {t.rand_te:+.3f}")
    R.drop(columns="yrs").to_csv("/tmp/choch_exits.csv", index=False)


if __name__ == "__main__":
    main()
