"""데이트레이딩 '되돌림 25%' 매매 검증 (15분봉, BTC·ETH). 규칙은 결과를 보기 전에 정했다.

파동(임펄스) 정의 (위로 간 파동 기준, 아래 파동은 거꾸로)
  직전 봉이 최근 N 봉 최고가(H)를 만들었고, 그 N 봉의 최저가(L)가 앞쪽 절반에 있으며,
  파동 크기 H − L ≥ m × ATR(15분, 14). 이번 봉이 더 높이 못 가고 음봉으로 마감 = 파동 끝 신호.
A. 역추세: 파동 끝에서 반대로 들어가 25% 되돌림을 먹는다
  다음 봉 시가에 숏, 목표 = H − 0.25 × (H − L) (지정가), 손절 = H + s (s = ATR × 0.5/1/2 또는 파동의 25%)
  진입가가 이미 목표 아래면 건너뜀.
B. 추세 눌림목: 25% 되돌림에서 파동 방향으로 들어간다
  H − 0.25 × (H − L) 에 지정가 매수, 16봉(4시간) 안에 체결 안 되거나 그 전에 H 를 넘으면 취소
  손절 = 50% / 61.8% / 100%(L) 되돌림, 목표 = H(직전 고점) 또는 2R
공통: 최대 보유 16봉(4시간) / 48봉(12시간) 뒤 종가 청산. 같은 봉에서 손절·목표 둘 다 닿으면 손절.
     지정가 체결 봉에서는 손절만 확인(보수적). 코인마다 한 번에 한 거래.
비용: 시장가 0.055% + 미끄러짐 0.02%, 지정가 0.02% (목표 청산과 B 진입은 지정가)
비교: '랜덤워크 승률' = 손절거리 ÷ (목표거리 + 손절거리). 가격이 아무 규칙 없이 움직여도 나오는 승률.
     실제 승률이 이보다 높아야 '되돌림이 실제로 잘 일어난다'는 뜻.
판정 (미리 정함): 설계 구간(~2021)에서 고른 설정으로 검증 구간(2022~)
  평균 R > 0, 100건 이상, BTC·ETH 둘 다 플러스.

사용:  python -m smc.retrace_day
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from itertools import product

import numpy as np
import pandas as pd

from .daytrade import SPLIT
from .indicator_day import frame

TAKER, MAKER = 0.00055 + 0.0002, 0.0002
SYMS = ("BTC", "ETH")
NS, MS = (16, 32, 96), (6, 10, 15)
RET = 0.25


def impulses(d: pd.DataFrame, n: int, m: float, side: int):
    """파동 끝 신호 봉 i 와 그 파동의 H, L (side=1 위 파동, -1 아래 파동; 숏 파동은 가격을 뒤집어 계산)."""
    hi = (d.high if side > 0 else -d.low).to_numpy()
    lo = (d.low if side > 0 else -d.high).to_numpy()
    c = (d.close * side).to_numpy()
    o = (d.open * side).to_numpy()
    hh = pd.Series(hi).rolling(n).max().to_numpy()
    ll = pd.Series(lo).rolling(n).min().to_numpy()
    ll_first = pd.Series(lo).shift(n // 2).rolling(n - n // 2).min().to_numpy()
    atr = d.atr.to_numpy()
    i = np.arange(1, len(d))
    p = i - 1
    ok = (hi[p] >= hh[p]) & (ll_first[p] <= ll[p]) & (hh[p] - ll[p] >= m * atr[p]) & (hi[i] < hi[p]) & (c[i] < o[i])
    i = i[ok & ~np.isnan(hh[p])]
    return i, hh[i - 1], ll[i - 1]


def sim(h, l, c, e, entry, stop, tgt, hold, first_bar_tgt=True):
    """롱 기준 (숏은 미리 뒤집어 넣는다). e: 진입 봉. 반환: 청산가, 청산 봉, 목표 도달 여부."""
    win = e[:, None] + np.arange(hold)[None, :]
    H, L = h[win], l[win]
    hit_s = L <= stop[:, None]
    hit_t = H >= tgt[:, None]
    if not first_bar_tgt:
        hit_t[:, 0] = False
    big = hold + 1
    fs = np.where(hit_s.any(1), hit_s.argmax(1), big)
    ft = np.where(hit_t.any(1), hit_t.argmax(1), big)
    last = c[e + hold - 1]
    px = np.where(fs <= ft, np.where(fs < big, stop, last), tgt)
    px = np.where((fs >= big) & (ft >= big), last, px)
    j = np.minimum(np.minimum(fs, ft), hold - 1)
    return px, e + j, (ft < fs), np.minimum(fs, ft) < big


def run(sym: str, kind: str, side: int, n: int, m: float, stop_rule, tgt_rule, hold: int) -> pd.DataFrame:
    d = frame(sym)
    i, H, L = impulses(d, n, m, side)
    rng = H - L
    s = side
    # 파동 방향 기준으로 가격 뒤집기 (side=-1 이면 아래 파동을 위 파동처럼)
    h = (d.high if s > 0 else -d.low).to_numpy()
    l = (d.low if s > 0 else -d.high).to_numpy()
    o, c = (d.open * s).to_numpy(), (d.close * s).to_numpy()
    atr = d.atr.to_numpy()
    N = len(d)
    if kind == "A":                                       # 역추세: 파동 반대로 → 한 번 더 뒤집어 롱처럼
        e = i + 1
        ok = e + hold < N
        i, H, L, rng, e = i[ok], H[ok], L[ok], rng[ok], e[ok]
        entry = -o[e]
        tgt = -(H - RET * rng)
        stop = -(H + (stop_rule * atr[i] if stop_rule != "wave" else RET * rng))
        ok = tgt > entry
        i, e, entry, tgt, stop = i[ok], e[ok], entry[ok], tgt[ok], stop[ok]
        px, ex, won, res = sim(-l, -h, -c, e, entry, stop, tgt, hold)
        cost_in = TAKER
    else:                                                 # 추세 눌림목: 지정가 진입
        limit = H - RET * rng
        stop = H - {"50%": 0.5, "61.8%": 0.618, "100%": 1.0}[stop_rule] * rng
        W = 16
        ok = i + 1 + W + hold < N
        i, H, limit, stop = i[ok], H[ok], limit[ok], stop[ok]
        win = (i + 1)[:, None] + np.arange(W)[None, :]
        touch = l[win] <= limit[:, None]
        over = h[win] > H[:, None]
        ft = np.where(touch.any(1), touch.argmax(1), W + 1)
        fo = np.where(over.any(1), over.argmax(1), W + 1)
        fill = (ft <= W) & (ft < fo)                     # 같은 봉에서 고점 돌파와 체결이 겹치면 체결 안 된 것으로
        i, H, limit, stop, ft = i[fill], H[fill], limit[fill], stop[fill], ft[fill]
        e = i + 1 + ft
        entry = np.minimum(limit, o[e])                  # 시가가 이미 아래면 시가에 체결
        dist = entry - stop
        tgt = H if tgt_rule == "high" else entry + 2 * dist
        good = dist > 0
        i, e, entry, stop, tgt = i[good], e[good], entry[good], stop[good], tgt[good]
        px, ex, won, res = sim(h, l, c, e, entry, stop, tgt, hold, first_bar_tgt=False)
        cost_in = MAKER
    dist = entry - stop
    a = tgt - entry
    stop_pct = dist / np.abs(entry)
    cost = cost_in + np.where(won, MAKER, TAKER)
    r = (px - entry) / dist - cost / stop_pct
    keep, busy = [], -1
    for t in range(len(e)):
        if i[t] <= busy:
            continue
        keep.append(t)
        busy = ex[t]
    k = np.array(keep, int)
    return pd.DataFrame({"time": d.index[e[k]], "r": r[k], "gross": r[k] + cost[k] / stop_pct[k], "won": won[k], "res": res[k],
                         "rw": (dist / (dist + a))[k], "symbol": sym})


def job(cfg):
    kind, side, n, m, st, tg, hold = cfg
    return cfg, pd.concat([run(s, kind, side, n, m, st, tg, hold) for s in SYMS], ignore_index=True)


def main():
    for s in SYMS:
        frame(s)
    cfgs = [("A", sd, n, m, st, None, h) for sd, n, m, st, h in product((1, -1), NS, MS, (0.5, 1.0, 2.0, "wave"), (16, 48))]
    cfgs += [("B", sd, n, m, st, tg, h) for sd, n, m, st, tg, h in product((1, -1), NS, MS, ("50%", "61.8%", "100%"), ("high", "2R"), (16, 48))]
    with ProcessPoolExecutor(4) as pool:
        res = list(pool.map(job, cfgs, chunksize=4))
    rows = []
    for (kind, side, n, m, st, tg, hold), x in res:
        tr, te = x[x.time < SPLIT], x[x.time >= SPLIT]
        rows.append({"kind": kind, "side": side, "n": n, "m": m, "st": st, "tg": tg, "hold": hold,
                     "n_tr": len(tr), "r_tr": tr.r.mean(), "n_te": len(te), "r_te": te.r.mean(), "g_te": te.gross.mean(),
                     "win_te": te.won.mean(), "rw_te": te.rw.mean(), "win_all": x[x.res].won.mean(), "rw_all": x[x.res].rw.mean(), "res_all": x.res.mean(),
                     "btc": te[te.symbol == "BTC"].r.mean(), "eth": te[te.symbol == "ETH"].r.mean()})
    R = pd.DataFrame(rows)
    names = {("A", 1): "A 역추세: 급등 뒤 숏", ("A", -1): "A 역추세: 급락 뒤 롱",
             ("B", 1): "B 눌림목: 상승 파동 25% 눌림 롱", ("B", -1): "B 눌림목: 하락 파동 25% 반등 숏"}
    print("15분봉 BTC·ETH 2018~2026 · 설계 ~2021 / 검증 2022~ · R 은 비용 뺀 값\n")
    print("■ 1. 25% 되돌림이 실제로 '잘' 일어나나: 손절·목표 중 먼저 닿은 쪽 (시간 청산 제외) vs 랜덤워크 (전체 기간, 모든 설정 평균)")
    for (kind, side), g in R.groupby(["kind", "side"], sort=False):
        print(f"  {names[(kind, side)]:28} 실제 목표 도달 {g.win_all.mean()*100:4.1f}% · 랜덤워크 {g.rw_all.mean()*100:4.1f}%"
              f" · 차이 {(g.win_all - g.rw_all).mean()*100:+.1f}%p · 시간 안에 결판 {g.res_all.mean()*100:.0f}% · 검증 비용전 R {g.g_te.mean():+.3f} 비용후 {g.r_te.mean():+.3f}")
    print("\n■ 2. 설계 구간에서 고른 설정 → 검증 구간 (설계 거래 80건 이상 중)")
    for (kind, side), g in R.groupby(["kind", "side"], sort=False):
        g = g[g.n_tr >= 80]
        b = g.loc[g.r_tr.idxmax()]
        ok = b.r_te > 0 and b.n_te >= 100 and b.btc > 0 and b.eth > 0
        st = f"손절 {b.st}" + ("ATR" if isinstance(b.st, float) else "")
        print(f"  {names[(kind, side)]:28} N={b.n} m={b.m} {st} 목표 {b.tg if isinstance(b.tg, str) else '25%'} {b.hold // 4}h |"
              f" 설계 {b.n_tr}건 {b.r_tr:+.3f}R | 검증 {b.n_te}건 승률 {b.win_te*100:.0f}% (랜덤워크 {b.rw_te*100:.0f}%)"
              f" {b.r_te:+.3f}R (비용전 {b.g_te:+.3f}) BTC {b.btc:+.3f} ETH {b.eth:+.3f} | {'✅ 후보' if ok else '–'}")
    print("\n■ 3. 승률이 가장 높은 설정 (검증 구간, 100건 이상) — 승률이 높아도 R 은?")
    for t in R[R.n_te >= 100].sort_values("win_te", ascending=False).head(6).itertuples():
        print(f"  {names[(t.kind, t.side)]:28} N={t.n} m={t.m} 손절 {t.st} {t.hold // 4}h | 승률 {t.win_te*100:.0f}%"
              f" (랜덤워크 {t.rw_te*100:.0f}%) | 평균 {t.r_te:+.3f}R")
    print("\n■ 4. 검증 구간 R 상위 5개 (참고만, 과최적화 주의)")
    for t in R[R.n_te >= 100].sort_values("r_te", ascending=False).head(5).itertuples():
        print(f"  {names[(t.kind, t.side)]:28} N={t.n} m={t.m} 손절 {t.st} 목표 {t.tg if isinstance(t.tg, str) else '25%'} {t.hold // 4}h |"
              f" 설계 {t.r_tr:+.3f} ({t.n_tr}) 검증 {t.r_te:+.3f} ({t.n_te})")
    R.to_csv("/tmp/retrace_day.csv", index=False)


if __name__ == "__main__":
    main()
