"""한국 상장 보통주 목록 + Yahoo 섹터 수집 -> data/universe.csv"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from yahoo import Yahoo  # noqa: E402

SECTORS = ["Technology", "Healthcare", "Industrials", "Consumer Cyclical",
           "Consumer Defensive", "Basic Materials", "Financial Services",
           "Communication Services", "Energy", "Utilities", "Real Estate"]
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "universe.csv")


def collect(y, operands):
    rows, off = [], 0
    while True:
        res = y.screener(operands, offset=off)
        q = res.get("quotes", [])
        rows += q
        off += len(q)
        if not q or off >= res["total"]:
            return rows


def main():
    y = Yahoo()
    base = [{"operator": "eq", "operands": ["region", "kr"]}]
    allq = {q["symbol"]: q for q in collect(y, base)}
    print("total", len(allq))
    sector = {}
    for s in SECTORS:
        qs = collect(y, base + [{"operator": "eq", "operands": ["sector", s]}])
        for q in qs:
            sector[q["symbol"]] = s
        print(s, len(qs))
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "name", "market", "sector", "market_cap", "shares"])
        for sym, q in allq.items():
            mkt = {"KSC": "KOSPI", "KOE": "KOSDAQ"}.get(q.get("exchange"), q.get("exchange"))
            w.writerow([sym, q.get("longName") or q.get("shortName"), mkt,
                        sector.get(sym, "Unknown"), q.get("marketCap"),
                        q.get("sharesOutstanding")])


if __name__ == "__main__":
    main()
