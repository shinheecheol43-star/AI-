"""스윙 자동매매 봇 (Bybit USDT 무기한 선물): smc.system 의 스윙 신호를 그대로 주문으로 옮긴다.

한 시간마다 (4시간봉 기준 전략이라 충분)
  1. 거래소 손절 주문이 실행됐는지 확인 → 실행됐으면 그 묶음(lot)은 끝 (다시 들어가지 않음)
  2. 모델(백테스트와 같은 코드)에서 끝난 거래 → 거래소 포지션을 시장가로 정리하고 손절 주문 취소
  3. 모델의 추적 손절이 올라갔으면(숏은 내려갔으면) → 거래소 손절 주문 가격 수정
  4. 새 신호가 방금(5시간 이내) 나왔으면 → 시장가 진입 + 거래소에 손절 주문(Mark Price 기준)
     수량 = 계좌 × 리스크 ÷ (현재가 − 손절가), 열린 포지션 명목 합계가 계좌 × 3배를 넘지 않게
  비상 브레이크: 계좌가 최고점 대비 −15% 면 리스크 절반, −7% 까지 회복하면 원래대로
안전장치
  기본은 모의 실행(주문을 보내지 않음). 실제 주문은 --live, 테스트넷은 환경변수 BYBIT_TESTNET=1
  봇 폴더에 STOP_TRADING 파일을 만들면 새 진입만 멈춤 (손절 관리·청산은 계속)
  손절은 항상 거래소에 걸려 있어서, 봇이 꺼져도 손절은 거래소가 실행한다.

사용:  python -m smc.trader --once          # 모의 실행 한 번 (주문 안 보냄)
       python -m smc.trader                 # 모의 실행, 1시간마다
       BYBIT_TESTNET=1 python -m smc.trader --live    # 테스트넷 실제 주문
       python -m smc.trader --live          # 실전 (충분히 시험한 뒤에)
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import pandas as pd

from . import system as S
from .alert import send
from .bybit import Bybit, DryRun

STATE = Path(".trader_state.json")
KILL = Path("STOP_TRADING")
FRESH = pd.Timedelta("5h")
MAX_LEV = 3.0
BRAKE_DD, BRAKE_MULT, BRAKE_RECOVER = 0.15, 0.5, 0.07


def fmt(v: float) -> str:
    return f"{v:,.2f}" if v < 1000 else f"{v:,.0f}"


def cycle(ex, state: dict, snap: dict, risk_scale: float = 1.0, allow_new: bool = True) -> list[str]:
    """한 번 확인. snap: signal_bot.snapshot 결과 (스윙 거래 표 x, 기준 시각 asof)."""
    x, now = snap["x"], snap["asof"]
    x = x[x.src.isin(list(S.SWING))]
    lots = state.setdefault("lots", {})
    seen = set(state.setdefault("seen", []))
    msgs = []
    model = x.set_index("key")

    # 1·2·3. 열려 있는 묶음 관리
    for key, lot in list(lots.items()):
        sym, side = lot["symbol"], lot["side"]
        status, fill = ex.order_status(sym, lot["stop_id"])
        if status in ("Filled", "Triggered"):
            msgs.append(f"🛑 {lot['name']} 손절 실행 · 진입 {fmt(lot['entry'])} → 약 {fmt(fill or lot['stop'])}")
            del lots[key]
            continue
        if ex.position_size(sym, side) <= 0:
            ex.cancel(sym, lot["stop_id"])
            msgs.append(f"⚠️ {lot['name']} 거래소 포지션이 없어 기록을 정리했습니다 (수동 청산이었는지 확인하세요)")
            del lots[key]
            continue
        m = model.loc[key] if key in model.index else None
        if m is None or not bool(m.open):
            ex.market(sym, -side, lot["qty"], reduce_only=True, pos_side=side)
            ex.cancel(sym, lot["stop_id"])
            msgs.append(f"✅ {lot['name']} 청산 (모델 기준 거래 종료) · 수량 {lot['qty']}")
            del lots[key]
            continue
        new = float(m.stop)
        tick = ex.instrument(sym)["tick"]
        if side * (new - lot["stop"]) >= tick:
            ex.amend_stop(sym, lot["stop_id"], new)
            msgs.append(f"🔧 {lot['name']} 손절 이동 {fmt(lot['stop'])} → {fmt(new)}")
            lot["stop"] = new

    # 4. 새 진입
    eq = ex.equity()
    state["peak"] = max(state.get("peak", eq), eq)
    if not state.get("brake") and eq <= state["peak"] * (1 - BRAKE_DD):
        state["brake"] = True
        msgs.append(f"🧯 비상 브레이크: 계좌 {fmt(eq)} (최고 {fmt(state['peak'])} 대비 −{BRAKE_DD:.0%}) → 리스크 절반")
    elif state.get("brake") and eq >= state["peak"] * (1 - BRAKE_RECOVER):
        state["brake"] = False
        msgs.append("🧯 비상 브레이크 해제 → 리스크 원래대로")
    mult = risk_scale * (BRAKE_MULT if state.get("brake") else 1.0)
    fresh = x[x.open.astype(bool) & ~x.key.isin(list(lots)) & ~x.key.isin(list(seen))]
    for t in fresh.itertuples():
        seen.add(t.key)
        if now - t.entry > FRESH:
            continue                                   # 놓친 신호는 따라가지 않는다
        if not allow_new:
            msgs.append(f"⏸️ {t.symbol} {t.src} 신호가 나왔지만 새 진입이 멈춰 있습니다 (STOP_TRADING)")
            continue
        sym = t.symbol + "USDT"
        price, stop, side = ex.last_price(sym), float(t.stop), int(t.side)
        dist = side * (price - stop)
        if dist <= 0:
            msgs.append(f"⚠️ {t.symbol} {t.src}: 지금 가격이 이미 손절가를 넘어 진입하지 않습니다")
            continue
        risk = S.RISK[t.src] * mult
        expo = sum(lot["qty"] * ex.last_price(lot["symbol"]) for lot in lots.values())
        qty = min(eq * risk / dist, max(0.0, (MAX_LEV * eq - expo) / price))
        qty = ex.round_qty(sym, qty)
        if qty < ex.instrument(sym)["min_qty"]:
            msgs.append(f"⚠️ {t.symbol} {t.src}: 계산 수량이 최소 주문 수량보다 작아 건너뜁니다")
            continue
        ex.market(sym, side, qty)
        stop_id = ex.stop(sym, side, qty, stop)
        name = f"{t.symbol} {t.src}"
        lots[t.key] = {"name": name, "symbol": sym, "side": side, "qty": qty, "entry": price, "stop": stop, "stop_id": stop_id,
                       "opened": str(now)}
        msgs.append(f"{'🟢' if side > 0 else '🔴'} {name} 진입 {'롱' if side > 0 else '숏'} {qty} @ 약 {fmt(price)} · 손절 {fmt(stop)}"
                    f" (거래소 주문, Mark 기준) · 리스크 {risk*100:.2f}% ≈ {eq*risk:,.1f} USDT")
    state["seen"] = sorted(seen)[-2000:]
    state["asof"] = str(now)
    return msgs


def main():
    from .signal_bot import snapshot

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="실제로 주문을 보냄 (없으면 모의 실행)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--scale", type=float, default=float(os.environ.get("RISK_SCALE") or 1.0), help="리스크 배수 (1 = 거래당 0.5%)")
    ap.add_argument("--source", default="api")
    ap.add_argument("--state", default=None)
    a = ap.parse_args()
    syms = list(S.SYMS)
    if a.live:
        ex = Bybit()
        for s in syms:
            ex.setup(s + "USDT", int(MAX_LEV))
        mode = "테스트넷" if "testnet" in ex.base else "실전"
        path = Path(a.state or f".trader_state_{'testnet' if mode == '테스트넷' else 'live'}.json")
    else:
        ex = DryRun(float(os.environ.get("BOT_BALANCE_USDT") or 1000))
        mode = "모의 실행"
        path = Path(a.state or ".trader_state_dry.json")
    state = json.loads(path.read_text()) if path.exists() else {}
    if not state:                                     # 처음 켤 때: 이미 진행 중인 신호는 따라가지 않는다
        state["seen_init"] = True
    send(f"🤖 자동매매 봇 시작 ({mode}) · {', '.join(syms)} · 리스크 배수 {a.scale}")
    while True:
        try:
            snap = snapshot(syms, a.source)
            if isinstance(ex, DryRun):
                ex.prices = {s + "USDT": snap["last"][s] for s in syms}
            if state.pop("seen_init", False):
                state["seen"] = sorted(snap["x"][snap["x"].open.astype(bool)].key)
            for m in cycle(ex, state, snap, a.scale, allow_new=not KILL.exists()):
                send(f"[{mode}] {m}")
            path.write_text(json.dumps(state, ensure_ascii=False))
            print(f"[{pd.Timestamp.now(tz='Asia/Seoul'):%m-%d %H:%M}] 확인 완료 · 열린 묶음 {len(state.get('lots', {}))}개", flush=True)
        except Exception as e:
            send(f"[{mode}] ❗ 오류 (다음 주기에 다시 시도): {e}")
        if a.once:
            break
        nxt = pd.Timestamp.now(tz="UTC").floor("1h") + pd.Timedelta("1h") + pd.Timedelta("90s")
        time.sleep(max(30.0, (nxt - pd.Timestamp.now(tz="UTC")).total_seconds()))


if __name__ == "__main__":
    main()
