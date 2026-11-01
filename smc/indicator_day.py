"""데이트레이딩 지표 결합 연구: 볼린저 밴드 · 이동평균 · MACD · 스토캐스틱 RSI (15분봉, BTC·ETH).

규칙은 결과를 보기 전에 정했다.
지표 (15분봉 마감 기준, 다음 봉 시가에 시장가 진입)
  볼린저 20·2σ, EMA 9·21·50, 1시간봉 EMA 50·200(큰 추세), MACD 12·26·9, 스토캐스틱 RSI 14·14·3·3, ATR 14
부품 (롱 기준, 숏은 거꾸로)
  큰추세    1시간봉 EMA50 > EMA200 이고 종가 > 1시간봉 EMA200
  작은추세  종가 > 15분봉 EMA50
  밴드복귀  직전 종가가 하단 밴드 아래 → 이번 종가가 하단 밴드 위
  밴드터치  최근 3봉 안에 저가가 하단 밴드에 닿음
  밴드돌파  종가가 상단 밴드 위 (처음)
  스퀴즈    최근 5봉 안에 밴드 폭이 직전 500봉의 하위 20%
  MACD교차  MACD 선이 시그널 선을 위로 교차      MACD양수 히스토그램 > 0      MACD상승 히스토그램 증가
  SRSI반등  K 가 D 를 위로 교차 + 최근 3봉 안에 K < 0.2 (과매도에서 반등)      SRSI과열아님 K < 0.8
  EMA교차   EMA9 가 EMA21 을 위로 교차
전략 (부품 조합)
  단일 지표 기준선: SRSI반등 / MACD교차 / 밴드복귀 / EMA교차   ← 조합이 정말 나아지는지 비교용
  ① 추세 눌림목   큰추세 + 밴드터치 + SRSI반등 + MACD상승
  ② 평균회귀     밴드복귀 + SRSI반등 (추세 무관)         ②t 같은 것 + 큰추세
  ③ 스퀴즈 돌파   스퀴즈 + 밴드돌파 + MACD양수          ③t 같은 것 + 큰추세
  ④ MACD 추세    MACD교차 + 큰추세 + 작은추세 + SRSI과열아님
  ⑤ EMA 교차     EMA교차 + MACD양수 + 큰추세
  ⑥ 전부 동의    큰추세 + 작은추세 + SRSI반등 + MACD상승 + 밴드 중간선 아래에서 출발 (눌림목에서 반등)
청산 (전략마다 같은 후보 중 '설계 구간' 성적으로 하나 고름)
  손절 ATR × {1, 1.5, 2}
  목표 {1R, 1.5R, 2R, 3R, 밴드 중간선(진입 때 값), 목표 없이 추적 손절 ATR×2}
  최대 보유 {16봉=4시간, 48봉=12시간} 뒤 종가 청산. 같은 봉에서 손절·목표 둘 다 닿으면 손절로 친다.
  코인마다 한 번에 한 거래 (거래 중 나온 신호는 버림)
비용: 수수료 0.055% × 2 + 미끄러짐 0.02% × 2 = 왕복 0.15% (R 로 환산해 뺌)
판정 (미리 정함): 설계 구간(~2021)에서 고른 청산으로 검증 구간(2022~)이
  ① 평균 R > 0  ② 거래 100건 이상  ③ 같은 청산의 무작위 진입보다 평균 R 이 0.05 이상 높음  ④ BTC·ETH 둘 다 플러스
  넷 다 만족해야 '쓸 만한 후보'.

사용:  python -m smc.indicator_day
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from itertools import product

import numpy as np
import pandas as pd

from .daytrade import SPLIT
from .data import ARCHIVE, load_csv, resample

COST = 2 * (0.00055 + 0.0002)
SYMS = ("BTC", "ETH")
STOPS = (1.0, 1.5, 2.0)
TARGETS = (1.0, 1.5, 2.0, 3.0, "mid", "trail")
TF = os.environ.get("TF", "15min")
MIN = pd.Timedelta(TF).total_seconds() / 60
HOLDS = (16, 48) if MIN == 15 else (4, 12, 24)
TRAIL_K = 2.0
RISK = 0.005


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def cross_up(a: pd.Series, b: pd.Series) -> pd.Series:
    return (a > b) & (a.shift(1) <= b.shift(1))


@lru_cache(maxsize=None)
def frame(sym: str) -> pd.DataFrame:
    d = resample(load_csv(ARCHIVE / f"{sym}USDT_5m.csv.gz"), TF).set_index("time")
    d = d[d.index >= pd.Timestamp("2018-01-01", tz="UTC")]
    c = d.close
    pc = c.shift(1)
    tr = pd.concat([d.high - d.low, (d.high - pc).abs(), (d.low - pc).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    d["mid"] = c.rolling(20).mean()
    sd = c.rolling(20).std()
    d["up"], d["lo"] = d.mid + 2 * sd, d.mid - 2 * sd
    d["width"] = (d.up - d.lo) / d.mid
    d["e9"], d["e21"], d["e50"] = ema(c, 9), ema(c, 21), ema(c, 50)
    macd = ema(c, 12) - ema(c, 26)
    d["macd"], d["sig"] = macd, ema(macd, 9)
    d["hist"] = macd - d.sig
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / loss)
    lo14, hi14 = rsi.rolling(14).min(), rsi.rolling(14).max()
    k = ((rsi - lo14) / (hi14 - lo14)).rolling(3).mean()
    d["k"], d["d"] = k, k.rolling(3).mean()
    # 1시간봉 EMA: 10:00 시간봉은 11:00 에 확정 → 10:45 시작 15분봉(11:00 마감)부터 사용
    h = c.resample("1h").last().dropna()
    eh = pd.DataFrame({"h50": ema(h, 50), "h200": ema(h, 200)})
    eh.index = eh.index + pd.Timedelta("1h") - pd.Timedelta(TF)
    d = d.join(eh.reindex(d.index, method="ffill"))
    d["sq"] = (d.width <= d.width.rolling(500).quantile(0.2)).rolling(5).max().astype(bool)
    return d.dropna()


def parts(d: pd.DataFrame, side: int) -> dict[str, pd.Series]:
    """부품 신호 (side=1 롱, -1 숏). 숏은 가격 축을 뒤집어 같은 규칙을 쓴다."""
    s = side
    c, lo = d.close * s, (d.low if s > 0 else d.high) * s
    band_lo = (d.lo if s > 0 else d.up) * s
    band_up = (d.up if s > 0 else d.lo) * s
    k = d.k if s > 0 else 1 - d.k
    dd = d["d"] if s > 0 else 1 - d["d"]
    macd, sig, hist = d.macd * s, d.sig * s, d["hist"] * s
    p = {
        "big": (d.h50 * s > d.h200 * s) & (c > d.h200 * s),
        "small": c > d.e50 * s,
        "reclaim": (c.shift(1) < band_lo.shift(1)) & (c > band_lo),
        "touch": (lo <= band_lo).rolling(3).max().astype(bool),
        "breakout": (c > band_up) & (c.shift(1) <= band_up.shift(1)),
        "squeeze": d.sq,
        "macd_x": cross_up(macd, sig),
        "macd_pos": hist > 0,
        "macd_up": hist > hist.shift(1),
        "srsi": cross_up(k, dd) & (k.rolling(3).min() < 0.2),
        "srsi_ok": k < 0.8,
        "ema_x": cross_up(d.e9 * s, d.e21 * s),
        "below_mid": (c.shift(1) < d.mid.shift(1) * s),
    }
    return p


FAMILIES = {
    "기준: SRSI반등만": ["srsi"],
    "기준: MACD교차만": ["macd_x"],
    "기준: 밴드복귀만": ["reclaim"],
    "기준: EMA교차만": ["ema_x"],
    "① 추세 눌림목": ["big", "touch", "srsi", "macd_up"],
    "② 평균회귀": ["reclaim", "srsi"],
    "②t 평균회귀+추세": ["reclaim", "srsi", "big"],
    "③ 스퀴즈 돌파": ["squeeze", "breakout", "macd_pos"],
    "③t 스퀴즈 돌파+추세": ["squeeze", "breakout", "macd_pos", "big"],
    "④ MACD 추세": ["macd_x", "big", "small", "srsi_ok"],
    "⑤ EMA 교차": ["ema_x", "macd_pos", "big"],
    "⑥ 전부 동의": ["big", "small", "srsi", "macd_up", "below_mid"],
}


def outcomes(d: pd.DataFrame, idx: np.ndarray, side: int, stop_k: float, target, hold: int) -> pd.DataFrame:
    """신호 봉 idx (그 봉 종가 확인 → 다음 봉 시가 진입). 한 코인 안에서 겹치는 거래는 버린다."""
    n = len(d)
    idx = idx[idx + 1 + hold < n]
    if not len(idx):
        return pd.DataFrame()
    o, h, l, c = (d[k].to_numpy() for k in ("open", "high", "low", "close"))
    atr, mid = d.atr.to_numpy(), d.mid.to_numpy()
    e = idx + 1
    entry = o[e]
    dist = stop_k * atr[idx]
    stop0 = entry - side * dist
    win = e[:, None] + np.arange(hold)[None, :]
    H = (h[win] if side > 0 else -l[win]) * 1.0
    L = (l[win] if side > 0 else -h[win]) * 1.0
    E, S0 = entry * side, stop0 * side                              # 숏은 부호를 뒤집어 롱처럼 계산
    if target == "trail":
        best = np.maximum.accumulate(H, axis=1)
        best = np.concatenate([np.full((len(idx), 1), -np.inf), best[:, :-1]], axis=1)
        best[:, 0] = E
        best = np.maximum(best, E[:, None])
        stop = np.maximum(S0[:, None], best - TRAIL_K * atr[idx][:, None])
        tgt = np.full(len(idx), np.inf)
    else:
        stop = np.repeat(S0[:, None], hold, axis=1)
        if target == "mid":
            tgt = mid[idx] * side
            tgt = np.where(tgt > E, tgt, np.nan)                     # 이미 중간선 위면 거래 안 함
        else:
            tgt = E + target * dist
    hit_s = L <= stop
    hit_t = H >= tgt[:, None]
    big = hold + 1
    fs = np.where(hit_s.any(1), hit_s.argmax(1), big)
    ft = np.where(hit_t.any(1), hit_t.argmax(1), big)
    j = np.minimum(np.minimum(fs, ft), hold - 1)
    rows = np.arange(len(idx))
    # 시가가 이미 손절가를 넘겨 열리면 시가에 체결
    o_side = (o[win] * side)
    sp = stop[rows, np.minimum(fs, hold - 1)]
    px_stop = np.minimum(sp, o_side[rows, np.minimum(fs, hold - 1)])
    exit_px = np.where(fs <= ft, np.where(fs < big, px_stop, c[e + hold - 1] * side), tgt)
    exit_px = np.where((fs >= big) & (ft >= big), c[e + hold - 1] * side, exit_px)
    ok = ~np.isnan(tgt) if target == "mid" else np.ones(len(idx), bool)
    stop_pct = dist / entry
    r = (exit_px - E) / dist - COST / stop_pct
    exit_i = e + j
    # 겹치는 거래 버리기 (순서대로)
    keep, busy = [], -1
    for t in range(len(idx)):
        if not ok[t] or idx[t] <= busy:
            continue
        keep.append(t)
        busy = exit_i[t]
    keep = np.array(keep, int)
    return pd.DataFrame({"time": d.index[e[keep]], "exit": d.index[exit_i[keep]], "r": r[keep], "gross": r[keep] + COST / stop_pct[keep],
                         "stop_pct": stop_pct[keep]})


@lru_cache(maxsize=None)
def signals(sym: str, side: int) -> dict[str, np.ndarray]:
    d = frame(sym)
    p = parts(d, side)
    out = {}
    for name, need in FAMILIES.items():
        m = np.logical_and.reduce([p[k].fillna(False).to_numpy(bool) for k in need])
        out[name] = np.flatnonzero(m)
    return out


@lru_cache(maxsize=None)
def random_idx(sym: str, side: int, n: int, seed: int) -> np.ndarray:
    d = frame(sym)
    rng = np.random.default_rng(seed)
    return np.sort(rng.choice(len(d) - 100, size=n, replace=False))


def job(args):
    name, side, stop_k, target, hold = args
    xs, rs = [], []
    for sym in SYMS:
        d = frame(sym)
        idx = signals(sym, side)[name]
        x = outcomes(d, idx, side, stop_k, target, hold).assign(symbol=sym)
        xs.append(x)
        ridx = random_idx(sym, side, max(len(idx), 2000), 7 + side)
        rs.append(outcomes(d, ridx, side, stop_k, target, hold).assign(symbol=sym))
    return args, pd.concat(xs, ignore_index=True), pd.concat(rs, ignore_index=True)


def summ(x: pd.DataFrame) -> dict:
    if not len(x):
        return {"n": 0, "win": np.nan, "r": np.nan, "pf": np.nan}
    g, b = x.r[x.r > 0].sum(), -x.r[x.r < 0].sum()
    return {"n": len(x), "win": (x.r > 0).mean(), "r": x.r.mean(), "pf": g / b if b else np.inf}


def account(x: pd.DataFrame) -> dict:
    """거래당 리스크 0.5%, 청산 순서대로 복리 (BTC·ETH 한 계좌)."""
    x = x.sort_values("exit")
    eq = (1 + RISK * x.r.clip(lower=-3)).cumprod()
    eq.index = x.exit
    yrs = max((x.exit.iloc[-1] - x.time.iloc[0]).days / 365.25, 0.1)
    return {"cagr": eq.iloc[-1] ** (1 / yrs) - 1, "mdd": (eq / eq.cummax() - 1).min(), "per_month": len(x) / yrs / 12}


def main():
    pd.set_option("display.width", 200)
    for sym in SYMS:
        frame(sym)
    for sym, side in product(SYMS, (1, -1)):
        signals(sym, side)
    configs = [(n, s, k, t, h) for n in FAMILIES for s in (1, -1) for k in STOPS for t in TARGETS for h in HOLDS]
    with ProcessPoolExecutor(4) as pool:
        results = list(pool.map(job, configs, chunksize=8))
    rows = []
    for (name, side, k, t, h), x, rx in results:
        tr, te = x[x.time < SPLIT], x[x.time >= SPLIT]
        rtr, rte = rx[rx.time < SPLIT], rx[rx.time >= SPLIT]
        a, b = summ(tr), summ(te)
        rows.append({"name": name, "side": side, "k": k, "t": t, "h": h,
                     "n_tr": a["n"], "r_tr": a["r"], "n_te": b["n"], "win_te": b["win"], "r_te": b["r"], "pf_te": b["pf"],
                     "rand_tr": rtr.r.mean(), "rand_te": rte.r.mean(), "g_te": te.gross.mean() if len(te) else np.nan,
                     "rg_te": rte.gross.mean(),
                     "btc_te": te[te.symbol == "BTC"].r.mean(), "eth_te": te[te.symbol == "ETH"].r.mean(), "x": x})
    R = pd.DataFrame(rows)
    print(f"데이터 {frame('BTC').index[0]:%Y-%m} ~ {frame('BTC').index[-1]:%Y-%m}, {TF}봉 · 비용 왕복 {COST*100:.2f}% · 설계 ~2021 / 검증 2022~\n")

    print("■ 1. 설계 구간에서 고른 청산으로 본 검증 구간 성적 (평균 R 은 비용 뺀 값)")
    print(f"{'전략':18} {'방향':2} | {'청산 (설계에서 고름)':22} | {'설계 n':>6} {'R':>6} | {'검증 n':>6} {'승률':>4} {'R':>6} {'PF':>5}"
          f" {'무작위':>6} {'BTC':>6} {'ETH':>6} | 판정")
    picks = []
    for (name, side), g in R.groupby(["name", "side"], sort=False):
        g = g[g.n_tr >= 60]
        if not len(g):
            print(f"{name:18} {'롱' if side > 0 else '숏':2} | 설계 구간 거래 60건 미만")
            continue
        best = g.loc[g.r_tr.idxmax()]
        ok = (best.r_te > 0) and (best.n_te >= 100) and (best.r_te - best.rand_te >= 0.05) and best.btc_te > 0 and best.eth_te > 0
        tgt = best.t if isinstance(best.t, str) else f"{best.t}R"
        tgt = {"mid": "중간선", "trail": "추적"}.get(tgt, tgt)
        ex = f"손절 {best.k}ATR·{tgt}·{best.h * MIN / 60:g}h"
        print(f"{name:18} {'롱' if side > 0 else '숏':2} | {ex:22} | {best.n_tr:6} {best.r_tr:+6.3f} | {best.n_te:6} {best.win_te*100:3.0f}%"
              f" {best.r_te:+6.3f} {best.pf_te:5.2f} {best.rand_te:+6.3f} {best.btc_te:+6.3f} {best.eth_te:+6.3f} | 비용전 {best.g_te:+.3f} (무작위 {best.rg_te:+.3f}) | {'✅ 후보' if ok else '–'}")
        picks.append((name, side, best, ok))

    print("\n■ 2. 무작위 진입(같은 청산 규칙)의 평균 R — 비용 때문에 보통 마이너스. 전략이 이보다 나아야 의미가 있다")
    rnd = R.groupby(["side", "k", "t", "h"], sort=False)[["rand_tr", "rand_te"]].first().reset_index()
    print(f"  롱 평균 {rnd[rnd.side > 0].rand_te.mean():+.3f}R · 숏 평균 {rnd[rnd.side < 0].rand_te.mean():+.3f}R (검증 구간, 모든 청산 규칙 평균)")

    print("\n■ 3. 검증 구간에서 가장 좋았던 조합 상위 10개 (참고만: 검증 구간으로 고르면 과최적화)")
    top = R[R.n_te >= 100].sort_values("r_te", ascending=False).head(10)
    for t in top.itertuples():
        print(f"  {t.name:18} {'롱' if t.side > 0 else '숏'} 손절{t.k} {t.t} {t.h * MIN / 60:g}h | 설계 {t.r_tr:+.3f} ({t.n_tr}) | 검증 {t.r_te:+.3f} ({t.n_te})")

    print("\n■ 4. 지표 조합 vs 단일 지표 (같은 방향·설계에서 고른 청산, 검증 R)")
    for side in (1, -1):
        base = [p for p in picks if p[1] == side and p[0].startswith("기준")]
        comb = [p for p in picks if p[1] == side and not p[0].startswith("기준")]
        if base and comb:
            print(f"  {'롱' if side > 0 else '숏'}: 단일 지표 평균 {np.mean([p[2].r_te for p in base]):+.3f}R · 조합 평균 {np.mean([p[2].r_te for p in comb]):+.3f}R")

    good = [p for p in picks if p[3]]
    print("\n■ 5. 후보로 한 계좌 (거래당 0.5%, BTC·ETH)")
    if not good:
        print("  판정을 통과한 전략이 없습니다.")
    for name, side, best, _ in good:
        x = best.x
        for lab, y in (("전체", x), ("설계", x[x.time < SPLIT]), ("검증", x[x.time >= SPLIT])):
            a = account(y)
            print(f"  {name} {'롱' if side > 0 else '숏'} {lab}: 연 {a['cagr']*100:+.1f}% · 최대낙폭 {a['mdd']*100:.1f}% · 월 {a['per_month']:.1f}건")
        yr = x.groupby(x.time.dt.year).r.agg(["count", "mean"])
        print("    연도별 평균 R: " + " ".join(f"{y}:{m:+.2f}({n})" for y, (n, m) in yr.iterrows()))
    R.drop(columns="x").to_csv(f"/tmp/indicator_day_{TF}.csv", index=False)


if __name__ == "__main__":
    main()
