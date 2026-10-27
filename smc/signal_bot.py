"""매매 신호 알림 봇: smc.system 과 같은 규칙·같은 코드로 신호를 찾아 알려 준다. 주문은 넣지 않는다.

기본은 스윙 전략(스윙 롱, 숏 S5, 숏 S2)만 알린다. 4시간봉 마감 기준이라 1시간마다 확인한다.
데이 롱(15분봉, 미국장 시간대)은 알림을 보고 사람이 따라가기 어려워 --with-day 를 줄 때만 포함한다.

알림 종류
  진입  : 전략, 방향, 근거(✅/❌), 근거 일치도 10점, 진입가·손절가·익절 참고가(1R·2R·3R와 과거 도달 비율), 권장 수량
  손절 상향 : 추적 손절이 0.3R 이상 유리하게 움직였을 때 새 손절가
  청산  : 손절선에 닿아 끝났을 때 결과(R)
  아침 브리핑 : 매일 오전 8시 이후 첫 확인 때 코인·미국 주식 공포·탐욕 지수, BTC·ETH 상태, 진행 중 신호 (smc.sentiment)
처음 켤 때 이미 진행 중인 신호는 '진행 중(신규 진입 비추천)'으로 한 번 정리해서 보낸다.

근거 일치도(10점) = 아래 5개 근거 중 신호 방향과 맞는 개수 × 2
  4h 200EMA 위(숏은 아래) · 전날 일봉 국면 +3(숏은 −3) · 4h RSI > 63(숏은 < 37)
  · 20EMA 이격 > ATR × 1.43(숏은 반대) · 전날 펀딩비 순위 하위 1/3(숏은 상위 1/3)
  스윙 롱은 이 중 4개 이상일 때만 신호가 나므로 8점 또는 10점이다.
  백테스트에서 이 점수는 결과를 예측하지 못했다(점수가 높다고 평균 R 이 높지 않음). 신호의 '모양'을 보여 주는 값이다.

텔레그램으로 받으려면 환경변수 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 를 설정한다(없으면 화면에만 출력).
권장 수량을 보려면 --balance 또는 환경변수 BOT_BALANCE_USDT 에 계좌 잔고(USDT)를 넣는다.

사용:  python -m smc.signal_bot                    # 스윙만, 바이낸스 API 로 1시간마다 확인 (내 PC·서버에서)
       python -m smc.signal_bot --with-day         # 데이 롱도 포함, 15분마다 확인
       python -m smc.signal_bot --once            # 한 번만 확인하고 종료
       python -m smc.signal_bot --source archive --once   # 공개 저장소 데이터로 시험 (하루 늦음)
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import daytrade, daytrade2, sentiment, system as S
from .alert import send
from .data import extend_with_api, extend_with_daily, fetch_binance_archive

STATE = Path(".signal_bot_state.json")
FRESH = {"데이 롱": pd.Timedelta("30min")}           # 이 시간 안에 알면 '지금 신호', 넘으면 '늦은 신호'
FRESH_SWING = pd.Timedelta("5h")
BRIEF_HOUR = 8                                       # 아침 브리핑 시각 (한국시간, 이 시각 이후 첫 확인 때)
STOP_STEP = 0.3                                      # 손절 상향 알림 기준 (R)
EV_NAMES = {1: ["4h 200EMA 위", "일봉 국면 +3", "4h RSI > 63", "20EMA 이격 > 1.43 ATR", "펀딩비 쏠림 없음(하위 1/3)"],
            -1: ["4h 200EMA 아래", "일봉 국면 −3", "4h RSI < 37", "20EMA 이격 < −1.43 ATR", "롱 쏠림(펀딩비 상위 1/3)"]}


def kst(t: pd.Timestamp) -> str:
    return t.tz_convert("Asia/Seoul").strftime("%m-%d %H:%M")


def px(sym: str, v: float) -> str:
    return f"{v:,.0f}" if v >= 1000 else f"{v:,.2f}"


def evidence(X: dict, t: pd.Timestamp, side: int) -> list[bool]:
    """t 시각에 확정돼 있던 마지막 4시간봉 기준 근거."""
    t4 = pd.DatetimeIndex(X["df"].time + pd.Timedelta("4h"))
    i = int(t4.searchsorted(t, side="right")) - 1
    c = X["c"][i]
    if side > 0:
        e = [c > X["e200"][i], X["score"][i] >= 3, X["rsi"][i] > S.Q_RSI, X["d20"][i] > S.Q_D20, X["frank"][i] <= S.Q_FUND]
    else:
        e = [c < X["e200"][i], X["score"][i] <= -3, X["rsi"][i] < 100 - S.Q_RSI, X["d20"][i] < -S.Q_D20,
             X["frank"][i] >= 1 - S.Q_FUND]
    return [bool(v) for v in e]


# ---------------------------------------------------------------- 상태 계산
def snapshot(syms, source: str, day: bool = False) -> dict:
    ivs = ("1h", "5m") if day else ("1h",)
    for s in syms:
        for iv in ivs:
            fetch_binance_archive(s + "USDT", iv)
            extend_with_daily(s + "USDT", iv)
            if source == "api":
                extend_with_api(s + "USDT", iv)
    Xs = {s: S.context(s) for s in syms}
    rows = [pd.concat([S.swing_trades(X) for X in Xs.values()], ignore_index=True)]
    h1 = {s: fetch_binance_archive(s + "USDT", "1h") for s in syms}
    for s in syms:
        Xs[s]["h1"] = h1[s]
    last = {s: h1[s].close.iloc[-1] for s in syms}
    asof = min(h1[s].time.iloc[-1] for s in syms) + pd.Timedelta("1h")
    day_open = {}
    if day:
        daytrade.prepare.cache_clear()               # 봇이 계속 돌 때 새 캔들을 다시 읽도록
        daytrade2.extra.cache_clear()
        dy, day_open = S.day_trades(syms)
        rows.append(dy)
        last = {s: daytrade.prepare(s).close.iloc[-1] for s in syms}
        asof = min(daytrade.prepare(s).index[-1] for s in syms) + pd.Timedelta("15min")
    for s, p in day_open.items():                    # 진행 중인 데이 롱
        rows.append(pd.DataFrame([{"symbol": s, "src": "데이 롱", "side": p["side"], "entry": p["time"] + pd.Timedelta("15min"),
                                   "exit": pd.NaT, "r": np.nan, "stop_pct": p["risk_px"] / p["entry"], "open": True,
                                   "p0": p["entry"], "stop": p["stop"], "mfe": p["mfe"]}]))
    x = pd.concat(rows, ignore_index=True)
    x["key"] = x.symbol + "|" + x.src + "|" + x.entry.astype(str)
    return {"x": x, "Xs": Xs, "last": last, "asof": asof}


def history(x: pd.DataFrame) -> dict:
    """전략별 과거 성적과 1R·2R·3R 도달 비율 (끝난 거래, 슬리피지 반영)."""
    done = x[~x.open.astype(bool)]
    out = {}
    for src, y in done.groupby("src"):
        r = y.r - 2 * S.SLIP / y.stop_pct
        out[src] = {"n": len(y), "win": (r > 0).mean(), "avg": r.mean(), "reach": [(y.mfe >= k).mean() for k in (1, 2, 3)]}
    return out


# ---------------------------------------------------------------- 메시지
def entry_msg(t, snap: dict, hist: dict, balance: float | None, late: bool, mood: dict | None = None) -> str:
    sym, side, p0 = t.symbol, int(t.side), t.p0
    one_r = p0 * t.stop_pct
    stop = t.stop if late and np.isfinite(t.stop) else p0 - side * one_r      # 늦은 신호는 지금의 손절선
    ev = evidence(snap["Xs"][sym], t.entry, side)
    score = 2 * sum(ev)
    h = hist.get(t.src)
    cur = snap["last"][sym]
    moved = side * (cur - p0) / one_r
    bar = "15분봉" if t.src == "데이 롱" else "4시간봉"
    lines = [f"{'🟢' if side > 0 else '🔴'} [{sym} {t.src}] {'롱' if side > 0 else '숏'} 진입 신호 · 근거 일치도 {score}/10 "
             f"{'■' * (score // 2)}{'□' * (5 - score // 2)}",
             f"신호 {kst(t.entry)} 한국시간 ({bar} 마감) · 지금 {px(sym, cur)}"]
    if late:
        hours = (snap["asof"] - t.entry).total_seconds() / 3600
        lines.append(f"⚠️ 늦은 알림: 신호 후 {hours:.0f}시간, 진입가 대비 {moved:+.2f}R. "
                     + ("0.5R 이상 움직여 신규 진입 비추천 (참고용)" if abs(moved) >= 0.5 else "아직 진입가 근처"))
    lines += [f"진입 {px(sym, p0)} (신호 봉 마감가, 시장가)",
              f"손절 {px(sym, stop)} ({(stop / (cur if late else p0) - 1) * 100:+.2f}%{' 지금 가격에서, 현재 손절선' if late else ', 1R'})"]
    reach = h["reach"] if h else [np.nan] * 3
    lines.append("익절 참고 " + " · ".join(f"{k}R {px(sym, p0 + side * k * one_r)} (과거 {r * 100:.0f}% 도달)"
                                         for k, r in zip((1, 2, 3), reach)))
    trail = ("15분봉 ATR×2 손절 → 1시간봉 ATR×3 추적, 미국장 마감 때 손실이면 청산·수익이면 본절" if t.src == "데이 롱"
             else f"{'최고가 − ' if side > 0 else '최저가 + '}4시간봉 ATR×3 추적")
    lines.append(f"청산: 고정 익절 없음, {trail}. 손절선이 움직이면 알려 드립니다.")
    lines.append("근거")
    lines += [f"  {'✅' if e else '❌'} {n}" for n, e in zip(EV_NAMES[side], ev)]
    if h:
        lines.append(f"이 전략 과거: {h['n']}건 · 승률 {h['win'] * 100:.0f}% · 평균 {h['avg']:+.2f}R")
    if mood is not None:
        lines += sentiment.mood_line(mood, side)
    risk = S.RISK[t.src]
    if balance:
        entry_px = cur if late else p0
        qty = balance * risk / abs(entry_px - stop)
        lines.append(f"권장 수량 (잔고 {balance:,.0f} USDT, 리스크 {risk * 100:.2f}%{', 지금 가격 기준' if late else ''}): "
                     f"{qty:.4f} {sym} · 명목 {qty * entry_px:,.0f} USDT (레버리지 {qty * entry_px / balance:.1f}배)")
    else:
        lines.append(f"리스크 {risk * 100:.2f}% (잔고를 --balance 로 넣으면 권장 수량 계산)")
    return "\n".join(lines)


def stop_msg(t, old: float) -> str:
    one_r = t.p0 * t.stop_pct
    lock = t.side * (t.stop - t.p0) / one_r
    return (f"🔧 [{t.symbol} {t.src}] 손절 이동 {px(t.symbol, old)} → {px(t.symbol, t.stop)}"
            f" (진입가 대비 {lock:+.2f}R {'수익 확보' if lock > 0 else '손실 축소'})")


def exit_msg(t) -> str:
    r = t.r - 2 * S.SLIP / t.stop_pct
    return f"{'✅' if r > 0 else '❌'} [{t.symbol} {t.src}] 청산 {kst(t.exit)} · 결과 {r:+.2f}R (진입 {kst(t.entry)} @ {px(t.symbol, t.p0)})"


# ---------------------------------------------------------------- 한 번 확인
def check(syms, source: str, state: dict, balance: float | None, day: bool = False) -> list[str]:
    snap = snapshot(syms, source, day)
    x, hist, now = snap["x"], history(snap["x"]), snap["asof"]
    opened = x[x.open.astype(bool)]
    msgs = []
    first = not state.get("started")
    mood = None
    if first:
        lines = [f"🤖 신호 봇 시작 ({', '.join(syms)} · {'스윙 + 데이 롱' if day else '스윙 롱·숏 S5·숏 S2'}, 데이터 {kst(now)} 한국시간까지)"]
        if opened.empty:
            lines.append("진행 중인 신호 없음")
        for t in opened.itertuples():
            one_r = t.p0 * t.stop_pct
            lines.append(f"· 진행 중 {t.symbol} {t.src} {'롱' if t.side > 0 else '숏'}: {kst(t.entry)} @ {px(t.symbol, t.p0)}, 현재 손절 "
                         f"{px(t.symbol, t.stop)}, 지금 {t.side * (snap['last'][t.symbol] - t.p0) / one_r:+.2f}R → 이미 시작된 신호라 신규 진입 비추천")
        msgs.append("\n".join(lines))
    alerted = state.setdefault("open", {})
    for t in opened.itertuples():
        if t.key in alerted:
            old = alerted[t.key]
            if t.side * (t.stop - old) >= STOP_STEP * t.p0 * t.stop_pct:
                msgs.append(stop_msg(t, old))
                alerted[t.key] = float(t.stop)
            continue
        if not first:
            late = now - t.entry > FRESH.get(t.src, FRESH_SWING)
            if mood is None:
                mood = sentiment.mood()                  # 진입 알림이 있을 때만 한 번 받는다
            msgs.append(entry_msg(t, snap, hist, balance, late, mood))
        alerted[t.key] = float(t.stop)
    closed = x.set_index("key")
    for k in [k for k in alerted if k not in set(opened.key)]:
        if k in closed.index and not bool(closed.loc[k, "open"]):
            msgs.append(exit_msg(closed.loc[[k]].reset_index().iloc[0]))
        del alerted[k]
    today = pd.Timestamp.now(tz="Asia/Seoul")
    if state.get("brief") != today.strftime("%Y-%m-%d") and today.hour >= BRIEF_HOUR:     # 하루 한 번 아침 브리핑
        msgs.append(sentiment.briefing(snap, today))
        state["brief"] = today.strftime("%Y-%m-%d")
    state["started"], state["asof"] = True, str(now)
    return msgs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--syms", default=",".join(S.SYMS))
    ap.add_argument("--source", default="api", help="api (바이낸스 실시간) | archive (공개 저장소, 하루 늦음)")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--balance", type=float, default=float(os.environ.get("BOT_BALANCE_USDT") or 0) or None)
    ap.add_argument("--state", default=str(STATE))
    ap.add_argument("--with-day", action="store_true", help="데이 롱 신호도 알림 (15분마다 확인)")
    a = ap.parse_args()
    syms, path = a.syms.split(","), Path(a.state)
    state = json.loads(path.read_text()) if path.exists() else {}
    tg = "텔레그램 연결됨" if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID") else "텔레그램 설정 없음 (화면에만 출력)"
    print(f"신호 봇 실행 중 · {', '.join(syms)} · {tg} · 이 창을 닫으면 봇이 꺼집니다", flush=True)
    while True:
        now = lambda: pd.Timestamp.now(tz="Asia/Seoul").strftime("%m-%d %H:%M")
        print(f"[{now()}] 시세 확인 중...", flush=True)
        try:
            msgs = check(syms, a.source, state, a.balance, a.with_day)
            for m in msgs:
                send(m)
            path.write_text(json.dumps(state, ensure_ascii=False))
            print(f"[{now()}] 확인 완료 · 새 알림 {len(msgs)}건 · 지켜보는 신호 {len(state.get('open', {}))}개", flush=True)
        except Exception as e:                       # 네트워크 오류 등으로 봇이 죽지 않게
            print(f"[{now()}] [오류, 다음 주기에 재시도] {e}", flush=True)
        if a.once:
            break
        step = pd.Timedelta("15min" if a.with_day else "1h")
        nxt = pd.Timestamp.now(tz="UTC").floor(step) + step + pd.Timedelta("40s")
        print(f"  다음 확인 {nxt.tz_convert('Asia/Seoul'):%H:%M}", flush=True)
        time.sleep(max(30.0, (nxt - pd.Timestamp.now(tz="UTC")).total_seconds()))


if __name__ == "__main__":
    main()
