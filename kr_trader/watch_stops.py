"""장중 손절 감시 (MOCK·REAL). 장 시작 전(08:59)에 켜 두면 15:20 까지 현재가를 보고, 손절가에 닿으면 시장가로 판다.

  주식      : 현재가 ≤ 손절가 → 매도
  박스 매매 : KODEX 200 현재가 ≤ 손절가 → 매도
  인버스    : KODEX 200 현재가 ≥ 지수 손절가 → KODEX 인버스 매도
코어 KODEX 200 은 손절 없이 종가(run_daily.py)에서만 판다. DRY 모드는 run_daily.py 가 장중 손절을 대신 계산하므로 필요 없다.
"""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from broker import DryBroker, make_broker
from common import config, load_state, lock, log, save_state, trade_record
from run_daily import KIND, exit_key, sync
from strategy import KODEX200, NAME, cost_of


def main():
    cfg = config()
    br = make_broker(cfg)
    if isinstance(br, DryBroker):
        raise SystemExit("DRY 모드에서는 장중 감시가 필요 없습니다 (run_daily.py 가 손절을 계산).")
    poll = float(cfg.get("POLL_SECONDS", 30))
    so = cfg.get("STOP_ORDER_TYPE", "3")
    end = cfg.get("WATCH_END", "15:20")
    synced = False
    log(f"장중 손절 감시 시작 [{br.mode}] · {poll:.0f}초마다 · {end} 까지")
    while datetime.now(ZoneInfo('Asia/Seoul')).strftime("%H:%M") < end:
        if datetime.now(ZoneInfo('Asia/Seoul')).strftime("%H:%M") < "09:00":
            time.sleep(10)
            continue
        try:
            with lock():
                st = load_state(cfg)
                if not synced:
                    sync(st, br.account(), None)
                    synced = True
                    save_state(st)
                watch = [p for p in st["positions"] if p["kind"] in ("stock", "box", "inv")]
                kpx = br.price(KODEX200) if any(p["kind"] in ("box", "inv") for p in watch) else None
                changed = False
                for p in watch:
                    if p["kind"] == "stock":
                        px = br.price(p["code"])
                        hit = px is not None and px <= p["stop"]
                    elif p["kind"] == "box":
                        hit = kpx is not None and kpx <= p["stop"]
                    else:
                        hit = kpx is not None and kpx >= p["idx_stop"]
                    if not hit:
                        continue
                    sell_px = br.price(p["code"]) or p["price"]
                    no = br.order("sell", p["code"], p["qty"], so)
                    st["cash"] += p["qty"] * sell_px * (1 - cost_of(p["code"]))
                    st["last_exit"][exit_key(p)] = datetime.now(ZoneInfo('Asia/Seoul')).strftime("%Y-%m-%d")
                    pnl = p["qty"] * (sell_px * (1 - cost_of(p["code"])) - p["price"] * (1 + cost_of(p["code"])))
                    st["positions"].remove(p)
                    changed = True
                    trade_record(dict(date=datetime.now(ZoneInfo('Asia/Seoul')).date(), side="매도", kind=p["kind"], code=p["code"], name=NAME.get(p["code"]),
                                      qty=p["qty"], price=round(sell_px), amount=round(p["qty"] * sell_px), why="장중 손절", order_no=no))
                    log(f"🔻 장중 손절 {KIND[p['kind']]} {NAME.get(p['code'])} {p['qty']}주 ≈{sell_px:,.0f} · 손익 ≈{pnl:+,.0f}원", cfg, notify=True)
                if changed:
                    save_state(st)
        except Exception as e:
            log(f"감시 오류(계속 진행): {e}")
        time.sleep(poll)
    log("장중 손절 감시 종료")


if __name__ == "__main__":
    main()
