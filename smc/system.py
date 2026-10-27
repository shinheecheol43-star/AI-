"""코인 롱·숏 통합 매매 프로그램 (기본 BTC + ETH 한 계좌): 백테스트와 '지금 상태' 점검을 같은 규칙·같은 코드로.

전략 (코인마다 같은 규칙, 연구 단계에서 고정한 값 그대로)
  스윙 롱 : 4시간봉 종가가 직전 20봉 고가를 처음 돌파 + 근거 5개 중 4개 이상
            (4h 200EMA 위, 전날 일봉 국면 +3, 4h RSI > 63.0, 20EMA 이격 > ATR × 1.43, 전날 펀딩비 순위 하위 1/3)
  숏 S5   : 4시간봉 종가가 가장 최근 확정된 일봉 스윙 저점(좌우 5일)을 처음 이탈
  숏 S2   : 전날 일봉 국면 ≤ −1, 4h 종가 < 200EMA, 고가가 50EMA 에 닿고 50EMA 아래 음봉 마감
  데이 롱 : 4h 200EMA 위 + 전날 국면 ≥ +1 인 날, 미국장 첫 30분 고가를 15분봉 종가로 돌파하고 전일 고가 위일 때
            (미국장 마감에 손실이면 청산, 수익이면 본절 올려 보유. 하루 −1% 면 그날 중단)
  스윙 공통: 시장가 진입, 손절 ATR(4h) × 2, 추적 손절 최고가(숏은 최저가) ∓ ATR × 3, 최대 120봉,
            동시 보유(코인별): 스윙 롱은 2개까지(새 강한 돌파 신호일 때만), 숏 S5·S2 는 각 1개 (불타기 없음)
계좌
  거래당 리스크 RISK (스윙 롱·S5·데이 0.5%, S2 0.25%), 레버리지 합계 3배 이하, 슬리피지 진입·청산 각 SLIP,
  비상 브레이크: 실현 잔고가 최고점 대비 −15% 면 리스크 절반, −7% 까지 회복하면 해제 (매매 중지는 하지 않음)

사용:  python -m smc.system                 # BTC + ETH: 데이터 갱신 + 백테스트 + 지금 상태
       python -m smc.system --now           # 지금 상태만
       python -m smc.system --syms BTC      # 비트코인만
       python -m smc.system --scale 2 --lev 5   # 리스크 2배, 레버리지 상한 5배로 백테스트
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from . import daytrade3, short_study
from .data import ARCHIVE, extend_with_daily, fetch_binance_archive, resample
from .dd_brake import curve as account_curve, underwater
from .detectors import pivots
from .regime import fetch_funding, indicators as daily_indicators
from .research import TAKER, rsi
from .research_report import SPLIT
from .swing_ls import describe

SYMS = ("BTC", "ETH")
RISK = {"스윙 롱": 0.005, "숏 S5": 0.005, "숏 S2": 0.0025, "데이 롱": 0.005}   # S2 는 BTC 검증 구간 약해 절반
SLIP = 0.0005
MAX_LEV = 3.0                                     # 열린 포지션 명목 합계 / 잔고 상한
BRAKE = {"dd": 0.15, "mult": 0.5, "recover": 0.07}
STOP_ATR, TRAIL_ATR, HOLD = 2.0, 3.0, 120
MAX_OPEN = {"스윙 롱": 2, "숏 S5": 1, "숏 S2": 1}   # 동시 보유 한도 (롱은 새 강한 신호면 2개까지)
Q_RSI, Q_D20, Q_FUND = 63.0, 1.43, 1 / 3        # 설계 구간(2018–2021) 4h 롱 신호 분위수로 고정한 값


def refresh(sym: str) -> pd.Timestamp:
    for iv in ("1h", "5m"):
        fetch_binance_archive(sym + "USDT", iv)
        df = extend_with_daily(sym + "USDT", iv)
    return df.time.iloc[-1]


# ---------------------------------------------------------------- 스윙 신호
def context(sym: str) -> dict:
    X = short_study.context(sym)                    # S5·S2 판단에 쓰는 값 + 4h 가격·ATR·EMA·펀딩
    d4 = X["df"]
    dD = resample(fetch_binance_archive(sym + "USDT", "1h"), "1D")
    day = d4.time.dt.floor("D")
    fund = fetch_funding(sym + "USDT")
    frank = fund.rolling(90, min_periods=30).rank(pct=True).shift(1)
    frank = frank.reindex(pd.DatetimeIndex(day.unique()).union(frank.index)).ffill()   # 이번 달은 마지막 값 유지
    X["rsi"] = rsi(d4.close).to_numpy()
    X["d20"] = ((d4.close - X["e20"]) / X["atr"]).to_numpy()
    X["frank"] = frank.reindex(day).to_numpy()
    X["hh20"] = d4.high.rolling(20).max().shift(1).to_numpy()
    X["daily"] = daily_indicators(dD.set_index("time"))
    X["dD"], X["sym"] = dD, sym
    return X


def evidence(X: dict, i: int) -> list[bool]:
    return [i >= 200 and X["c"][i] > X["e200"][i], X["score"][i] >= 3, X["rsi"][i] > Q_RSI,
            X["d20"][i] > Q_D20, X["frank"][i] <= Q_FUND]


def long_signal(X: dict, i: int) -> bool:
    c, hh = X["c"], X["hh20"]
    return c[i] > hh[i] and c[i - 1] <= hh[i - 1] and sum(evidence(X, i)) >= 4


SWING = {"스윙 롱": (1, long_signal),
         "숏 S5": (-1, lambda X, i: short_study.signal(X, i, short_study.SETUPS[4])),
         "숏 S2": (-1, lambda X, i: short_study.signal(X, i, short_study.SETUPS[1]))}


def trail(X: dict, i: int, side: int) -> dict:
    """i 봉 종가 진입. 끝나지 않았으면 open=True 와 현재 손절선."""
    o, h, l, c, atr = X["o"], X["h"], X["l"], X["c"], X["atr"]
    n, p0 = len(c), c[i]
    stop = p0 - side * STOP_ATR * atr[i]
    one_r, ext = abs(p0 - stop), p0
    ex = ei = None
    for t in range(i + 1, min(n, i + HOLD + 1)):
        if (o[t] <= stop) if side > 0 else (o[t] >= stop):
            ex, ei = o[t], t
            break
        if (l[t] <= stop) if side > 0 else (h[t] >= stop):
            ex, ei = stop, t
            break
        ext = max(ext, h[t]) if side > 0 else min(ext, l[t])
        new = ext - side * TRAIL_ATR * atr[t]
        stop = max(stop, new) if side > 0 else min(stop, new)
    still = ex is None and i + HOLD >= n - 1
    if ex is None:
        ei = min(n - 1, i + HOLD)
        ex = c[ei]
    fund = (X["fcum"][X["didx"][ei]] - X["fcum"][X["didx"][i]]) * p0          # 양수 = 롱이 냄
    pnl = side * (ex - p0) - TAKER * (p0 + ex) - side * fund
    return {"r": pnl / one_r, "exit_t": ei, "stop_pct": one_r / p0, "open": still, "stop": stop, "p0": p0}


def swing_trades(X: dict, max_open: dict | None = None) -> pd.DataFrame:
    """max_open: 전략별 동시 보유 한도 (1 = 끝나야 다음 진입)."""
    max_open = max_open or MAX_OPEN
    rows, times, n = [], X["df"].time, len(X["c"])
    for name, (side, sig) in SWING.items():
        ends = []
        for i in range(201, n):
            ends = [e for e in ends if e >= i]
            if len(ends) >= max_open[name] or not np.isfinite(X["atr"][i]) or not sig(X, i):
                continue
            r = trail(X, i, side)
            ends.append(r["exit_t"] if not r["open"] else n)
            rows.append({"symbol": X["sym"], "src": name, "side": side, "entry": times.iat[i] + pd.Timedelta("4h"),
                         "exit": times.iat[r["exit_t"]] + pd.Timedelta("4h"), **r})
    return pd.DataFrame(rows)


def day_trades(syms) -> tuple[pd.DataFrame, dict]:
    res = daytrade3.run(above_ph=True, syms=tuple(syms))        # 코인들이 한 계좌·하루 손실 한도를 공유
    t = res["trades"]
    return (pd.DataFrame({"symbol": t.sym, "src": "데이 롱", "side": t.side, "entry": t.entry_time, "exit": t.exit_time, "r": t.r,
                          "stop_pct": t.stop_pct, "open": False}), res["open"])


# ---------------------------------------------------------------- 백테스트
def backtest(sw: pd.DataFrame, dy: pd.DataFrame, syms) -> None:
    x = pd.concat([sw, dy], ignore_index=True)
    x = x.assign(risk=x.src.map(RISK), r=x.r - 2 * SLIP / x.stop_pct)
    x = x[~x.open]                                   # 진행 중인 거래는 손익 미확정
    yrs = (pd.Timestamp("2026-10-01", tz="UTC") - pd.Timestamp("2018-03-15", tz="UTC")).days / 365.25
    print(f"■ 전략별 (슬리피지 {SLIP*100:.2f}% 포함)")
    print(f"{'':12} {'거래':>5} {'연':>4} {'승률':>6} {'평균R':>7} {'설계R':>7} {'검증R':>7} {'평균익':>6} {'평균손':>6}")
    for name, sym in ((n, s) for n in RISK for s in syms):
        y = x[(x.src == name) & (x.symbol == sym)]
        print(f"{name:8} {sym:3} {len(y):5} {len(y)/yrs:4.0f} {(y.r>0).mean()*100:5.1f}% {y.r.mean():+.3f} {y[y.entry<SPLIT].r.mean():+.3f}"
              f" {y[y.entry>=SPLIT].r.mean():+.3f} {y[y.r>0].r.mean():+6.2f} {y[y.r<=0].r.mean():+6.2f}")
    print(f"\n■ 한 계좌 ($1,000, 복리, 레버리지 ≤ {MAX_LEV:g}배)")
    print(f"{'구성':22} | {'연평균':>7} {'낙폭':>7} {'효율':>5} | {'설계':>7} {'검증':>7} {'검증낙폭':>7} | {'최장회복':>6} | $1,000→ | "
          + " ".join(f"{y:>5}" for y in range(2018, 2027)))
    allc = (list(RISK), list(syms))
    sets = {f"{s} 전체": (list(RISK), [s]) for s in syms}
    sets.update({"롱만 (스윙 + 데이)": (["스윙 롱", "데이 롱"], list(syms)), "숏만 (S5 + S2)": (["숏 S5", "숏 S2"], list(syms)),
                 "스윙만 (롱 + 숏)": (["스윙 롱", "숏 S5", "숏 S2"], list(syms)), "전체": allc, "전체 + 비상 브레이크": allc})
    for name, (srcs, ss) in sets.items():
        y = x[x.src.isin(srcs) & x.symbol.isin(ss)]
        cv, _ = account_curve(y, max_lev=MAX_LEV, **(BRAKE if "브레이크" in name else {}))
        d = describe(cv)
        f, a, b = d["full"], d["design"], d["test"]
        print(f"{name:22} | {f[0]*100:+6.1f}% {f[1]*100:6.1f}% {f[0]/-f[1]:5.2f} | {a[0]*100:+6.1f}% {b[0]*100:+6.1f}% {b[1]*100:6.1f}% |"
              f" {underwater(cv):5}일 | ${d['final']:>6,.0f} | " + " ".join(f"{d['years'][y]*100:+4.0f}%" for y in range(2018, 2027)))
    ev = sorted([(t, r) for t, r in zip(x.entry, x.risk)] + [(t, -r) for t, r in zip(x.exit, x.risk)], key=lambda e: (e[0], e[1]))
    peak = max(np.cumsum([r for _, r in ev]))
    print(f"  동시에 걸린 리스크 최대 {peak*100:.1f}% (모든 손절이 한꺼번에 맞을 때의 손실)")
    m = x.assign(y=x.entry.dt.year).groupby(["y", "src"]).size().unstack(fill_value=0)[list(RISK)]
    m["합계"] = m.sum(axis=1)
    print("\n■ 연도별 거래 수\n" + m.to_string())


# ---------------------------------------------------------------- 지금 상태
def now(X: dict, sw: pd.DataFrame, day_open: dict) -> None:
    sw = sw[sw.symbol == X["sym"]]
    day_open = {s: p for s, p in day_open.items() if s == X["sym"]}
    d4, i = X["df"], len(X["c"]) - 1
    last = d4.time.iat[i] + pd.Timedelta("4h")
    px = X["c"][i]
    kst = last.tz_convert("Asia/Seoul")
    print(f"\n■ {X['sym']} 지금 상태 (마지막 4시간봉 마감 {kst:%Y-%m-%d %H:%M} 한국시간, 종가 {px:,.0f})")
    daily = X["daily"]
    print(f"  일봉 국면 점수 {daily.score.iloc[-1]:+.0f} (전날 기준 {X['score'][i]:+.0f}) | 4h EMA20 {X['e20'][i]:,.0f} · EMA50 {X['e50'][i]:,.0f}"
          f" · EMA200 {X['e200'][i]:,.0f} | ATR {X['atr'][i]:,.0f} ({X['atr'][i]/px*100:.2f}%)")
    print("\n  [보유 중인 포지션]")
    held = sw[sw.open]
    for _, t in held.iterrows():
        one_r = t.p0 * t.stop_pct
        print(f"  {t.src:6} {'롱' if t.side > 0 else '숏'} 진입 {t.entry.tz_convert('Asia/Seoul'):%m-%d %H시} @ {t.p0:,.0f}"
              f" | 현재 손절 {t.stop:,.0f} | 평가 {t.side * (px - t.p0) / one_r:+.2f}R")
    for s, p in day_open.items():
        print(f"  데이 롱 진입 {p['time'].tz_convert('Asia/Seoul'):%m-%d %H:%M} @ {p['entry']:,.0f} | 현재 손절 {p['stop']:,.0f}")
    if held.empty and not day_open:
        print("  없음")
    print("\n  [다음 신호 조건]")
    ev = evidence(X, i)
    names = ["4h 200EMA 위", "일봉 국면 +3", f"RSI > {Q_RSI:.0f} (지금 {X['rsi'][i]:.0f})",
             f"20EMA 이격 > {Q_D20} ATR (지금 {X['d20'][i]:.2f})", "펀딩비 순위 하위 1/3"]
    hh = d4.high.iloc[-20:].max()
    busy = set(held.src)
    print(f"  스윙 롱 : 4h 종가 > {hh:,.0f} ({(hh/px-1)*100:+.1f}%) 돌파 + 근거 4개 이상. 지금 근거 {sum(ev)}/5"
          f" [{', '.join(n for n, e in zip(names, ev) if e) or '없음'}]" + (" ※ 보유 중" if "스윙 롱" in busy else ""))
    dD = X["dD"]
    _, lows = pivots(dD, 5)
    sup = next((lvl for _, pc, lvl in reversed(lows) if pc + 1 < len(dD)), np.nan)
    state = "이미 아래" if px < sup else f"{(sup/px-1)*100:+.1f}%"
    print(f"  숏 S5  : 4h 종가가 일봉 지지선 {sup:,.0f} ({state}) 를 처음 이탈" + (" ※ 보유 중" if "숏 S5" in busy else ""))
    s2ok = X["score"][i] <= -1
    print(f"  숏 S2  : 일봉 국면 ≤ −1 {'충족' if s2ok else '불충족 (상승 국면이라 대기)'}, 4h 200EMA {X['e200'][i]:,.0f} 아래에서"
          f" 50EMA {X['e50'][i]:,.0f} 터치 후 음봉 마감" + (" ※ 보유 중" if "숏 S2" in busy else ""))
    trade_day = X["c"][i] > X["e200"][i] and X["score"][i] >= 1
    ph = dD.high.iloc[-1] if dD.time.iloc[-1] < last.floor("D") else dD.high.iloc[-2]
    print(f"  데이 롱 : {'매매하는 날 조건 충족' if trade_day else '4h 200EMA 아래라 매매 안 하는 날' if X['c'][i] <= X['e200'][i] else '일봉 국면 미달'}"
          f" | 진입은 미국장 첫 30분 고가 돌파 + 전일 고가 {ph:,.0f} 위")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--now", action="store_true", help="백테스트 없이 지금 상태만")
    ap.add_argument("--no-refresh", action="store_true")
    ap.add_argument("--scale", type=float, default=1.0, help="모든 리스크에 곱할 배수 (예: 2 = 롱 1%%)")
    ap.add_argument("--lev", type=float, default=MAX_LEV, help="레버리지 합계 상한")
    ap.add_argument("--syms", default=",".join(SYMS), help="예: BTC,ETH")
    a = ap.parse_args()
    syms = a.syms.split(",")
    globals()["MAX_LEV"] = a.lev
    for k in RISK:
        RISK[k] *= a.scale
    if not a.no_refresh:
        for s in syms:
            print(f"데이터 갱신 {s}: 마지막 캔들 {refresh(s):%Y-%m-%d %H:%M} UTC ({ARCHIVE})")
    Xs = {s: context(s) for s in syms}
    sw = pd.concat([swing_trades(X) for X in Xs.values()], ignore_index=True)
    dy, day_open = day_trades(syms)
    if not a.now:
        backtest(sw, dy, syms)
    for X in Xs.values():
        now(X, sw, day_open)


if __name__ == "__main__":
    main()
