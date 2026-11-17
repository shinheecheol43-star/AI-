"""일봉 데이터: 야후 파이낸스 (무료, 키 필요 없음). 오늘 봉은 키움 값으로 덮어쓸 수 있다 (run_daily.py)."""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

from strategy import INVERSE, KODEX200, SECTOR

CACHE = Path(__file__).parent / "cache"


def yahoo(code: str) -> pd.DataFrame:
    for attempt in range(4):
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.KS",
                             params={"period1": 0, "period2": 4102444800, "interval": "1d"},
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            r.raise_for_status()
            j = r.json()["chart"]["result"][0]
            q = j["indicators"]["quote"][0]
            t = pd.to_datetime(j["timestamp"], unit="s", utc=True).tz_convert("Asia/Seoul").normalize().tz_localize(None)
            d = pd.DataFrame({k: q[k] for k in ("open", "high", "low", "close", "volume")}, index=t).dropna()
            d = d[(d.close > 0)]
            return d[~d.index.duplicated(keep="last")]
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))


def load_all(refresh: bool = True) -> dict[str, pd.DataFrame]:
    CACHE.mkdir(exist_ok=True)
    out = {}
    for code in [KODEX200, INVERSE, *SECTOR]:
        f = CACHE / f"{code}.csv"
        if refresh or not f.exists():
            try:
                d = yahoo(code)
                d.to_csv(f)
            except Exception as e:
                print(f"  [데이터] {code} 받기 실패: {e}" + (" → 저장된 값 사용" if f.exists() else ""))
                if not f.exists():
                    continue
                d = pd.read_csv(f, index_col=0, parse_dates=True)
        else:
            d = pd.read_csv(f, index_col=0, parse_dates=True)
        out[code] = d
    return out
