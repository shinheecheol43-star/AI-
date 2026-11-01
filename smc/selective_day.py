"""'확실할 때만' 하는 데이트레이딩: 모든 봉을 후보로 두고, 이길 확률이 높다고 판단될 때만 매매. 규칙은 결과를 보기 전에 정했다.

후보: 15분봉·1시간봉 (BTC·ETH)의 모든 봉, 롱·숏 각각. 다음 봉 시가 진입.
청산 두 가지 (데이트레이딩, 최대 12시간)
  고승률형: 목표 1 ATR(지정가) · 손절 3 ATR      (아무렇게나 들어가도 승률 ~70%대가 나오는 구조)
  대칭형  : 목표 2 ATR(지정가) · 손절 2 ATR      (아무렇게나 들어가면 승률 ~50%)
비용: 진입 0.075%, 목표 0.02%, 손절·시간 청산 0.075%.  '승리' = 비용 뺀 손익 > 0
특징 (봉 마감 때 알 수 있는 것만, 34개)
  RSI 2·14, 스토캐스틱 RSI, 볼린저 위치·폭(과 그 백분위), EMA 20·50·200 과의 거리(ATR 단위), EMA 기울기,
  최근 1·4·16·64봉 수익률(ATR 단위), ATR 백분위(변동성 국면), 거래량 비율, 연속 상승/하락 수,
  일봉 장세(전날까지 SMA 50/200), 일봉 기준 오늘 등락, 시각(UTC), 요일, 4시간 추세
모델: HistGradientBoosting (깊이 3, 잎당 최소 500개, 과최적화 방지)
검증: 해마다 다시 학습 — Y 년 거래는 Y−1 년 말까지 데이터로만 학습한 모델로 판단 (2020~2026 각각)
  확률 기준 0.80 / 0.85 / 0.90: 모델이 그 이상이라 할 때만 진입, 코인마다 한 번에 한 거래
판정 (미리 정함): 2022~ 에서 실제 승률 ≥ 85%, 기대값 > 0, BTC·ETH 둘 다 > 0, 거래 ≥ 50

사용:  python -m smc.selective_day
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from .highwin import TAKER, MAKER, ema, frame, rsi
from .highwin2 import regime

SYMS = ("BTC", "ETH")
HOLD = {"15min": 48, "1h": 12}
EXITS = {"고승률형 (목표1·손절3)": (1.0, 3.0), "대칭형 (목표2·손절2)": (2.0, 2.0)}
YEARS = range(2020, 2027)
TH = (0.80, 0.85, 0.90)


@lru_cache(maxsize=None)
def features(sym: str, tf: str) -> pd.DataFrame:
    d = frame(sym, tf).copy()
    c, a = d.close, d.atr
    f = pd.DataFrame(index=d.index)
    f["r2"], f["r14"], f["k"] = d.r2, d.r14, d.k
    mid, sd = c.rolling(20).mean(), c.rolling(20).std()
    f["bbpos"] = (c - mid) / (2 * sd)
    f["bbw"] = 4 * sd / c
    f["bbw_pct"] = f.bbw.rolling(500).rank(pct=True)
    for n in (20, 50, 200):
        e = d[f"e{n}"]
        f[f"d_e{n}"] = (c - e) / a
        f[f"s_e{n}"] = (e - e.shift(5)) / a
    for n in (1, 4, 16, 64):
        f[f"ret{n}"] = (c - c.shift(n)) / a
    f["atr_pct"] = (a / c).rolling(500).rank(pct=True)
    f["atr_rel"] = a / c
    f["vol_ratio"] = d.volume / d.volume.rolling(50).mean()
    up = (c > c.shift(1)).astype(int)
    grp = (up != up.shift(1)).cumsum()
    f["streak"] = up.groupby(grp).cumcount().add(1) * np.where(up > 0, 1, -1)
    f["regime"] = regime(sym).reindex(d.index, method="ffill").fillna(0)
    day_open = c.groupby(d.index.floor("1D")).transform("first")
    f["day_ret"] = (c - day_open) / a
    f["hour"], f["dow"] = d.index.hour, d.index.dayofweek
    c4 = c.resample("4h").last()
    t4 = (c4 > ema(c4, 50)).astype(int) - (c4 < ema(c4, 50)).astype(int)
    t4.index = t4.index + pd.Timedelta("4h") - pd.Timedelta(tf)
    f["trend4h"] = t4.reindex(d.index, method="ffill").fillna(0)
    f["r14_slope"] = rsi(c, 14).diff(4)
    f["hi_dist"] = (c.rolling(96).max() - c) / a
    f["lo_dist"] = (c - c.rolling(96).min()) / a
    return f


def labels(sym: str, tf: str, side: int, tgt_k: float, stop_k: float) -> pd.DataFrame:
    d = frame(sym, tf)
    hold = HOLD[tf]
    s = side
    h = (d.high if s > 0 else -d.low).to_numpy()
    l = (d.low if s > 0 else -d.high).to_numpy()
    o, c = (d.open * s).to_numpy(), (d.close * s).to_numpy()
    atr = d.atr.to_numpy()
    n = len(d)
    i = np.arange(n - hold - 2)
    e = i + 1
    entry, stop, tgt = o[e], o[e] - stop_k * atr[i], o[e] + tgt_k * atr[i]
    win = e[:, None] + np.arange(hold)[None, :]
    big = hold + 1
    hs = l[win] <= stop[:, None]
    ht = h[win] >= tgt[:, None]
    fs = np.where(hs.any(1), hs.argmax(1), big)
    ft = np.where(ht.any(1), ht.argmax(1), big)
    O = o[win]
    spx = np.minimum(stop, O[np.arange(len(i)), np.minimum(fs, hold - 1)])
    last = c[e + hold - 1]
    px = np.where(fs <= ft, np.where(fs < big, spx, last), tgt)
    px = np.where((fs >= big) & (ft >= big), last, px)
    ret = (px - entry) / entry - TAKER - np.where(ft < fs, MAKER, TAKER)
    ex = e + np.minimum(np.minimum(fs, ft), hold - 1)
    return pd.DataFrame({"ret": ret, "exit_i": ex, "i": i}, index=d.index[i])


def run(tf: str, side: int, tgt_k: float, stop_k: float) -> pd.DataFrame:
    """해마다 다시 학습해 Y 년 모든 봉의 '이길 확률'을 예측."""
    data = []
    for sym in SYMS:
        f = features(sym, tf)
        y = labels(sym, tf, side, tgt_k, stop_k)
        z = f.join(y, how="inner").dropna()
        data.append(z.assign(symbol=sym, coin=0 if sym == "BTC" else 1))
    z = pd.concat(data).sort_index()
    cols = [c for c in z.columns if c not in ("ret", "exit_i", "i", "symbol")]
    out = []
    for yr in YEARS:
        a = pd.Timestamp(f"{yr}-01-01", tz="UTC")
        b = pd.Timestamp(f"{yr + 1}-01-01", tz="UTC")
        tr = z[z.index < a - pd.Timedelta("1D")]                     # 결과(최대 12시간)가 확정된 것만
        te = z[(z.index >= a) & (z.index < b)]
        if len(te) == 0 or len(tr) < 20000:
            continue
        step = max(1, len(tr) // 300000)                              # 너무 많으면 고르게 줄여 학습
        trs = tr.iloc[::step]
        m = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=500,
                                           l2_regularization=1.0, random_state=0)
        m.fit(trs[cols], (trs.ret > 0).astype(int))
        out.append(te.assign(p=m.predict_proba(te[cols])[:, 1], base=(tr.ret > 0).mean()))
    return pd.concat(out)


def take(z: pd.DataFrame, th: float) -> pd.DataFrame:
    """확률 기준 이상만, 코인마다 한 번에 한 거래."""
    rows = []
    for sym, g in z[z.p >= th].groupby("symbol"):
        busy = -1
        for t in g.itertuples():
            if t.i <= busy:
                continue
            rows.append(t)
            busy = t.exit_i
    return pd.DataFrame(rows)


def main():
    print("'확실할 때만' 데이트레이딩 · BTC·ETH · 해마다 다시 학습 (그 해는 미리 못 본 상태로 판단) · 비용 포함\n")
    for tf in HOLD:
        for ex_name, (tk, sk) in EXITS.items():
            for side in (1, -1):
                z = run(tf, side, tk, sk)
                te = z[z.index >= pd.Timestamp("2022-01-01", tz="UTC")]
                print(f"■ {tf} {'롱' if side > 0 else '숏'} · {ex_name} · 2022~ 모든 봉 승률 {(te.ret > 0).mean()*100:.1f}%"
                      f" (아무 때나 들어갈 때), 평균 {te.ret.mean()*100:+.3f}%")
                # 보정: 모델이 말한 확률 vs 실제
                bins = pd.cut(te.p, [0, .5, .6, .7, .8, .85, .9, 1.0])
                cal = te.groupby(bins, observed=True).ret.agg(n="count", win=lambda r: (r > 0).mean(), ev="mean")
                print("   모델 확률 → 실제 승률 (평균 수익): " + " · ".join(
                    f"{iv.left:.2f}~{iv.right:.2f}: {w*100:.0f}% ({e*100:+.2f}%, {n})" for iv, (n, w, e) in cal.iterrows()))
                for th in TH:
                    x = take(z, th)
                    if not len(x):
                        print(f"   확률 ≥ {th:.2f}: 거래 없음")
                        continue
                    x2 = x[x.Index >= pd.Timestamp("2022-01-01", tz="UTC")]
                    if not len(x2):
                        print(f"   확률 ≥ {th:.2f}: 2022~ 거래 없음")
                        continue
                    yrs = 4.75
                    btc, eth = x2[x2.symbol == "BTC"].ret.mean(), x2[x2.symbol == "ETH"].ret.mean()
                    ok = (x2.ret > 0).mean() >= .85 and x2.ret.mean() > 0 and btc > 0 and eth > 0 and len(x2) >= 50
                    eq = np.cumprod(1 + x2.ret.to_numpy())
                    yr = x2.groupby(x2.Index.year).ret.agg(["count", lambda r: (r > 0).mean(), "mean"])
                    print(f"   확률 ≥ {th:.2f}: 2022~ {len(x2)}건 (월 {len(x2)/yrs/12:.1f}건) 승률 {(x2.ret > 0).mean()*100:.0f}%"
                          f" 평균 {x2.ret.mean()*100:+.3f}% · BTC {btc*100:+.3f}% ETH {eth*100:+.3f}% · 1배 누적 {eq[-1]:.2f}배"
                          f" | {'✅' if ok else '–'}")
                    print("      연도별 " + " ".join(f"{y}:{n}건 {w*100:.0f}% {m*100:+.2f}%" for y, (n, w, m) in yr.iterrows()))
                print()


if __name__ == "__main__":
    main()
