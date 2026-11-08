"""BOS · CHoCH · FVG 매매 전략 검증 (15분·1시간·4시간봉, BTC·ETH). 실시간 대응을 가정. 규칙은 결과를 보기 전에 정했다.

구조 (롱 기준, 숏은 가격을 뒤집어 같은 규칙)
  스윙 고점·저점: 좌우 k 봉(k = 3, 5) 중 가장 높/낮은 봉. 오른쪽 k 봉이 지나야 확정되므로 그때부터만 사용 (미래 정보 없음)
  추세 상태: 마지막으로 깨진 구조의 방향
  상승 돌파 = 봉의 고가가 확정된 직전 스윙 고점을 넘음
    추세가 이미 위였으면 BOS(추세 지속), 아래였으면 CHoCH(추세 전환)
  보호 저점 = 깨진 스윙 고점 이후 ~ 돌파 봉까지의 최저가 (이 파동의 출발점)
진입 방식
  실시간 돌파 : 스윙 고점에 미리 역지정가 주문 → 넘는 순간 그 가격(갭이면 시가)에 체결
  늦은 돌파   : 봉 종가가 스윙 고점 위로 마감한 걸 보고 다음 봉 시가에 진입 (비교용)
  FVG 되돌림 : 돌파 파동 안에 생긴 상승 FVG(1번 고가 < 3번 저가, 2번 양봉)의 윗변에 지정가.
              FVG 와 돌파가 둘 다 확인된 봉 다음부터 20봉 대기 (손절까지 내려가는 봉은 지정가가 먼저 체결된 것으로 침)
손절 = 보호 저점 − 0.1 ATR (손절폭이 0.5 ATR 미만이거나 5 ATR 초과면 건너뜀 — 비용·위험 과다)
목표 = 1.5R · 2R · 3R (지정가), 최대 보유 15분 96봉(하루) · 1시간 48봉 · 4시간 30봉
체결 봉 안의 순서는 모르므로 그 봉에서 손절가에 닿으면 손절로 친다 (보수적), 목표는 다음 봉부터.
필터: 없음 / 일봉 장세(전날까지 SMA50·200)와 같은 방향만
비용: 역지정가·시장가 0.075%, 지정가 0.02%, 손절·시간 청산 0.075%
비교: 같은 손절폭·목표로 무작위 시점에 들어간 결과
판정 (미리 정함): 설계(~2021)에서 고른 설정으로 검증(2022~) 평균 R > 0, 100건 이상,
  무작위보다 0.05R 이상 높음, BTC·ETH 둘 다 > 0

사용:  python -m smc.bos_choch
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
HOLD = {"15min": 96, "1h": 48, "4h": 30}
KS = (3, 5)
TARGETS = (1.5, 2.0, 3.0)
WAIT = 20


@lru_cache(maxsize=None)
def arrays(sym: str, tf: str, side: int):
    d = frame(sym, tf)
    s = side
    h = (d.high if s > 0 else -d.low).to_numpy()
    l = (d.low if s > 0 else -d.high).to_numpy()
    o, c = (d.open * s).to_numpy(), (d.close * s).to_numpy()
    reg = regime(sym).reindex(d.index, method="ffill").fillna(0).to_numpy() == side
    return d.index, o, h, l, c, d.atr.to_numpy(), reg


@lru_cache(maxsize=None)
def events(sym: str, tf: str, side: int, k: int):
    """상승 돌파 사건 목록 (가격은 side 기준으로 뒤집힌 공간)."""
    idx, o, h, l, c, atr, _ = arrays(sym, tf, side)
    n = len(c)
    hmax = pd.Series(h).rolling(2 * k + 1, center=True).max().to_numpy()
    lmin = pd.Series(l).rolling(2 * k + 1, center=True).min().to_numpy()
    is_sh, is_sl = h == hmax, l == lmin
    sh = sl = None                       # (피벗 위치, 가격) — 확정된 것만
    sh_broken = sl_broken = True
    trend = 0
    ev = []
    for t in range(2 * k + 1, n):
        j = t - 1 - k                    # 지난 봉(t-1) 마감 때 확정되는 피벗
        if is_sh[j]:
            sh, sh_broken = (j, h[j]), False
        if is_sl[j]:
            sl, sl_broken = (j, l[j]), False
        if sl is not None and not sl_broken and l[t] < sl[1]:      # 아래 구조가 깨지면 추세 하락
            trend, sl_broken = -1, True
        if sh is not None and not sh_broken and h[t] > sh[1]:
            kind = "BOS" if trend > 0 else "CHoCH"
            prot = l[sh[0]:t + 1].min()
            ev.append((t, sh[0], sh[1], prot, kind, c[t] > sh[1]))
            sh_broken = True
            trend = 1
    return ev


def fvgs_up(h, l, o, c, a: int, b: int):
    """[a, b] 구간에서 3번째 봉이 끝나는 상승 FVG (윗변 = 3번 저가, 아랫변 = 1번 고가, 확정 봉)."""
    out = []
    for i in range(max(a, 2), b + 1):
        if l[i] > h[i - 2] and c[i - 1] > o[i - 1]:
            out.append((i, l[i], h[i - 2]))
    return out


def simulate(sym, tf, side, k, entry_mode, use_reg, tgt):
    idx, o, h, l, c, atr, reg = arrays(sym, tf, side)
    n, hold = len(c), HOLD[tf]
    rows = []
    busy = -1
    for t, piv, lvl, prot, kind, close_above in events(sym, tf, side, k):
        if t <= busy or (use_reg and not reg[t]):
            continue
        stop = prot - 0.1 * atr[t]
        if entry_mode == "실시간 돌파":
            e, px, fee_in = t, max(lvl, o[t]), TAKER
            first_bar_stop = l[t] <= stop
        elif entry_mode == "늦은 돌파":
            if not close_above or t + 1 >= n:
                continue
            e, px, fee_in = t + 1, o[t + 1], TAKER
            first_bar_stop = l[e] <= stop
        else:                                               # FVG 되돌림
            z = fvgs_up(h, l, o, c, piv + 2, min(t + 2, n - 1))
            if not z:
                continue
            fi, top, bot = z[-1]
            start = max(t, fi) + 1
            e = None
            for u in range(start, min(n, start + WAIT)):
                if l[u] <= top:
                    e = u
                    break
            if e is None:
                continue
            px, fee_in = (top if o[e] <= stop else min(top, o[e])), MAKER
            first_bar_stop = l[e] <= stop
        dist = px - stop
        if not (0.5 * atr[t] <= dist <= 5 * atr[t]) or e + hold >= n:
            continue
        target = px + tgt * dist
        if first_bar_stop:
            ex_px, j, won = min(stop, o[e]), e, False
        else:
            ex_px, j, won = c[e + hold - 1], e + hold - 1, False
            for u in range(e + 1, e + hold):
                if l[u] <= stop:
                    ex_px, j = min(stop, o[u]), u
                    break
                if h[u] >= target:
                    ex_px, j, won = target, u, True
                    break
        fee = (fee_in + (MAKER if won else TAKER)) * abs(px)
        r = (ex_px - px - fee) / dist
        rows.append((idx[e], r, dist / abs(px), kind))
        busy = j
    return pd.DataFrame(rows, columns=["time", "r", "stop_pct", "kind"]).assign(symbol=sym)


def random_baseline(sym, tf, side, stop_pcts, tgt, n_min=400, seed=5):
    idx, o, h, l, c, atr, _ = arrays(sym, tf, side)
    hold = HOLD[tf]
    rng = np.random.default_rng(seed)
    pts = np.sort(rng.choice(np.arange(300, len(c) - hold - 2), max(n_min, len(stop_pcts)), replace=False))
    pcts = rng.choice(stop_pcts if len(stop_pcts) else np.array([0.01]), len(pts))
    rs = []
    for e, p in zip(pts, pcts):
        px = o[e]
        dist = abs(px) * p
        stop, target = px - dist, px + tgt * dist
        ex, won = c[e + hold - 1], False
        for u in range(e, e + hold):
            if l[u] <= stop:
                ex = min(stop, o[u])
                break
            if u > e and h[u] >= target:
                ex, won = target, True
                break
        rs.append((idx[e], (ex - px - (TAKER + (MAKER if won else TAKER)) * abs(px)) / dist))
    return pd.DataFrame(rs, columns=["time", "r"])


def job(cfg):
    tf, side, k, mode, use_reg = cfg
    out = []
    for tgt in TARGETS:
        x = pd.concat([simulate(s, tf, side, k, mode, use_reg, tgt) for s in SYMS], ignore_index=True)
        rb = pd.concat([random_baseline(s, tf, side, x[x.symbol == s].stop_pct.to_numpy(), tgt) for s in SYMS], ignore_index=True)
        out.append(((tf, side, k, mode, use_reg, tgt), x, rb))
    return out


def main():
    cfgs = list(product(HOLD, (1, -1), KS, ("실시간 돌파", "늦은 돌파", "FVG 되돌림"), (False, True)))
    with ProcessPoolExecutor(4) as pool:
        res = [r for chunk in pool.map(job, cfgs) for r in chunk]
    rows = []
    for key, x, rb in res:
        for kind in ("BOS", "CHoCH", "둘 다"):
            y = x if kind == "둘 다" else x[x.kind == kind]
            tr, te = y[y.time < SPLIT], y[y.time >= SPLIT]
            rows.append(dict(zip(("tf", "side", "k", "mode", "reg", "tgt"), key), kind=kind,
                             n_tr=len(tr), r_tr=tr.r.mean(), n_te=len(te), r_te=te.r.mean(), win_te=(te.r > 0).mean(),
                             rand_te=rb[rb.time >= SPLIT].r.mean(), stop_te=te.stop_pct.median(),
                             btc=te[te.symbol == "BTC"].r.mean(), eth=te[te.symbol == "ETH"].r.mean(),
                             yrs=te.groupby(te.time.dt.year).r.mean().round(2).to_dict()))
    R = pd.DataFrame(rows)
    print("BOS · CHoCH · FVG (실시간 대응 가정) · BTC·ETH · 설계 ~2021 / 검증 2022~ · R 은 비용 뺀 값\n")
    print("■ 1. 진입 방식 비교 (모든 설정 평균, 검증 구간): 실시간으로 들어가면 나아지나")
    for tf in HOLD:
        g = R[(R.tf == tf) & (R.kind == "둘 다")]
        print(f"  {tf:5} " + " · ".join(f"{m} {g[g['mode'] == m].r_te.mean():+.3f}R (승률 {g[g['mode'] == m].win_te.mean()*100:.0f}%)"
                                        for m in ("실시간 돌파", "늦은 돌파", "FVG 되돌림"))
              + f" · 무작위 {g.rand_te.mean():+.3f}R")
    print("\n■ 2. BOS vs CHoCH (모든 설정 평균, 검증 구간)")
    for tf in HOLD:
        g = R[R.tf == tf]
        print(f"  {tf:5} " + " · ".join(f"{kd} {g[g.kind == kd].r_te.mean():+.3f}R" for kd in ("BOS", "CHoCH")))
    print("\n■ 3. 봉·방향·진입 방식별로 설계 구간에서 고른 설정 → 검증 구간")
    print(f"{'봉':5} {'방향':2} {'진입':7} | {'고른 설정':24} | {'설계 n':>5} {'R':>6} | {'검증 n':>5} {'승률':>4} {'R':>6} {'무작위':>6} {'BTC':>6} {'ETH':>6} | 판정 | 연도별")
    for (tf, side, mode), g in R.groupby(["tf", "side", "mode"], sort=False):
        g = g[g.n_tr >= 80]
        if not len(g):
            continue
        b = g.loc[g.r_tr.idxmax()]
        ok = b.r_te > 0 and b.n_te >= 100 and b.r_te - b.rand_te >= 0.05 and b.btc > 0 and b.eth > 0
        cfg = f"{b.kind} k={b.k} 장세{'O' if b.reg else '-'} 목표{b.tgt}R"
        ys = " ".join(f"{y}:{v:+.2f}" for y, v in b.yrs.items())
        print(f"{tf:5} {'롱' if side > 0 else '숏':2} {mode:7} | {cfg:24} | {b.n_tr:5} {b.r_tr:+6.3f} | {b.n_te:5} {b.win_te*100:3.0f}%"
              f" {b.r_te:+6.3f} {b.rand_te:+6.3f} {b.btc:+6.3f} {b.eth:+6.3f} | {'✅' if ok else '–'} | {ys}")
    print("\n■ 4. 검증 구간 상위 5개 (참고만, 과최적화 주의)")
    for t in R[R.n_te >= 100].sort_values("r_te", ascending=False).head(5).itertuples():
        print(f"  {t.tf} {'롱' if t.side > 0 else '숏'} {t.mode} {t.kind} k={t.k} 장세{'O' if t.reg else '-'} 목표{t.tgt}R |"
              f" 설계 {t.r_tr:+.3f} ({t.n_tr}) 검증 {t.r_te:+.3f} ({t.n_te}) 무작위 {t.rand_te:+.3f}")
    R.drop(columns="yrs").to_csv("/tmp/bos_choch.csv", index=False)


if __name__ == "__main__":
    main()
