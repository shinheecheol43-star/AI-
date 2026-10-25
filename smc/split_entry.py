"""분할 진입 비교: 4시간봉 20봉 돌파 · 강한 신호(근거 4개 이상) · 롱만 · 추적 손절.

모든 방식에서 총 계획 수량과 손절선은 같고, 나눠 넣는 방식만 다르다.
  계획 수량 : 잔고 × 1% ÷ (신호 종가 − 최초 손절)   (한 번에 다 넣었을 때 손절 = 잔고 1% 손실)
  최초 손절 : 신호 종가 − 신호 캔들 ATR × 2
  추적 손절 : 첫 진입 후 최고가 − 현재 ATR × 3 (위로만 이동), 최대 보유 120봉
  눌림 주문 : 신호 종가 − ATR × k 지정가. 12봉 안에 안 닿으면 취소
  레버리지  : 열린 포지션 계획 금액 합계가 잔고의 3배를 넘지 않게 줄여서 진입
  비용      : 첫 진입·청산 시장가 0.055%, 눌림 지정가 0.02%, 보유 기간 실제 펀딩비

사용:  python -m smc.split_entry
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import fetch_binance_archive, resample
from .regime import DEFAULT_FUNDING, fetch_funding
from .research import MAKER, OUT as DATA, TAKER, tf_features
from .research_report import SPLIT

PLANS = {
    "A. 한 번에": [(1.0, 0.0)],
    "B. 2분할 (1 ATR 눌림)": [(0.5, 0.0), (0.5, 1.0)],
    "C. 3분할 (0.75·1.5 ATR)": [(1 / 3, 0.0), (1 / 3, 0.75), (1 / 3, 1.5)],
    "D. 2분할 (0.5 ATR 눌림)": [(0.5, 0.0), (0.5, 0.5)],
}
WAIT, HOLD, STOP_ATR, TRAIL_ATR = 12, 120, 2.0, 3.0


def strong_signals() -> pd.DataFrame:
    d = pd.read_pickle(DATA)
    d = d[(d.tf == "4h") & (d.side > 0)]
    tr = d[d.time < SPLIT]
    q_rsi, q_d20, q_f = tr.rsi.quantile(2 / 3), tr.dist_ema20.quantile(2 / 3), tr.funding_rank.quantile(1 / 3)
    d = d.assign(strength=(d.trend4h > 0).astype(int) + (d.day_score >= 3) + (d.rsi > q_rsi)
                 + (d.dist_ema20 > q_d20) + (d.funding_rank <= q_f))
    return d[(d.family == "20봉돌파") & (d.strength >= 4)]


def simulate_trade(o, h, l, c, atr, didx, fcum, i, plan):
    """한 신호의 결과. 계획 수량 1 기준 손익을 '한 번에 진입했을 때의 손절 손실(=1R)' 단위로 돌려준다."""
    n = len(c)
    p0, a = c[i], atr[i]
    stop = p0 - STOP_ATR * a
    one_r = p0 - stop
    legs = [{"w": w, "px": p0 - k * a, "filled": k == 0, "t": i, "fee": TAKER if k == 0 else MAKER} for w, k in plan]
    ext, ex, ei = p0, None, None
    for t in range(i + 1, min(n, i + HOLD + 1)):
        for g in legs:            # 눌림 주문 체결 (손절선 위에서만)
            if not g["filled"] and t - i <= WAIT and l[t] <= g["px"] and g["px"] > stop:
                g["filled"], g["t"] = True, t
                g["px"] = min(o[t], g["px"])
        if o[t] <= stop:
            ex, ei = o[t], t
            break
        if l[t] <= stop:
            ex, ei = stop, t
            break
        ext = max(ext, h[t])
        stop = max(stop, ext - TRAIL_ATR * atr[t])
    if ex is None:
        ei = min(n - 1, i + HOLD)
        ex = c[ei]
    pnl = 0.0
    filled = [g for g in legs if g["filled"]]
    for g in filled:
        fund = fcum[didx[ei]] - fcum[didx[g["t"]]]
        pnl += g["w"] * ((ex - g["px"]) - g["fee"] * g["px"] - TAKER * ex - fund * g["px"])
    worst = sum(g["w"] * (g["px"] - (p0 - STOP_ATR * a)) for g in filled)   # 처음 손절에 걸렸을 때의 손실
    return {"r": pnl / one_r, "filled_w": sum(g["w"] for g in filled), "risk_used": worst / one_r,
            "exit_t": ei, "stop_pct": one_r / p0}


def run_trades(plan) -> pd.DataFrame:
    sig = strong_signals()
    rows = []
    for sym in ("BTC", "ETH"):
        df = resample(fetch_binance_archive(sym + "USDT", "1h"), "4h")
        f = tf_features(df)
        o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
        atr = f["atr"].to_numpy()
        days = df["time"].dt.floor("D")
        fund = fetch_funding(sym + "USDT").reindex(pd.DatetimeIndex(days.unique())).fillna(DEFAULT_FUNDING)
        fcum = np.r_[0.0, fund.cumsum().to_numpy()]
        didx = pd.Index(fund.index).get_indexer(days) + 1
        idx = {t: k for k, t in enumerate(df["time"])}
        for _, s in sig[sig.symbol == sym].iterrows():
            i = idx[s.time]
            res = simulate_trade(o, h, l, c, atr, didx, fcum, i, plan)
            rows.append({"symbol": sym, "entry": df["time"].iat[i] + pd.Timedelta("4h"),
                         "exit": df["time"].iat[res["exit_t"]] + pd.Timedelta("4h"), **res})
    return pd.DataFrame(rows).sort_values("entry").reset_index(drop=True)


def portfolio(x: pd.DataFrame, start=1000.0, risk=0.01, max_lev=3.0) -> dict:
    """복리 + 레버리지 상한. 진입 시점 확정 잔고 기준, 열린 포지션 계획 금액 합계 ≤ 잔고 × max_lev."""
    bal, open_pos, curve, used = start, [], [], []
    for _, t in x.iterrows():
        for p in [p for p in open_pos if p["exit"] <= t.entry]:
            bal += p["pnl"]
            open_pos.remove(p)
            curve.append((p["exit"], bal))
        planned = bal * risk / t.stop_pct
        room = max_lev * bal - sum(p["notional"] for p in open_pos)
        notional = min(planned, room)
        if notional <= 0 or bal <= 0:
            continue
        scale = notional / planned
        open_pos.append({"exit": t.exit, "pnl": bal * risk * scale * t.r, "notional": notional})
        used.append(sum(p["notional"] for p in open_pos) / bal)
    for p in sorted(open_pos, key=lambda p: p["exit"]):
        bal += p["pnl"]
        curve.append((p["exit"], bal))
    eq = np.array([b for _, b in sorted(curve)]) if curve else np.array([start])
    peak = np.maximum.accumulate(np.r_[start, eq])[1:]
    return {"final": float(eq[-1]), "mdd": float((eq / peak - 1).min()), "trades": len(used),
            "max_lev": float(max(used)) if used else 0.0}


def main():
    print("4시간봉 20봉 돌파 · 강한 신호(근거 ≥ 4) · 롱만 · 레버리지 최대 3배 · 거래당 1% 리스크 복리\n")
    print(f"{'방식':24} {'구간':10} {'거래':>5} {'승률':>6} {'평균R':>7} {'2차이후 체결':>10} {'손절시 손실':>9} {'$1,000→':>9} {'연평균':>7} {'최대낙폭':>7} {'최대 레버리지':>9}")
    for name, plan in PLANS.items():
        x = run_trades(plan)
        for per, m in (("검증 22–26", x.entry >= SPLIT), ("전체 18–26", x.entry == x.entry)):
            y = x[m]
            p = portfolio(y)
            yrs = (y.exit.max() - y.entry.min()).days / 365.25
            later = (y.filled_w > plan[0][0] + 1e-9).mean() if len(plan) > 1 else float("nan")
            sl = y.risk_used[y.r < 0].mean()
            print(f"{name:24} {per:10} {len(y):5} {(y.r > 0).mean()*100:5.1f}% {y.r.mean():+7.3f} "
                  f"{('-' if np.isnan(later) else f'{later*100:.0f}%'):>10} {sl*100:8.0f}%  ${p['final']:>8,.0f}"
                  f" {((p['final']/1000)**(1/yrs)-1)*100:+6.1f}% {p['mdd']*100:6.1f}% {p['max_lev']:8.1f}배")


if __name__ == "__main__":
    main()
