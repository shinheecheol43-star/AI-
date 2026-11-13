"""universe.csv 전 종목 일봉 수집 -> data/prices.csv.gz

period1 은 분석 시작(2023-11-13)보다 앞선 2023-08-01 부터 받아
직전 거래일 종가·20일 평균 거래량·52주 고점 계산에 쓴다.
"""
import csv
import gzip
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from yahoo import Yahoo  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
P1 = int(datetime(2022, 11, 1, tzinfo=timezone.utc).timestamp())
P2 = int(time.time()) + 86400
KST = timezone(timedelta(hours=9))


def fetch(y, sym):
    r = y.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
              {"period1": P1, "period2": P2, "interval": "1d", "events": "split"})
    if r is None or r.status_code != 200:
        return sym, None
    res = r.json()["chart"]["result"]
    if not res or "timestamp" not in res[0]:
        return sym, []
    res = res[0]
    q = res["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(res["timestamp"]):
        vals = [q[k][i] for k in ("open", "high", "low", "close", "volume")]
        if None in vals:
            continue
        d = datetime.fromtimestamp(t, KST).strftime("%Y-%m-%d")
        out.append([sym, d] + vals)
    return sym, out


def main():
    with open(os.path.join(ROOT, "universe.csv"), encoding="utf-8") as f:
        syms = [r["symbol"] for r in csv.DictReader(f)]
    y = Yahoo()
    fails, n = [], 0
    with gzip.open(os.path.join(ROOT, "prices.csv.gz"), "wt", newline="") as gz:
        w = csv.writer(gz)
        w.writerow(["symbol", "date", "open", "high", "low", "close", "volume"])
        with ThreadPoolExecutor(6) as ex:
            futs = [ex.submit(fetch, y, s) for s in syms]
            for fu in as_completed(futs):
                sym, rows = fu.result()
                n += 1
                if rows is None:
                    fails.append(sym)
                else:
                    w.writerows(rows)
                if n % 250 == 0:
                    print(n, "done, fails", len(fails), flush=True)
    print("fails:", fails)


if __name__ == "__main__":
    main()
