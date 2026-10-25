"""시세 데이터 불러오기: 로컬 CSV, 업비트, 바이낸스.

모든 함수는 같은 형태의 DataFrame을 돌려준다.
    columns = time(UTC, tz-aware), open, high, low, close, volume
    오래된 캔들 → 최신 캔들 순서, index는 0부터.
"""
from __future__ import annotations

import time as _time
from pathlib import Path

import numpy as np
import pandas as pd

COLUMNS = ["time", "open", "high", "low", "close", "volume"]
DEFAULT_CSV = Path(__file__).resolve().parent.parent / "data" / "BTCUSD_1h_coinbase.csv"


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df[COLUMNS].copy()
    df["time"] = pd.to_datetime(df["time"], utc=True)
    for c in COLUMNS[1:]:
        df[c] = df[c].astype(float)
    return df.sort_values("time").drop_duplicates("time").reset_index(drop=True)


def load_csv(path: str | Path = DEFAULT_CSV) -> pd.DataFrame:
    return _normalize(pd.read_csv(path))


# ---------------------------------------------------------------- 업비트
_UPBIT_UNITS = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}


def fetch_upbit(market: str = "KRW-BTC", interval: str = "1h", count: int = 1000) -> pd.DataFrame:
    """업비트 캔들. 한 번에 200개까지라 나눠서 받는다. 인증 필요 없음."""
    import requests

    if interval in _UPBIT_UNITS:
        url = f"https://api.upbit.com/v1/candles/minutes/{_UPBIT_UNITS[interval]}"
    elif interval == "1d":
        url = "https://api.upbit.com/v1/candles/days"
    else:
        raise ValueError(f"지원하지 않는 interval: {interval}")

    rows, to = [], None
    while len(rows) < count:
        params = {"market": market, "count": min(200, count - len(rows))}
        if to:
            params["to"] = to
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows.extend(batch)
        to = batch[-1]["candle_date_time_utc"] + "Z"
        _time.sleep(0.12)  # 초당 요청 제한(10회) 여유

    df = pd.DataFrame(rows).rename(columns={
        "candle_date_time_utc": "time", "opening_price": "open", "high_price": "high",
        "low_price": "low", "trade_price": "close", "candle_acc_trade_volume": "volume",
    })
    return _normalize(df)


# ---------------------------------------------------------------- 바이낸스
def fetch_binance(symbol: str = "BTCUSDT", interval: str = "1h", count: int = 1000) -> pd.DataFrame:
    """바이낸스 현물 캔들. 한 번에 1000개까지라 나눠서 받는다. 인증 필요 없음."""
    import requests

    url = "https://api.binance.com/api/v3/klines"
    rows, end = [], None
    while len(rows) < count:
        params = {"symbol": symbol, "interval": interval, "limit": min(1000, count - len(rows))}
        if end:
            params["endTime"] = end
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        rows = batch + rows
        end = batch[0][0] - 1

    df = pd.DataFrame([r[:6] for r in rows], columns=COLUMNS)
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    return _normalize(df)


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """1시간봉 → 4시간봉 등 상위 타임프레임으로 묶기. rule 예: '4h', '1D'."""
    out = (df.set_index("time")
             .resample(rule)
             .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
             .dropna()
             .reset_index())
    return out[COLUMNS]


def drop_unclosed(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """거래소가 주는 마지막 캔들은 아직 진행 중일 수 있으니 버린다. 신호는 마감된 캔들로만."""
    step = pd.Timedelta(interval.replace("m", "min"))
    now = pd.Timestamp.now(tz="UTC")
    return df[df["time"] + step <= now].reset_index(drop=True)


# ---------------------------------------------------------------- 바이낸스 공개 데이터 저장소
ARCHIVE = Path(__file__).resolve().parent.parent / "data" / "binance"


def fetch_binance_archive(symbol: str = "BTCUSDT", interval: str = "1h", start: str = "2017-08",
                          end: str | None = None, cache: Path = ARCHIVE) -> pd.DataFrame:
    """data.binance.vision 의 월별 캔들 파일을 받아 합친다. 받은 파일은 cache 에 저장해 재사용.

    국가 차단이 있는 거래소 API 대신 쓰는 과거 데이터용. 인증 필요 없음.
    """
    import io
    import zipfile

    import requests

    end = end or (pd.Timestamp.now(tz="UTC") - pd.offsets.MonthBegin(1)).strftime("%Y-%m")
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"{symbol}_{interval}.csv.gz"
    have = load_csv(out) if out.exists() else None
    months = pd.period_range(start, end, freq="M")
    if have is not None and len(have):
        last = have["time"].iloc[-1].tz_localize(None).to_period("M")
        months = [m for m in months if m >= last]
    frames = [] if have is None else [have]
    base = "https://data.binance.vision/data/spot/monthly/klines"
    for m in months:
        url = f"{base}/{symbol}/{interval}/{symbol}-{interval}-{m}.zip"
        r = requests.get(url, timeout=60)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            raw = pd.read_csv(z.open(z.namelist()[0]), header=None)
        raw = raw[pd.to_numeric(raw[0], errors="coerce").notna()]  # 헤더 줄이 있는 파일 대비
        ts = raw[0].astype("int64")
        unit = np.where(ts > 10**14, "us", "ms")                    # 2025년부터 마이크로초 단위
        t = pd.to_datetime(ts.where(unit == "ms", ts // 1000), unit="ms", utc=True)
        frames.append(pd.DataFrame({"time": t, "open": raw[1], "high": raw[2], "low": raw[3],
                                    "close": raw[4], "volume": raw[5]}))
    df = _normalize(pd.concat(frames, ignore_index=True))
    df.assign(time=df["time"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")).to_csv(out, index=False)
    return df


def load(source: str, symbol: str | None = None, interval: str = "1h", count: int = 1000) -> pd.DataFrame:
    """source: 'upbit' | 'binance' | 'archive'(바이낸스 공개 저장소) | CSV 파일 경로."""
    if source == "upbit":
        return fetch_upbit(symbol or "KRW-BTC", interval, count)
    if source == "binance":
        return fetch_binance(symbol or "BTCUSDT", interval, count)
    if source == "archive":
        return fetch_binance_archive(symbol or "BTCUSDT", interval)
    return load_csv(source)
