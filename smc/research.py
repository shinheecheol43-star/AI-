"""신호 + 진입 근거 데이터셋 만들기.

"신호가 나왔을 때 어떤 근거가 붙어 있으면 이길 확률이 올라가는가"를 보기 위해
7종 진입 신호(롱·숏)를 1시간봉·4시간봉에서 모으고, 그 순간의 근거(지표)를 함께 기록한다.

공정한 비교를 위해 청산은 모두 같게 통일한다.
  손절 = 진입가 ∓ ATR(14) × 1.5,  익절 = 손절폭 × 1.5 (1.5R),  최대 보유 1h 48봉 / 4h 30봉
  지정가 진입(FVG·OB)은 0.02%, 시장가 진입은 0.055%, 익절 0.02%, 손절·시간 청산 0.055% (Bybit)
  같은 캔들에 손절·익절이 모두 닿으면 손절로 본다.

근거 지표는 모두 신호 캔들 마감 시점까지의 정보만 쓴다(일봉·펀딩비는 전날까지).
방향성 지표는 '신호 방향 기준'으로 바꿔 저장한다(예: 롱이면 RSI, 숏이면 100−RSI).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import BTConfig, _manage
from .data import fetch_binance_archive, resample
from .detectors import Params, find_fakeouts, find_fvgs
from .ob_lecture import find as find_ob
from .regime import fetch_funding, indicators as daily_indicators

MAKER, TAKER = 0.0002, 0.00055
STOP_ATR, TP_R = 1.5, 1.5
OUT = Path(__file__).resolve().parent.parent / "reports" / "signals.pkl"


# ---------------------------------------------------------------- 지표
def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def tf_features(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c, v = (df[k] for k in ("open", "high", "low", "close", "volume"))
    f = pd.DataFrame(index=df.index)
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    f["atr"] = atr
    f["atr_pct"] = atr / c
    f["vol_rank"] = f["atr_pct"].rolling(500, min_periods=200).rank(pct=True)
    for n in (20, 50, 200):
        f[f"ema{n}"] = c.ewm(span=n, adjust=False).mean()
    f["rsi"] = rsi(c)
    # ADX(14): 추세의 강도 (방향과 무관)
    upm, dnm = h.diff(), -l.diff()
    pdm = pd.Series(np.where((upm > dnm) & (upm > 0), upm, 0.0), index=df.index)
    ndm = pd.Series(np.where((dnm > upm) & (dnm > 0), dnm, 0.0), index=df.index)
    pdi = 100 * pdm.ewm(alpha=1 / 14, adjust=False).mean() / atr
    ndi = 100 * ndm.ewm(alpha=1 / 14, adjust=False).mean() / atr
    f["adx"] = (100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)).ewm(alpha=1 / 14, adjust=False).mean()
    sd = c.rolling(20).std()
    f["bb_width"] = 4 * sd / c.rolling(20).mean()
    f["bb_width_rank"] = f["bb_width"].rolling(500, min_periods=200).rank(pct=True)
    f["vol_ratio"] = v / v.rolling(20).mean()
    f["ret20"] = c / c.shift(20) - 1
    f["dist_ema20"] = (c - f["ema20"]) / atr
    f["dist_ema200"] = (c - f["ema200"]) / atr
    rng = (h - l).replace(0, np.nan)
    f["body_ratio"] = (c - o).abs() / rng
    f["close_pos"] = (c - l) / rng                     # 캔들 안에서 종가 위치 (0 = 저가, 1 = 고가)
    return f


# ---------------------------------------------------------------- 신호
def signals(df: pd.DataFrame, f: pd.DataFrame, wait: int) -> list[dict]:
    """[{family, side, i(신호 마감 캔들), entry_type, price(지정가면 대기가), sweep}]"""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    n = len(c)
    out = []
    for z in find_fvgs(df, Params()):
        out.append(dict(family="FVG", side=z.side, i=z.confirm, limit=z.entry, sweep=z.sweep))
    for b in find_ob(df):
        out.append(dict(family="OB", side=b.side, i=b.confirm, limit=b.entry, sweep=b.tags["sweep"]))
    for x in find_fakeouts(df, Params()):
        out.append(dict(family="거짓돌파", side=x.side, i=x.confirm, limit=None, sweep=True))
    # 회귀 채널(직전 100캔들 종가) ±2σ 바깥에 꼬리를 찍고 안쪽으로 반대색 마감
    m = 100
    xs = np.arange(m)
    xm, xv = xs.mean(), ((xs - xs.mean()) ** 2).sum()
    for i in range(m, n):
        y = c[i - m:i]
        bcoef = ((xs - xm) * (y - y.mean())).sum() / xv
        a = y.mean() - bcoef * xm
        sd = (y - (a + bcoef * xs)).std()
        mid = a + bcoef * m
        if h[i] >= mid + 2 * sd and c[i] < mid + 2 * sd and c[i] < o[i]:
            out.append(dict(family="채널반전", side=-1, i=i, limit=None, sweep=False))
        if l[i] <= mid - 2 * sd and c[i] > mid - 2 * sd and c[i] > o[i]:
            out.append(dict(family="채널반전", side=1, i=i, limit=None, sweep=False))
    r = f["rsi"].to_numpy()
    e20, e50 = f["ema20"].to_numpy(), f["ema50"].to_numpy()
    hh = pd.Series(h).rolling(20).max().shift(1).to_numpy()
    ll = pd.Series(l).rolling(20).min().shift(1).to_numpy()
    for i in range(1, n):
        if r[i - 1] < 30 <= r[i]:
            out.append(dict(family="RSI반전", side=1, i=i, limit=None, sweep=False))
        if r[i - 1] > 70 >= r[i]:
            out.append(dict(family="RSI반전", side=-1, i=i, limit=None, sweep=False))
        if c[i] > hh[i] and c[i - 1] <= hh[i - 1]:
            out.append(dict(family="20봉돌파", side=1, i=i, limit=None, sweep=False))
        if c[i] < ll[i] and c[i - 1] >= ll[i - 1]:
            out.append(dict(family="20봉돌파", side=-1, i=i, limit=None, sweep=False))
        if e20[i - 1] <= e50[i - 1] and e20[i] > e50[i]:
            out.append(dict(family="EMA교차", side=1, i=i, limit=None, sweep=False))
        if e20[i - 1] >= e50[i - 1] and e20[i] < e50[i]:
            out.append(dict(family="EMA교차", side=-1, i=i, limit=None, sweep=False))
    return out


def outcome(df: pd.DataFrame, atr: np.ndarray, s: dict, wait: int, hold: int):
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    n, side, i = len(c), s["side"], s["i"]
    if i + 1 >= n or not np.isfinite(atr[i]):
        return None
    if s["limit"] is None:                      # 신호 캔들 종가에 시장가
        t0, fill, fee_in = i, c[i], TAKER
        start = i + 1
    else:                                       # 지정가가 wait 안에 닿으면 체결
        t0 = next((t for t in range(i + 1, min(n, i + 1 + wait))
                   if ((l[t] <= s["limit"]) if side > 0 else (h[t] >= s["limit"]))), None)
        if t0 is None:
            return None
        fill = min(o[t0], s["limit"]) if side > 0 else max(o[t0], s["limit"])
        fee_in, start = MAKER, t0
    risk = STOP_ATR * atr[i]
    stop, target = fill - side * risk, fill + side * TP_R * risk
    ei, ex, oc = _manage(o, h, l, c, side, start, fill, stop, target, BTConfig(max_hold=hold))
    fee = fee_in * fill + (MAKER if oc == "tp" else TAKER) * ex
    return dict(t_entry=t0, t_exit=ei, entry=fill, r=(side * (ex - fill) - fee) / risk,
                stop_pct=risk / fill, outcome=oc)


def build_symbol(symbol: str) -> pd.DataFrame:
    df1 = fetch_binance_archive(symbol, "1h")
    daily = daily_indicators(resample(df1, "1D").set_index("time"))
    daily["rsi_d"] = rsi(daily["close"])
    daily["dist_sma200_d"] = daily["close"] / daily["sma200"] - 1
    dprev = daily[["score", "rsi_d", "dist_sma200_d"]].shift(1)        # 전날까지 확정된 값
    fund = fetch_funding(symbol)
    fprev = fund.shift(1)
    frank = fund.rolling(90, min_periods=30).rank(pct=True).shift(1)
    rows = []
    df4 = resample(df1, "4h")
    f4 = tf_features(df4)
    close4 = (df4["time"] + pd.Timedelta("4h")).to_numpy()
    trend4 = np.sign(df4["close"] - f4["ema200"]).to_numpy()
    for tf, df, wait, hold, step in (("1h", df1, 24, 48, "1h"), ("4h", df4, 12, 30, "4h")):
        f = f4 if tf == "4h" else tf_features(df)
        atr = f["atr"].to_numpy()
        times = df["time"]
        fv = f.to_dict("series")
        for s in signals(df, f, wait):
            res = outcome(df, atr, s, wait, hold)
            if res is None:
                continue
            i, side = s["i"], s["side"]
            t_close = times.iat[i] + pd.Timedelta(step)
            day = times.iat[i].floor("D")
            k = int(np.searchsorted(close4, t_close, side="right")) - 1
            row = dict(symbol=symbol[:3], tf=tf, family=s["family"], side=side, time=times.iat[i],
                       entry_time=times.iat[res["t_entry"]], exit_time=times.iat[res["t_exit"]] + pd.Timedelta(step),
                       sweep=bool(s["sweep"]), limit_entry=s["limit"] is not None, **res)
            # 방향 기준으로 바꾼 근거들 (값이 클수록 '신호 방향에 우호적')
            row.update(
                day_score=side * dprev["score"].get(day, np.nan),
                day_rsi=(dprev["rsi_d"].get(day, np.nan) if side > 0 else 100 - dprev["rsi_d"].get(day, np.nan)),
                day_dist200=side * dprev["dist_sma200_d"].get(day, np.nan),
                trend4h=side * trend4[k] if k >= 200 else np.nan,
                tf_trend=side * np.sign(df["close"].iat[i] - fv["ema200"].iat[i]),
                rsi=fv["rsi"].iat[i] if side > 0 else 100 - fv["rsi"].iat[i],
                dist_ema20=side * fv["dist_ema20"].iat[i],
                dist_ema200=side * fv["dist_ema200"].iat[i],
                ret20=side * fv["ret20"].iat[i],
                close_pos=fv["close_pos"].iat[i] if side > 0 else 1 - fv["close_pos"].iat[i],
                funding=side * fprev.get(day, np.nan),
                funding_rank=(frank.get(day, np.nan) if side > 0 else 1 - frank.get(day, np.nan)),
                # 방향과 무관한 근거
                adx=fv["adx"].iat[i], vol_rank=fv["vol_rank"].iat[i], bb_width_rank=fv["bb_width_rank"].iat[i],
                vol_ratio=fv["vol_ratio"].iat[i], body_ratio=fv["body_ratio"].iat[i],
                hour=times.iat[i].hour, weekday=times.iat[i].weekday(),
            )
            rows.append(row)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT")
    a = ap.parse_args()
    data = pd.concat([build_symbol(s) for s in a.symbols.split(",")], ignore_index=True)
    data = data[data.time >= "2018-03-01"]          # 일봉 200일선이 계산되는 시점부터
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data.to_pickle(OUT)
    print(f"신호 {len(data):,}건 저장: {OUT}")
    print(data.groupby(["tf", "family"]).size().unstack(0))


if __name__ == "__main__":
    main()
