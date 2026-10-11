"""오더블럭 / FVG / 거짓 돌파 알림 봇.

새 캔들이 마감될 때마다 검사해서 다음 상황을 알려 준다. 주문은 넣지 않는다(알림 전용).
  1) 새 존 생성     : 상승/하락 OB·FVG가 방금 확정됨 (진입가·손절가 안내)
  2) 존 도달        : 가격이 아직 안 쓰인 존에 처음 닿음 = 강의의 진입 타점
  3) 거짓 돌파 복귀 : 지지선 이탈 후 복귀 마감(매수) / 저항선 돌파 후 복귀 마감(매도)

텔레그램으로 받으려면 환경변수 두 개를 설정한다(없으면 화면에만 출력):
  TELEGRAM_BOT_TOKEN  : @BotFather 에게 받은 토큰
  TELEGRAM_CHAT_ID    : 내 채팅 ID (봇에게 아무 말이나 보낸 뒤
                        https://api.telegram.org/bot<토큰>/getUpdates 에서 확인)

사용:
  python -m smc.alert --source upbit --symbol KRW-BTC --interval 1h
  python -m smc.alert --source binance --symbol BTCUSDT --interval 15m --only-sweep
  python -m smc.alert --replay data/BTCUSD_1h_coinbase.csv --last 200   (과거 데이터로 시험)
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import pandas as pd

from .data import DEFAULT_CSV, drop_unclosed, load, load_csv
from .detectors import Params, Zone, find_fakeouts, find_fvgs, find_order_blocks

SIDE = {1: "상승", -1: "하락"}
ACTION = {1: "매수(Long)", -1: "매도(Short)"}


def _price(x: float) -> str:
    return f"{x:,.0f}" if x >= 1000 else f"{x:,.4g}"


def zone_state(df: pd.DataFrame, z: Zone, max_wait: int) -> tuple[str, float]:
    """존의 현재 상태와 익절 목표(파동 고점/저점).

    'waiting' 아직 안 닿음, 'touched_now' 마지막 캔들에서 처음 닿음, 'used' 이미 닿았음,
    'expired' 너무 오래됨, 'broken' 닿기 전에 손절선이 깨짐.
    """
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    last = len(df) - 1
    wave = h[z.confirm] if z.side > 0 else l[z.confirm]
    for t in range(z.confirm + 1, last + 1):
        if t - z.confirm > max_wait:
            return "expired", wave
        touched = l[t] <= z.entry if z.side > 0 else h[t] >= z.entry
        if touched:
            return ("touched_now" if t == last else "used"), wave
        wave = max(wave, h[t]) if z.side > 0 else min(wave, l[t])
    return "waiting", wave


def scan(df: pd.DataFrame, p: Params, kinds: set[str], only_sweep: bool, max_wait: int,
         min_rr: float = 1.0) -> list[tuple[str, str]]:
    """마지막 마감 캔들 기준으로 알림 목록 [(중복방지 키, 메시지)] 을 만든다."""
    last = len(df) - 1
    t_last = df["time"].iloc[-1]
    alerts = []

    zones: list[Zone] = []
    if "OB" in kinds:
        zones += find_order_blocks(df, p)
    if "FVG" in kinds:
        zones += find_fvgs(df, p)
    for z in zones:
        if only_sweep and not z.sweep:
            continue
        if last - z.confirm > max_wait:
            continue
        key = f"{z.kind}:{z.side}:{df['time'].iloc[z.confirm].isoformat()}"
        tag = " · 유동성 흡수 동반" if z.sweep else ""
        if z.confirm == last:
            alerts.append((key + ":new", (
                f"🆕 {SIDE[z.side]} {z.kind} 생성{tag}\n"
                f"구간 {_price(z.bottom)} ~ {_price(z.top)}\n"
                f"진입 대기가 {_price(z.entry)} / 손절 {_price(z.stop)}")))
            continue
        state, wave = zone_state(df, z, max_wait)
        if state == "touched_now":
            risk = abs(z.entry - z.stop)
            rr = abs(wave - z.entry) / risk if risk else 0
            if rr < min_rr:
                continue
            alerts.append((key + ":touch", (
                f"🎯 {SIDE[z.side]} {z.kind} 구간 도달{tag} → {ACTION[z.side]} 타점\n"
                f"진입 {_price(z.entry)} / 손절 {_price(z.stop)} / 익절 목표 {_price(wave)} (손익비 {rr:.1f})")))

    if "FAKEOUT" in kinds:
        for f in find_fakeouts(df, p):
            if f.confirm != last:
                continue
            name = "함정(Trap)" if f.trap else "거짓 돌파(Fake out)"
            line = "지지선" if f.side > 0 else "저항선"
            risk = abs(f.entry - f.stop)
            rr = abs(f.targets[0] - f.entry) / risk if risk else 0
            if rr < min_rr:
                continue
            tps = " / ".join(_price(x) for x in f.targets)
            alerts.append((f"FO:{f.side}:{t_last.isoformat()}:{f.level}", (
                f"⚠️ {line} {_price(f.level)} {name} 후 복귀 → {ACTION[f.side]} 신호\n"
                f"진입 {_price(f.entry)} / 손절 {_price(f.stop)} / 익절 {tps} (1차 손익비 {rr:.1f})")))
    return alerts


def send(text: str) -> None:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    print(text, end="\n\n", flush=True)
    if token and chat:
        import requests
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text}, timeout=10).raise_for_status()
        except Exception as e:  # 알림 실패로 봇이 죽지 않게
            print(f"[텔레그램 전송 실패] {e}", flush=True)


class Seen:
    """보낸 알림 키를 파일에 저장해서 재시작해도 같은 알림을 또 보내지 않는다."""

    def __init__(self, path: Path | None):
        self.path = path
        self.keys: set[str] = set(json.loads(path.read_text())) if path and path.exists() else set()

    def add(self, key: str) -> bool:
        if key in self.keys:
            return False
        self.keys.add(key)
        if self.path:
            self.path.write_text(json.dumps(sorted(self.keys)[-5000:]))
        return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default="upbit", help="upbit | binance")
    ap.add_argument("--symbol", help="예: KRW-BTC (업비트), BTCUSDT (바이낸스)")
    ap.add_argument("--interval", default="1h", help="1m 5m 15m 30m 1h 4h ...")
    ap.add_argument("--kinds", default="OB,FVG,FAKEOUT", help="쉼표로 구분")
    ap.add_argument("--only-sweep", action="store_true", help="유동성 흡수 동반 존만 알림 (백테스트상 손실이 덜했던 조건)")
    ap.add_argument("--min-rr", type=float, default=1.0, help="타점 알림의 최소 손익비 (익절폭 / 손절폭)")
    ap.add_argument("--max-wait", type=int, default=48, help="존 생성 후 이 캔들 수가 지나면 무시")
    ap.add_argument("--poll", type=int, default=30, help="새 캔들 확인 주기(초)")
    ap.add_argument("--state", default=".alert_state.json", help="보낸 알림 기록 파일")
    ap.add_argument("--replay", nargs="?", const=str(DEFAULT_CSV), help="CSV를 한 캔들씩 재생하며 시험")
    ap.add_argument("--last", type=int, default=300, help="재생 모드: 마지막 몇 캔들을 재생할지")
    a = ap.parse_args()

    p = Params()
    kinds = {k.strip().upper() for k in a.kinds.split(",")}
    window = 400  # 패턴과 스윙 판정에 충분한 길이

    if a.replay:
        df = load_csv(a.replay)
        seen = Seen(None)
        start = max(window, len(df) - a.last)
        print(f"[재생] {df['time'].iloc[start]} 부터 {len(df) - start}개 캔들\n")
        for k in range(start, len(df) + 1):
            part = df.iloc[max(0, k - window):k].reset_index(drop=True)
            for key, msg in scan(part, p, kinds, a.only_sweep, a.max_wait, a.min_rr):
                if seen.add(key):
                    print(f"[{part['time'].iloc[-1]:%Y-%m-%d %H:%M} UTC 마감]\n{msg}\n")
        return

    seen = Seen(Path(a.state))
    last_time = None
    send(f"🤖 알림 봇 시작: {a.source} {a.symbol or ''} {a.interval} / {', '.join(sorted(kinds))}"
         + (" / 유동성 흡수만" if a.only_sweep else ""))
    while True:
        try:
            df = drop_unclosed(load(a.source, a.symbol, a.interval, window), a.interval)
            if len(df) and df["time"].iloc[-1] != last_time:
                last_time = df["time"].iloc[-1]
                for key, msg in scan(df, p, kinds, a.only_sweep, a.max_wait, a.min_rr):
                    if seen.add(key):
                        send(f"[{a.symbol or a.source} {a.interval} · {last_time:%m-%d %H:%M} UTC 마감]\n{msg}")
        except Exception as e:
            print(f"[오류, 다음 주기에 재시도] {e}", flush=True)
        time.sleep(a.poll)


if __name__ == "__main__":
    main()
