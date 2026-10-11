"""차트 시각화: 캔들 위에 OB·FVG 박스, 거짓 돌파 라인, 백테스트 진입/청산을 그린 HTML 한 장을 만든다.

외부 라이브러리 없이 캔버스로 그리므로 인터넷 없이도 열린다(글꼴만 온라인일 때 적용).

사용:
  python -m smc.chart                                   → reports/chart.html
  python -m smc.chart --resample 4h --out reports/chart_4h.html
  python -m smc.chart --source upbit --symbol KRW-BTC --count 2000
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .backtest import BTConfig, run
from .data import DEFAULT_CSV, load, resample
from .detectors import Params, find_fakeouts, find_fvgs, find_order_blocks

TEMPLATE = Path(__file__).with_name("chart_template.html")


def _zone_rows(df: pd.DataFrame, zones, max_wait: int) -> list[list]:
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    n, rows = len(df), []
    for z in zones:
        end = min(n - 1, z.confirm + max_wait)
        for t in range(z.confirm + 1, end + 1):
            if (l[t] <= z.entry) if z.side > 0 else (h[t] >= z.entry):
                end = t
                break
        start = z.confirm - (1 if z.kind == "OB" else 2)
        rows.append([z.kind, z.side, start, end, round(z.top, 2), round(z.bottom, 2), int(z.sweep)])
    return rows


def build(df: pd.DataFrame, title: str, p: Params = Params(), cfg: BTConfig = BTConfig(),
          standalone: bool = True) -> str:
    rep = run(df, p, cfg)
    zones = _zone_rows(df, find_order_blocks(df, p) + find_fvgs(df, p), cfg.max_wait)
    fakeouts = [[f.confirm, round(f.level, 2), f.side, int(f.trap)] for f in find_fakeouts(df, p)]
    trades = [[t["strategy"], t["side"], t["entry_i"], t["exit_i"], round(t["entry"], 2), round(t["exit"], 2),
               round(t["stop"], 2), round(t["target"], 2), round(t["r"], 3), int(bool(t["sweep"]))]
              for ts in rep["trades"].values() for t in ts]
    payload = {
        "title": title,
        "t": ((df["time"] - pd.Timestamp(0, tz="UTC")) // pd.Timedelta("1s")).tolist(),
        "o": df["open"].round(2).tolist(), "h": df["high"].round(2).tolist(),
        "l": df["low"].round(2).tolist(), "c": df["close"].round(2).tolist(),
        "zones": zones, "fakeouts": fakeouts, "trades": trades,
        "summary": {k: {kk: vv for kk, vv in v.items() if kk != "outcomes"} for k, v in rep["results"].items()},
        "data": rep["data"], "params": rep["params"], "config": rep["config"],
    }
    html = TEMPLATE.read_text(encoding="utf-8").replace("__PAYLOAD__", json.dumps(payload, separators=(",", ":")))
    return ("<!doctype html>\n<meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            + html) if standalone else html


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=str(DEFAULT_CSV), help="CSV 경로 | upbit | binance")
    ap.add_argument("--symbol")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--count", type=int, default=3000)
    ap.add_argument("--resample", help="예: 4h")
    ap.add_argument("--title", help="페이지 제목에 들어갈 종목 이름")
    ap.add_argument("--out", default="reports/chart.html")
    ap.add_argument("--fragment", action="store_true", help="doctype 없이 본문만 출력 (Artifact 게시용)")
    a = ap.parse_args()

    df = load(a.source, a.symbol, a.interval, a.count)
    tf = a.interval
    if a.resample:
        df, tf = resample(df, a.resample), a.resample
    name = a.title or a.symbol or ("BTC/USD" if a.source == str(DEFAULT_CSV) else a.source)
    cfg = BTConfig() if tf in ("1h", "1m", "5m", "15m", "30m") else BTConfig(max_wait=24, max_hold=120)
    html = build(df, f"{name} {tf}", cfg=cfg, standalone=not a.fragment)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(html, encoding="utf-8")
    print(f"저장: {a.out} ({len(html) / 1e6:.1f} MB) — 브라우저로 열면 됩니다.")


if __name__ == "__main__":
    main()
