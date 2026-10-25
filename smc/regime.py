"""국면 전환형 롱·숏 전략: 여러 지표의 점수로 롱/숏 비중을 정하고,
반전 신호에 분할 익절, 손절선에 닿으면 정리 후 국면 변화 때 다시 진입한다.

규칙(검증 전에 고정)
  국면 점수   : 종가 vs 200일선, 50일선 vs 200일선, 90일 수익률 부호 → 각 ±1, 합 −3~+3
  기본 비중   : +3 → 롱 100%, +1 → 롱 50%, −1 → 숏 50%, −3 → 숏 100% (레버리지 없음)
  분할 익절   : 종가가 20일 EMA를 포지션 반대 방향으로 넘으면 비중 절반
  약손절      : 진입가에서 일봉 ATR × 2.5 역행하면 정리 → 점수가 바뀔 때까지 쉬기
  실행        : 일봉 종가로 판단, 다음 날 보유. Bybit 선물 수수료 0.055% + 실제 펀딩비

사용:  python -m smc.regime
"""
from __future__ import annotations

import io
import zipfile

import numpy as np
import pandas as pd

from .data import ARCHIVE, fetch_binance_archive, resample

FEE = 0.00055
DEFAULT_FUNDING = 0.0003   # 선물 상장 전 구간: 8시간 0.01% × 3 (가장 흔한 기본값)


def fetch_funding(symbol: str) -> pd.Series:
    """일별 펀딩비 합계 (롱이 내는 비율, 음수면 롱이 받음). data.binance.vision, 캐시 저장."""
    import requests

    out = ARCHIVE / f"{symbol}_funding.csv"
    if out.exists():
        s = pd.read_csv(out, index_col=0, parse_dates=True).iloc[:, 0]
        if s.index[-1] >= pd.Timestamp.now(tz="UTC").normalize() - pd.offsets.MonthBegin(2):
            return s
    rows = []
    end = (pd.Timestamp.now(tz="UTC") - pd.offsets.MonthBegin(1)).strftime("%Y-%m")
    for m in pd.period_range("2019-09", end, freq="M"):
        url = f"https://data.binance.vision/data/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{m}.zip"
        r = requests.get(url, timeout=60)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            f = pd.read_csv(z.open(z.namelist()[0]))
        rows.append(f)
    f = pd.concat(rows)
    t = pd.to_datetime(f["calc_time"], unit="ms", utc=True).dt.floor("D")
    s = f["last_funding_rate"].groupby(t).sum().rename("funding")
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    s.to_csv(out)
    return s


def indicators(d: pd.DataFrame) -> pd.DataFrame:
    c = d["close"]
    d = d.copy()
    d["sma50"], d["sma200"] = c.rolling(50).mean(), c.rolling(200).mean()
    d["ret90"] = c / c.shift(90) - 1
    d["ema20"] = c.ewm(span=20, adjust=False).mean()
    pc = c.shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(), (d["low"] - pc).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    d["score"] = (np.sign(c - d["sma200"]) + np.sign(d["sma50"] - d["sma200"]) + np.sign(d["ret90"]))
    return d.dropna()


SIZE = {3: 1.0, 1: 0.5, -1: -0.5, -3: -1.0}


def simulate(d: pd.DataFrame, funding: pd.Series, mode: str) -> pd.DataFrame:
    """mode: 'long200' | 'ls200' | 'score' | 'score_half' | 'score_half_stop'."""
    c, h, l = d["close"].to_numpy(), d["high"].to_numpy(), d["low"].to_numpy()
    fund = funding.reindex(d.index).fillna(DEFAULT_FUNDING).to_numpy()
    n = len(d)
    w = np.zeros(n)          # 그날 종가에 정한, 다음 날 들고 갈 비중
    pnl = np.zeros(n)        # 그날 하루 손익률
    entry = stop = None
    rest_until_score = None  # 손절 후 쉬는 중이면 그때의 점수
    for t in range(n):
        prev = w[t - 1] if t else 0.0
        # 1) 오늘 하루 손익 (어제 정한 비중 기준). 손절선에 닿았으면 그 가격에 정리
        if t and prev != 0:
            r = c[t] / c[t - 1] - 1
            hit = stop is not None and ((l[t] <= stop) if prev > 0 else (h[t] >= stop))
            if hit:
                r = stop / c[t - 1] - 1
            pnl[t] = prev * r - prev * fund[t]
            if hit:
                pnl[t] -= abs(prev) * FEE
                prev, entry, stop = 0.0, None, None
                rest_until_score = d["score"].iat[t]
        # 2) 오늘 종가로 내일 비중 결정
        s = int(d["score"].iat[t])
        if mode == "long200":
            target = 1.0 if c[t] > d["sma200"].iat[t] else 0.0
        elif mode == "ls200":
            target = 1.0 if c[t] > d["sma200"].iat[t] else -1.0
        else:
            target = SIZE[s]
            if mode in ("score_half", "score_half_stop"):
                against = c[t] < d["ema20"].iat[t] if target > 0 else c[t] > d["ema20"].iat[t]
                if against:
                    target /= 2
            if mode == "score_half_stop":
                if rest_until_score is not None:
                    if s == rest_until_score:
                        target = 0.0
                    else:
                        rest_until_score = None
                if target != 0 and (prev == 0 or np.sign(target) != np.sign(prev)):
                    entry = c[t]
                    stop = entry - np.sign(target) * 2.5 * d["atr"].iat[t]
                elif target == 0:
                    entry = stop = None
        pnl[t] -= abs(target - prev) * FEE
        w[t] = target
    out = pd.DataFrame({"w": w, "pnl": pnl}, index=d.index)
    out["equity"] = 1000 * np.cumprod(1 + out["pnl"])
    return out


def metrics(eq: pd.Series, w: pd.Series) -> dict:
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return {"final": eq.iloc[-1] / eq.iloc[0] * 1000, "cagr": (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1,
            "mdd": (eq / eq.cummax() - 1).min(), "trades": int((w.diff().abs() > 1e-9).sum()),
            "long": (w > 0).mean(), "short": (w < 0).mean()}


MODES = {
    "그냥 보유": None,
    "200일선 롱만": "long200",
    "200일선 롱·숏 전환": "ls200",
    "국면 점수 롱·숏": "score",
    "+ 반전 시 분할 익절": "score_half",
    "+ 분할 익절 + 약손절 전환": "score_half_stop",
}


def main():
    for sym in ("BTCUSDT", "ETHUSDT"):
        d = indicators(resample(fetch_binance_archive(sym, "1h"), "1D").set_index("time"))
        fund = fetch_funding(sym)
        print(f"\n■ {sym}  {d.index[0]:%Y-%m-%d} ~ {d.index[-1]:%Y-%m-%d}  ($1,000 시작)")
        print(f"  {'방식':22} {'전체 최종':>10} {'연평균':>7} {'최대낙폭':>7} | {'설계 18–21 연평균/낙폭':>20} | {'검증 22–26 연평균/낙폭':>20} | 매매  롱/숏 비중")
        for name, mode in MODES.items():
            if mode is None:
                eq = 1000 * d["close"] / d["close"].iloc[0]
                w = pd.Series(1.0, index=d.index)
            else:
                s = simulate(d, fund, mode)
                eq, w = s["equity"], s["w"]
            a = metrics(eq, w)
            tr, te = metrics(eq[:"2021"], w[:"2021"]), metrics(eq["2022":], w["2022":])
            print(f"  {name:22} ${a['final']:>9,.0f} {a['cagr']*100:+6.1f}% {a['mdd']*100:6.1f}% |"
                  f" {tr['cagr']*100:+8.1f}% / {tr['mdd']*100:6.1f}%    | {te['cagr']*100:+8.1f}% / {te['mdd']*100:6.1f}%    |"
                  f" {a['trades']:4}  {a['long']*100:3.0f}%/{a['short']*100:3.0f}%")


if __name__ == "__main__":
    main()
