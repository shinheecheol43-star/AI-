"""하루 한 번, 장 마감 직후(15:41 무렵) 실행: 오늘 종가로 판단 → 청산·진입 주문 (장마감 후 시간외 종가).

  python run_daily.py                    # 오늘
  python run_daily.py --date 2026-11-13  # DRY 모드에서 과거 하루를 다시 돌려 보기 (연습용)
  python run_daily.py --force            # 오늘 이미 돌았어도 다시 (주의: 주문이 두 번 나갈 수 있음)
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from broker import DryBroker, make_broker
from common import config, load_state, lock, log, save_state, trade_record
from data import load_all
from strategy import KODEX200, NAME, Market, cost_of, plan_entries

KIND = {"stock": "주식", "box": "박스권 KODEX200", "inv": "인버스", "core": "코어 KODEX200"}


def exit_key(p):
    return p["code"] if p["kind"] == "stock" else p["kind"] + p.get("src", "")


def sync(st, acct, today):
    """증권사 실제 보유 수량과 맞추기: 체결 안 된 매수는 줄이고 돈을 돌려놓는다."""
    hold = acct["hold"]
    for code in {p["code"] for p in st["positions"]}:
        ps = [p for p in st["positions"] if p["code"] == code]
        short = sum(p["qty"] for p in ps) - hold.get(code, 0)
        for p in sorted(ps, key=lambda p: (not p.get("pending"), p["entry_date"]), reverse=False):
            if short <= 0:
                break
            take = min(short, p["qty"])
            p["qty"] -= take
            short -= take
            st["cash"] += take * p["price"] * (1 + cost_of(code))
            log(f"⚠ {NAME.get(code, code)} 계좌 수량이 기록보다 {take}주 적음 → 기록 줄임 ({'미체결' if p.get('pending') else '수동 매도?'})")
        for p in ps:
            p.pop("pending", None)
    st["positions"] = [p for p in st["positions"] if p["qty"] > 0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--cache", action="store_true", help="야후에서 새로 받지 않고 저장된 데이터 사용 (연습용)")
    a = ap.parse_args()
    cfg = config()
    br = make_broker(cfg)
    dry = isinstance(br, DryBroker)
    if a.date and not dry and not os.environ.get("KR_TRADER_TEST"):
        raise SystemExit("--date 는 DRY 모드에서만 씁니다.")
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    today = pd.Timestamp(a.date or now.strftime("%Y-%m-%d"))
    if not a.date and now.strftime("%H:%M") < "15:31":
        raise SystemExit("장 마감(15:30) 뒤에 실행하세요. 오늘 종가가 확정돼야 합니다.")
    eo, xo = cfg.get("ENTRY_ORDER_TYPE", "81"), cfg.get("EXIT_ORDER_TYPE", "81")

    with lock():
        st = load_state(cfg)
        if st.get("mode") != br.mode:
            raise SystemExit(f"state.json 은 {st.get('mode')} 모드 기록입니다. 모드를 바꾸려면 state.json 을 다른 이름으로 옮기고 시작하세요.")
        if st["last_run"] >= str(today.date()) and not a.force:
            log(f"{today.date()} 은 이미 실행했습니다 (--force 로 다시).")
            return
        data = load_all(refresh=not a.cache)
        if not dry:
            got = 0
            for code, d in data.items():
                try:
                    bar = br.today_bar(code)
                except Exception as e:
                    log(f"  키움 일봉 {code} 실패: {e}")
                    bar = None
                if bar:
                    d.loc[today, list(bar)] = list(bar.values())
                    got += 1
            data = {k: d.sort_index() for k, d in data.items()}
            log(f"키움 오늘 봉 {got}/{len(data)}개 반영")
        if a.date:
            data = {k: d[d.index <= today] for k, d in data.items()}
        if today not in data[KODEX200].index:
            log(f"{today.date()} KODEX 200 오늘 봉이 없습니다 (휴장이거나 아직 데이터 전). 아무것도 안 함.")
            return
        mk = Market(data)
        i = mk.i_of(today)
        acct = br.account()
        if acct:
            sync(st, acct, today)
        pos = st["positions"]
        for p in pos:
            p["entry_i"] = mk.i_of(pd.Timestamp(p["entry_date"]))
        last_exit = {k: int(np.searchsorted(mk.dates, pd.Timestamp(v))) for k, v in st["last_exit"].items()}
        state_txt = mk.k.state.iat[i]
        lines = [f"■ {today.date()} [{br.mode}] 시장 상태 {state_txt}" + (" · 강한 상승(코어 ON)" if mk.k.core_on.iat[i] else "")
                 + (" · 지수 20일선 아래(위험 0.5%)" if mk.k.weak.iat[i] else "")]

        sells = []
        for p in list(pos):
            if p["entry_i"] >= i:
                continue
            px = mk.intraday_exit(p, i)
            if px is not None:
                why = "손절(장중)" if dry else "손절가 이탈 · 장중 감시가 못 팔아 종가에 매도"
                sells.append((p, px if dry else mk.price(p["code"], i), why))
                continue
            why = mk.close_update(p, i)
            if why:
                sells.append((p, mk.price(p["code"], i), why))
        for p, px, why in sells:
            no = br.order("sell", p["code"], p["qty"], xo)
            st["cash"] += p["qty"] * px * (1 - cost_of(p["code"]))
            st["last_exit"][exit_key(p)] = str(today.date())
            pnl = p["qty"] * (px * (1 - cost_of(p["code"])) - p["price"] * (1 + cost_of(p["code"])))
            lines.append(f"  매도 {KIND[p['kind']]} {NAME.get(p['code'], p['code'])} {p['qty']}주 ≈{px:,.0f} · {why} · 손익 ≈{pnl:+,.0f}원")
            trade_record(dict(date=today.date(), side="매도", kind=p["kind"], code=p["code"], name=NAME.get(p["code"]), qty=p["qty"],
                              price=round(px), amount=round(p["qty"] * px), why=why, order_no=no))
            pos.remove(p)

        value = sum(p["qty"] * mk.price(p["code"], i) for p in pos)
        equity = st["cash"] + value
        cash = st["cash"]
        if acct:
            cash = min(cash, acct["cash"] + sum(p["qty"] * px for p, px, _ in sells))
        new = plan_entries(mk, i, pos, last_exit, equity, max(cash, 0), cost_of)
        for s in new:
            no = br.order("buy", s["code"], s["qty"], eo)
            st["cash"] -= s["qty"] * s["price"] * (1 + cost_of(s["code"]))
            rec = {k: v for k, v in s.items() if k not in ("entry_i",)}
            rec.update(entry_date=str(today.date()), pending=not dry, name=NAME.get(s["code"], s["code"]))
            pos.append(rec)
            stop_txt = f" · 손절 {s['stop']:,.0f}" if "stop" in s else (f" · KODEX200 {s['idx_stop']:,.0f} 넘으면 손절" if "idx_stop" in s else "")
            lines.append(f"  매수 {KIND[s['kind']]} {NAME.get(s['code'])} {s['qty']}주 ≈{s['price']:,.0f} ({s['qty']*s['price']:,.0f}원) · {s['why']}{stop_txt}")
            trade_record(dict(date=today.date(), side="매수", kind=s["kind"], code=s["code"], name=NAME.get(s["code"]), qty=s["qty"],
                              price=round(s["price"]), amount=round(s["qty"] * s["price"]), why=s["why"], order_no=no))
        for p in pos:
            p.pop("entry_i", None)
        if not sells and not new:
            lines.append("  오늘 주문 없음")
        value = sum(p["qty"] * mk.price(p["code"], i) for p in pos)
        lines.append(f"  보유 {len(pos)}건 · 평가 {value:,.0f}원 · 현금 {st['cash']:,.0f}원 · 합계 {st['cash'] + value:,.0f}원"
                     f" (시작 {st['start_capital']:,.0f}원 대비 {(st['cash'] + value) / st['start_capital'] * 100 - 100:+.1f}%)")
        for p in pos:
            stop = f"손절 {p['stop']:,.0f}" if "stop" in p and p["kind"] != "core" else (f"지수손절 {p['idx_stop']:,.0f}" if "idx_stop" in p else "")
            lines.append(f"   · {KIND[p['kind']]} {p['name']} {p['qty']}주 매수가 {p['price']:,.0f} 현재 {mk.price(p['code'], i):,.0f} {stop}")
        st["last_run"] = str(today.date())
        save_state(st)
        log("\n".join(lines), cfg, notify=True)


if __name__ == "__main__":
    main()
