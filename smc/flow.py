"""거래량 델타(시장가 매수 − 시장가 매도)가 들어 있는 캔들 받기 (바이낸스 공개 저장소, 현물 1시간봉).

바이낸스 캔들 파일의 9번째 열이 '시장가 매수 체결량(taker buy base volume)'이다.
  델타 = 시장가 매수 − 시장가 매도 = 2 × 시장가 매수 − 전체 거래량
  CVD  = 델타의 누적 합
"""
from __future__ import annotations

import io
import zipfile

import pandas as pd

from .data import ARCHIVE


def _read(content: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        raw = pd.read_csv(z.open(z.namelist()[0]), header=None)
    raw = raw[pd.to_numeric(raw[0], errors="coerce").notna()]
    ts = raw[0].astype("int64")
    ts = ts.where(ts < 10**14, ts // 1000)
    return pd.DataFrame({"time": pd.to_datetime(ts, unit="ms", utc=True), "open": raw[1].astype(float), "high": raw[2].astype(float),
                         "low": raw[3].astype(float), "close": raw[4].astype(float), "volume": raw[5].astype(float),
                         "taker_buy": raw[9].astype(float)})


def fetch_flow(symbol: str = "BTCUSDT", start: str = "2017-08") -> pd.DataFrame:
    import requests

    out = ARCHIVE / f"{symbol}_1h_flow.csv.gz"
    have = pd.read_csv(out) if out.exists() else None
    if have is not None:
        have["time"] = pd.to_datetime(have.time, utc=True, format="ISO8601")
    frames = [] if have is None else [have]
    last = have.time.iloc[-1] if have is not None else None
    base = "https://data.binance.vision/data/spot"
    end = (pd.Timestamp.now(tz="UTC") - pd.offsets.MonthBegin(1)).strftime("%Y-%m")
    for m in pd.period_range(start, end, freq="M"):
        if last is not None and m < last.tz_localize(None).to_period("M"):
            continue
        r = requests.get(f"{base}/monthly/klines/{symbol}/1h/{symbol}-1h-{m}.zip", timeout=60)
        if r.status_code == 200:
            frames.append(_read(r.content))
    for d in pd.date_range(pd.Timestamp.now(tz="UTC").normalize().replace(day=1), pd.Timestamp.now(tz="UTC").normalize(), freq="D"):
        r = requests.get(f"{base}/daily/klines/{symbol}/1h/{symbol}-1h-{d:%Y-%m-%d}.zip", timeout=60)
        if r.status_code == 200:
            frames.append(_read(r.content))
    df = pd.concat(frames, ignore_index=True)
    df["time"] = pd.to_datetime(df.time, utc=True)
    df = df.drop_duplicates("time").sort_values("time").reset_index(drop=True)
    df.to_csv(out, index=False)
    return df


def to_tf(h: pd.DataFrame, rule: str) -> pd.DataFrame:
    g = h.set_index("time").resample(rule)
    d = g.agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum", "taker_buy": "sum"}).dropna().reset_index()
    d["delta"] = 2 * d.taker_buy - d.volume
    return d
