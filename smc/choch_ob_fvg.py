"""CHoCH → OB → FVG → FVG 리테스트 진입 전략 검증 (5분·15분·30분·1시간·4시간봉, BTC·ETH, 롱·숏).

규칙은 결과를 보기 전에 정했다. 롱 기준 (숏은 가격을 뒤집어 같은 규칙)
  1) CHoCH : 추세가 하락이던 중 봉의 고가가 확정된 직전 스윙 고점(좌우 5봉)을 넘음  (smc.bos_choch.events)
  2) OB    : 그 상승 파동의 출발점(마지막 저점) 이전 5봉 안의 마지막 음봉. 없으면 신호 아님
             '엄격' 조건이면 FVG 아랫변이 OB 고가보다 위 (OB → FVG 순서가 겹치지 않고 위로)
  3) FVG   : 마지막 저점 이후 ~ 돌파 봉 2봉 뒤까지 생긴 첫 상승 FVG (1번 고가 < 3번 저가, 2번 양봉)
  4) 진입  : CHoCH 와 FVG 가 모두 확인된 다음 봉부터 20봉 동안 FVG 에 지정가
             진입가 = FVG 윗변 또는 FVG 중간(50%). 손절가는 진입가 아래라 가격이 손절까지 가면 반드시 먼저 체결됨
  손절    : OB 저가 − 0.1 ATR  또는  FVG 아랫변 − 0.1 ATR
            (손절폭이 0.3 ATR 미만이거나 6 ATR 초과면 건너뜀)
  목표    : 1.5R · 2R · 3R (지정가).  최대 보유 5분 288봉 · 15분 96봉 · 30분 96봉 · 1시간 48봉 · 4시간 30봉
  체결 봉에서는 손절만 확인(보수적), 같은 봉에서 손절·목표 둘 다면 손절.  코인마다 한 번에 한 거래
  필터    : 없음 / 일봉 장세(전날까지 SMA50·200)와 같은 방향
비용: 지정가 0.02%(진입·목표), 손절·시간 청산 0.075%
비교: 같은 손절폭(%)·같은 목표로 무작위 시점에 지정가처럼 들어간 결과
판정 (미리 정함): 봉·방향마다 설계(~2021)에서 고른 설정으로 검증(2022~)
  평균 R > 0, 100건 이상, 무작위보다 0.05R 이상 높음, BTC·ETH 둘 다 > 0

사용:  python -m smc.choch_ob_fvg
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from itertools import product

import numpy as np
import pandas as pd

from .bos_choch import arrays, events, fvgs_up
from .daytrade import SPLIT
from .highwin import MAKER, TAKER

SYMS = ("BTC", "ETH")
HOLD = {"5min": 288, "15min": 96, "30min": 96, "1h": 48, "4h": 30}
K, WAIT = 5, 20
TARGETS = (1.5, 2.0, 3.0)


def setups(sym: str, tf: str, side: int) -> list[dict]:
    """CHoCH + OB + FVG 가 모두 있는 신호 (가격은 side 기준으로 뒤집힌 공간)."""
    idx, o, h, l, c, atr, reg = arrays(sym, tf, side)
    n = len(c)
    out = []
    for t, piv, lvl, prot, kind, _ in events(sym, tf, side, K):
        if kind != "CHoCH":
            continue
        lo_i = piv + int(np.argmin(l[piv:t + 1]))
        obs = [k for k in range(max(0, lo_i - 5), lo_i + 1) if c[k] < o[k]]
        if not obs:
            continue
        ob = obs[-1]
        z = fvgs_up(h, l, o, c, lo_i + 2, min(t + 2, n - 1))
        if not z:
            continue
        fi, top, bot = z[0]
        out.append(dict(t=t, ob=ob, ob_lo=l[ob], ob_hi=h[ob], fi=fi, top=top, bot=bot, start=max(t, fi) + 1,
                        atr=atr[t], reg=bool(reg[t])))
    return out


def run(sym, tf, side, S, stop_mode, entry_mode, use_reg, strict):
    """설정 하나의 진입 목록 → (진입 봉, 진입가, 손절가) 배열."""
    idx, o, h, l, c, atr, _ = arrays(sym, tf, side)
    n, hold = len(c), HOLD[tf]
    E, P, ST = [], [], []
    for s in S:
        if use_reg and not s["reg"]:
            continue
        if strict and not s["bot"] > s["ob_hi"]:
            continue
        stop = (s["ob_lo"] if stop_mode == "OB 아래" else s["bot"]) - 0.1 * s["atr"]
        limit = s["top"] if entry_mode == "FVG 윗변" else (s["top"] + s["bot"]) / 2
        if not (0.3 * s["atr"] <= limit - stop <= 6 * s["atr"]):
            continue
        e = None
        for u in range(s["start"], min(n - hold - 1, s["start"] + WAIT)):
            if l[u] <= limit:
                e = u
                break
        if e is None:
            continue
        E.append(e); P.append(min(limit, o[e])); ST.append(stop)
    return np.array(E, int), np.array(P, float), np.array(ST, float)


def exits(sym, tf, side, e, px, stop, tgt_r):
    """진입 배열 → R (비용 포함), 청산 봉. 체결 봉은 손절만 확인."""
    idx, o, h, l, c, atr, _ = arrays(sym, tf, side)
    hold = HOLD[tf]
    if not len(e):
        return np.array([]), np.array([], int)
    dist = px - stop
    tgt = px + tgt_r * dist
    win = e[:, None] + np.arange(hold)[None, :]
    hs = l[win] <= stop[:, None]
    ht = h[win] >= tgt[:, None]
    ht[:, 0] = False
    big = hold + 1
    fs = np.where(hs.any(1), hs.argmax(1), big)
    ft = np.where(ht.any(1), ht.argmax(1), big)
    rows = np.arange(len(e))
    spx = np.minimum(stop, o[win][rows, np.minimum(fs, hold - 1)])
    last = c[e + hold - 1]
    won = ft < fs
    exit_px = np.where(won, tgt, np.where(fs < big, spx, last))
    fee = (MAKER + np.where(won, MAKER, TAKER)) * np.abs(px)
    r = (exit_px - px - fee) / dist
    return r, e + np.minimum(np.minimum(fs, ft), hold - 1)


def one_at_a_time(e, ex):
    keep, busy = [], -1
    for k in np.argsort(e, kind="stable"):
        if e[k] <= busy:
            continue
        keep.append(k)
        busy = ex[k]
    return np.array(keep, int)


def job(cfg):
    tf, side = cfg
    S = {sym: setups(sym, tf, side) for sym in SYMS}
    rng = np.random.default_rng(3)
    rows = []
    for stop_mode, entry_mode, use_reg, strict in product(("OB 아래", "FVG 아래"), ("FVG 윗변", "FVG 중간"), (False, True), (False, True)):
        per = {sym: run(sym, tf, side, S[sym], stop_mode, entry_mode, use_reg, strict) for sym in SYMS}
        for tgt in TARGETS:
            xs, rs = [], []
            for sym, (e, px, st) in per.items():
                idx, o, h, l, c, atr, _ = arrays(sym, tf, side)
                r, ex = exits(sym, tf, side, e, px, st, tgt)
                k = one_at_a_time(e, ex)
                xs.append(pd.DataFrame({"time": idx[e[k]], "r": r[k], "symbol": sym}) if len(k) else pd.DataFrame(columns=["time", "r", "symbol"]))
                # 무작위: 같은 손절폭(%) 분포, 무작위 시점에 시가로 진입
                pct = (px - st) / np.abs(px) if len(e) else np.array([0.01])
                m = max(len(e), 300)
                re_ = np.sort(rng.choice(np.arange(500, len(c) - HOLD[tf] - 2), m, replace=False))
                rp = o[re_]
                rst = rp - np.abs(rp) * rng.choice(pct, m)
                rr, rex = exits(sym, tf, side, re_, rp, rst, tgt)
                rk = one_at_a_time(re_, rex)
                rs.append(pd.DataFrame({"time": idx[re_[rk]], "r": rr[rk]}))
            x = pd.concat(xs, ignore_index=True)
            rx = pd.concat(rs, ignore_index=True)
            if len(x):
                x["time"] = pd.to_datetime(x.time, utc=True)
                x["r"] = x.r.astype(float)
            tr, te = x[x.time < SPLIT] if len(x) else x, x[x.time >= SPLIT] if len(x) else x
            rows.append(dict(tf=tf, side=side, stop=stop_mode, entry=entry_mode, reg=use_reg, strict=strict, tgt=tgt,
                             n_tr=len(tr), r_tr=tr.r.mean() if len(tr) else np.nan,
                             n_te=len(te), r_te=te.r.mean() if len(te) else np.nan, win_te=(te.r > 0).mean() if len(te) else np.nan,
                             rand_te=rx[rx.time >= SPLIT].r.mean(),
                             btc=te[te.symbol == "BTC"].r.mean() if len(te) else np.nan,
                             eth=te[te.symbol == "ETH"].r.mean() if len(te) else np.nan,
                             yrs=te.groupby(te.time.dt.year).r.mean().round(2).to_dict() if len(te) else {}))
    n_setups = sum(len(v) for v in S.values())
    return rows, (tf, side, n_setups)


def main():
    cfgs = list(product(HOLD, (1, -1)))
    with ProcessPoolExecutor(4) as pool:
        res = list(pool.map(job, cfgs))
    R = pd.DataFrame([r for rows, _ in res for r in rows])
    counts = {(tf, side): n for _, (tf, side, n) in res}
    print("CHoCH → OB → FVG → FVG 리테스트 진입 · BTC·ETH 2018~2026 · 설계 ~2021 / 검증 2022~ · R 은 비용 뺀 값\n")
    print("■ 1. 봉·방향별: 설계 구간에서 고른 설정 → 검증 구간")
    print(f"{'봉':6} {'방향':2} {'신호':>6} | {'고른 설정':34} | {'설계 n':>5} {'R':>6} | {'검증 n':>5} {'승률':>4} {'R':>6} {'무작위':>6} {'BTC':>6} {'ETH':>6} | 판정 | 연도별")
    for (tf, side), g in R.groupby(["tf", "side"], sort=False):
        g2 = g[g.n_tr >= 60]
        if not len(g2):
            print(f"{tf:6} {'롱' if side > 0 else '숏':2} {counts[(tf, side)]:6} | 설계 구간 거래 60건 미만")
            continue
        b = g2.loc[g2.r_tr.idxmax()]
        ok = b.r_te > 0 and b.n_te >= 100 and b.r_te - b.rand_te >= 0.05 and b.btc > 0 and b.eth > 0
        cfg = f"손절 {b.stop}·{b.entry}·장세{'O' if b.reg else '-'}·엄격{'O' if b.strict else '-'}·{b.tgt}R"
        ys = " ".join(f"{y}:{v:+.2f}" for y, v in b.yrs.items())
        print(f"{tf:6} {'롱' if side > 0 else '숏':2} {counts[(tf, side)]:6} | {cfg:34} | {b.n_tr:5} {b.r_tr:+6.3f} | {b.n_te:5} {b.win_te*100:3.0f}%"
              f" {b.r_te:+6.3f} {b.rand_te:+6.3f} {b.btc:+6.3f} {b.eth:+6.3f} | {'✅' if ok else '–'} | {ys}")
    print("\n■ 2. 봉별 전체 평균 (모든 설정, 검증 구간): 전략 vs 무작위")
    for tf in HOLD:
        g = R[R.tf == tf]
        print(f"  {tf:6} 롱 {g[g.side > 0].r_te.mean():+.3f}R (승률 {g[g.side > 0].win_te.mean()*100:.0f}%) · 숏 {g[g.side < 0].r_te.mean():+.3f}R"
              f" (승률 {g[g.side < 0].win_te.mean()*100:.0f}%) · 무작위 {g.rand_te.mean():+.3f}R · 거래 {int(g.n_te.mean())}건/설정")
    print("\n■ 3. 설정 요소별 평균 (검증 구간, 모든 봉·방향)")
    for col, name in (("stop", "손절"), ("entry", "진입가"), ("reg", "장세 필터"), ("strict", "OB-FVG 엄격"), ("tgt", "목표")):
        print(f"  {name:10} " + " · ".join(f"{k}: {v:+.3f}R" for k, v in R.groupby(col).r_te.mean().items()))
    print("\n■ 4. 검증 구간 상위 5개 (참고만, 과최적화 주의)")
    for t in R[R.n_te >= 100].sort_values("r_te", ascending=False).head(5).itertuples():
        print(f"  {t.tf} {'롱' if t.side > 0 else '숏'} 손절 {t.stop}·{t.entry}·장세{'O' if t.reg else '-'}·엄격{'O' if t.strict else '-'}·{t.tgt}R |"
              f" 설계 {t.r_tr:+.3f} ({t.n_tr}) 검증 {t.r_te:+.3f} ({t.n_te}) 무작위 {t.rand_te:+.3f}")
    R.drop(columns="yrs").to_csv("/tmp/choch_ob_fvg.csv", index=False)


if __name__ == "__main__":
    main()
