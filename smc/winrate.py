"""승률을 올릴 수 있는가: (1) 진입 근거를 기계학습으로 종합하면 이기는 신호를 미리 골라낼 수 있는지
(2) 같은 신호에서 청산을 바꾸면 승률과 기대값이 어떻게 바뀌는지.

1. 진입 근거 종합 (signals.pkl, 7종 신호 × 롱·숏 × 1h·4h, 청산 1.5R 고정이라 승률 비교가 공정)
   그래디언트 부스팅으로 '이 신호가 익절로 끝날 확률'을 예측. 해마다 그 해 이전 데이터로만 학습 → 그 해 예측
   (2021–2026 모두 학습에 쓰지 않은 데이터, 펀딩비가 2019-10 부터 있어 2021 부터 예측). 예측 확률 10분위별 실제 승률·평균 R 을 본다.
   손익분기 승률은 1.5R 익절에서 수수료 포함 약 42%.
2. 청산 방식 (스윙 강한 롱 L, 일봉 지지선 이탈 숏 S5 · 4시간봉 · 같은 진입)
   추적      : 손절 ATR × 2, 최고가(숏은 최저가) − ATR × 3 추적 (현재 방식)
   본절      : 추적 + 1R 수익에 닿으면 손절을 진입가(수수료 포함)로
   분할 1R   : 1R 에 절반 지정가 익절, 손절 본절로, 나머지 추적
   분할 2R   : 2R 에 절반 지정가 익절, 손절 본절로, 나머지 추적
   고정 1.5R / 3R : 지정가 익절, 최대 120봉

사용:  python -m smc.winrate
"""
from __future__ import annotations

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from .research import MAKER, OUT as DATA, TAKER
from .research_report import NUMERIC, SPLIT
from .split_entry import HOLD, STOP_ATR, TRAIL_ATR
from .split_evidence import context
from .swing_ls import describe, equity_curve, strong

FEATS = NUMERIC + ["sweep", "hour", "weekday", "fam", "tf4", "side"]
FAMS = ["20봉돌파", "EMA교차", "FVG", "OB", "RSI반전", "거짓돌파", "채널반전"]
EXITS = ["추적", "본절", "분할 1R", "분할 2R", "고정 1.5R", "고정 3R"]


# ---------------------------------------------------------------- 1. 진입 근거 종합
def walk_forward() -> pd.DataFrame:
    d = pd.read_pickle(DATA).copy()
    d["fam"] = d.family.map({f: k for k, f in enumerate(FAMS)})
    d["tf4"] = (d.tf == "4h").astype(int)
    d["sweep"] = d.sweep.astype(int)
    d["win"] = (d.r > 0).astype(int)
    d["side"] = (d.side > 0).astype(int)                 # 범주형은 0 이상의 정수여야 함
    d["year"] = d.time.dt.year
    cat = [FEATS.index(c) for c in ("fam", "tf4", "side", "weekday")]
    out = []
    for y in range(2021, 2027):
        tr, te = d[d.year < y], d[d.year == y]
        m = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=200,
                                           l2_regularization=1.0, categorical_features=cat, random_state=0)
        m.fit(tr[FEATS], tr.win)
        out.append(te.assign(p=m.predict_proba(te[FEATS])[:, 1]))
    return pd.concat(out)


def report_ml(x: pd.DataFrame):
    x = x.assign(dec=pd.qcut(x.p.rank(method="first"), 10, labels=False) + 1)
    yrs = 5.75
    print("예측 확률 10분위 (2021-01 ~ 2026-09, 모두 학습에 안 쓴 데이터)")
    print(f"{'분위':>4} {'예측':>6} | {'실제 승률':>8} {'평균R':>7} | {'BTC 승률':>8} {'ETH 승률':>8} | {'2021':>8} {'2022–':>8} | 연 신호수")
    for k, g in x.groupby("dec"):
        a, b = g[g.time < SPLIT], g[g.time >= SPLIT]
        print(f"{k:4} {g.p.mean()*100:5.1f}% | {g.win.mean()*100:7.1f}% {g.r.mean():+.3f} |"
              f" {g[g.symbol=='BTC'].win.mean()*100:7.1f}% {g[g.symbol=='ETH'].win.mean()*100:7.1f}% |"
              f" {a.win.mean()*100:7.1f}% {b.win.mean()*100:7.1f}% | {len(g)/yrs:6.0f}")
    top = x[x.p >= x.p.quantile(0.9)]
    print("\n상위 10% 신호 구성 (어떤 신호·봉·방향이 많이 뽑혔나)")
    print(top.groupby(["tf", "family", "side"]).agg(n=("r", "size"), 승률=("win", "mean"), 평균R=("r", "mean"))
          .sort_values("n", ascending=False).head(8).round(3).to_string())
    for tf in ("4h", "1h"):
        g = x[x.tf == tf]
        t = g[g.p >= g.p.quantile(0.9)]
        print(f"{tf} 안에서 상위 10%: {len(t)}개, 승률 {t.win.mean()*100:.1f}% (전체 {g.win.mean()*100:.1f}%), 평균R {t.r.mean():+.3f}")


# ---------------------------------------------------------------- 2. 청산 방식
def simulate(ctx: dict, i: int, side: int, mode: str) -> dict:
    o, h, l, c, atr = ctx["o"], ctx["h"], ctx["l"], ctx["c"], ctx["atr"]
    n, p0 = len(c), c[i]
    one_r = STOP_ATR * atr[i]
    stop = p0 - side * one_r
    tp = {"분할 1R": 1.0, "분할 2R": 2.0, "고정 1.5R": 1.5, "고정 3R": 3.0}.get(mode)
    tp_px = p0 + side * tp * one_r if tp else None
    be = p0 + side * 2 * TAKER * p0
    fav = (lambda a, b: a >= b) if side > 0 else (lambda a, b: a <= b)
    legs, left, ext, ei, armed = [], 1.0, p0, None, False
    for t in range(i + 1, min(n, i + HOLD + 1)):
        if fav(stop, o[t]):                                  # 시가가 손절선 넘어 열림
            legs.append((left, o[t], TAKER)); left, ei = 0.0, t
            break
        if fav(stop, l[t] if side > 0 else h[t]):
            legs.append((left, stop, TAKER)); left, ei = 0.0, t
            break
        best = h[t] if side > 0 else l[t]
        if tp_px is not None and fav(best, tp_px):
            px = max(o[t], tp_px) if side > 0 else min(o[t], tp_px)
            if mode.startswith("고정"):
                legs.append((left, px, MAKER)); left, ei = 0.0, t
                break
            legs.append((0.5, px, MAKER)); left, tp_px = 0.5, None
            stop = max(stop, be) if side > 0 else min(stop, be)
        if mode == "본절" and not armed and fav(best, p0 + side * one_r):
            armed, stop = True, (max(stop, be) if side > 0 else min(stop, be))
        if not mode.startswith("고정"):
            ext = max(ext, h[t]) if side > 0 else min(ext, l[t])
            new = ext - side * TRAIL_ATR * atr[t]
            stop = max(stop, new) if side > 0 else min(stop, new)
    if left > 0:
        ei = min(n - 1, i + HOLD)
        legs.append((left, c[ei], TAKER))
    fund = (ctx["fcum"][ctx["didx"][ei]] - ctx["fcum"][ctx["didx"][i]]) * p0
    pnl = sum(q * (side * (px - p0) - TAKER * p0 - fee * px) for q, px, fee in legs) - side * fund
    return {"r": pnl / one_r, "exit_t": ei, "stop_pct": one_r / p0}


def exit_trades() -> pd.DataFrame:
    ctxs = {s: context(s) for s in ("BTC", "ETH")}
    sig = {"L": strong(1)[["symbol", "time"]].assign(side=1)}
    s5 = pd.read_pickle("reports/short_study.pkl")
    s5 = s5[(s5.setup.str[:2] == "S5") & (s5["mode"] == "추적")]
    sig["S5"] = pd.DataFrame({"symbol": s5.sym, "time": s5.entry - pd.Timedelta("4h"), "side": -1})
    rows = []
    for name, sg in sig.items():
        for mode in EXITS:
            for sym, ctx in ctxs.items():
                busy = -1
                for t0 in sg[sg.symbol == sym].time.sort_values():
                    i = ctx["idx"][t0]
                    if name == "S5" and i <= busy:              # S5 는 원래도 겹치지 않게 진입
                        continue
                    r = simulate(ctx, i, -1 if name == "S5" else 1, mode)
                    busy = r["exit_t"]
                    rows.append({"src": name, "mode": mode, "symbol": sym, "entry": ctx["df"].time.iat[i] + pd.Timedelta("4h"),
                                 "exit": ctx["df"].time.iat[r["exit_t"]] + pd.Timedelta("4h"), **r})
    return pd.DataFrame(rows)


def report_exits(x: pd.DataFrame):
    print(f"\n{'신호':3} {'청산':8} | {'거래':>4} {'승률':>6} {'평균R':>6} {'설계R':>6} {'검증R':>6} {'BTC R':>6} {'ETH R':>6} |"
          f" {'1% 복리 연평균':>10} {'낙폭':>7} {'효율':>5} | 최대 연패")
    for src in ("L", "S5"):
        for mode in EXITS:
            y = x[(x.src == src) & (x["mode"] == mode)].sort_values("entry")
            d = describe(equity_curve(y))
            streak = (y.r <= 0).astype(int).groupby((y.r > 0).cumsum()).sum().max()
            print(f"{src:3} {mode:8} | {len(y):4} {(y.r>0).mean()*100:5.1f}% {y.r.mean():+.3f} {y[y.entry<SPLIT].r.mean():+.3f}"
                  f" {y[y.entry>=SPLIT].r.mean():+.3f} {y[y.symbol=='BTC'].r.mean():+.3f} {y[y.symbol=='ETH'].r.mean():+.3f} |"
                  f" {d['full'][0]*100:+9.1f}% {d['full'][1]*100:6.1f}% {d['full'][0]/-d['full'][1]:5.2f} | {streak:3}")
        print()


def main():
    report_ml(walk_forward())
    report_exits(exit_trades())


if __name__ == "__main__":
    main()
