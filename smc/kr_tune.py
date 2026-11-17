"""국내 시장 시스템을 국내장에 맞게 다시 맞추기: 롱 규칙 값 · 동시 보유 제한 · 시장 상태별 대응 (일봉).

규칙과 후보 값은 결과를 보기 전에 정했다. 고르는 건 설계 구간(2012~2019)만, 채점은 2020~2026.
공통: 후보 풀 = smc.kr_portfolio.POOL, 롱은 주도 섹터(6개월 강도 상위 3) + 상대 강도(종목 6개월 수익률 > KODEX 200) 종목만,
      근거 4개 중 3개 이상(200일선 위·국면 +3·RSI>60·20일선 이격>ATR), 비용 편도 주식 0.15% · ETF 0.05%,
      계좌 1,000만원, 롱 거래당 1%, 레버리지 없음 (열린 포지션 합계 ≤ 계좌)
1단계 롱 값 (72조합): 돌파 기간 N 20·40·60일, 손절 ATR×1.5·2·3, 추적 ATR×2·3·4·5, 최대 보유 60·120일
   점수 = 설계 구간 연수익 ÷ |최대 낙폭|. 가장 좋은 한 점이 아니라 '이웃 값 평균 점수'가 가장 높은 조합을 고른다.
2단계 동시 보유: 최대 종목 5·8·12·제한 없음 × 섹터당 1·2·제한 없음 (설계 구간 점수로 고름)
3단계 시장 상태 (KODEX 200, 전날 종가)
   하락장 = 250일 고점 대비 −10% 이상 (−5% 이내 회복 시 해제) · 박스권 = 하락장 아니고 ADX(14) < 20 · 나머지 상승장
   롱 처리: 항상 / 하락장 제외 / 상승장만
   인버스: 없음 / 신호 (하락장에서 KODEX 200 숏 신호 → 인버스, 0.5%) / 보유 (하락장이고 지수 < 50일선이면 계좌 30% 보유, 지수가 50일선 위로 마감하거나 하락장 해제 시 정리)
   박스권: 없음 / 평균회귀 (박스권에서 KODEX 200 종가 < 볼린저 하단(20,2) → 매수, 중간선 위 마감·10일·손절 ATR×2 중 먼저, 1%)

사용:  python -m smc.kr_tune
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from itertools import product

import numpy as np
import pandas as pd

from . import stock_swing as ss
from .kr_portfolio import INVERSE, POOL, gate, load
from .research import tf_features

CAP = 10_000_000
DESIGN = ("2012-01-01", "2020-01-01")
TEST = ("2020-01-01", "2026-11-18")
LOOK = 120
NS, STOPS, TRAILS, HOLDS = (20, 40, 60), (1.5, 2.0, 3.0), (2.0, 3.0, 4.0, 5.0), (60, 120)


# ---------------------------------------------------------------- 데이터
@lru_cache(maxsize=None)
def universe():
    out = {}
    for sec, mem in POOL.items():
        for code, name in mem.items():
            try:
                d = load(code)
            except Exception:
                continue
            if len(d) >= 300:
                out[name] = (sec, d)
    return out


@lru_cache(maxsize=None)
def index_data():
    kd = load("069500")
    inv = load(INVERSE)
    return kd, inv


@lru_cache(maxsize=None)
def filters():
    """(종목, 날짜) → 주도 섹터·상대 강도 통과 여부를 위한 표."""
    kd, _ = index_data()
    k = kd.set_index("time").close
    kmom = (k / k.shift(LOOK) - 1).shift(1)
    U = universe()
    M = pd.DataFrame({n: (d.set_index("time").close / d.set_index("time").close.shift(LOOK) - 1).shift(1) for n, (s, d) in U.items()})
    sector_of = {n: s for n, (s, d) in U.items()}
    secmom = pd.DataFrame({s: M[[n for n in M if sector_of[n] == s]].mean(axis=1) for s in POOL})
    rank = secmom.rank(axis=1, ascending=False)
    return M, kmom, rank, sector_of


# ---------------------------------------------------------------- 롱 거래
def long_trades_param(name, sec, d, N, stop_k, trail_k, hold, cost=0.0015):
    X = ss.context(d)
    hh = d.high.rolling(N).max().shift(1).to_numpy()
    o, h, l, c, atr = X["o"], X["h"], X["l"], X["c"], X["atr"]
    n, rows, busy = len(c), [], -1
    for i in range(max(201, N + 1), n):
        if i <= busy or not np.isfinite(atr[i]):
            continue
        if not (c[i] > hh[i] and c[i - 1] <= hh[i - 1] and sum(ss.evidence(X, i)) >= 3):
            continue
        p0 = c[i]
        stop = p0 - stop_k * atr[i]
        one_r, ext, ex, ei = p0 - stop, p0, None, None
        for t in range(i + 1, min(n, i + hold + 1)):
            if o[t] <= stop:
                ex, ei = o[t], t; break
            if l[t] <= stop:
                ex, ei = stop, t; break
            ext = max(ext, h[t])
            stop = max(stop, ext - trail_k * atr[t])
        if ex is None:
            ei = min(n - 1, i + hold); ex = c[ei]
        r = ((ex - p0) - cost * (p0 + ex)) / one_r
        rows.append((name, sec, d.time.iat[i], d.time.iat[ei], r, one_r / p0))
        busy = ei
    return rows


def build_longs(params):
    N, stop_k, trail_k, hold = params
    M, kmom, rank, sector_of = filters()
    rows = []
    for name, (sec, d) in universe().items():
        rows += long_trades_param(name, sec, d, N, stop_k, trail_k, hold)
    x = pd.DataFrame(rows, columns=["sym", "sector", "entry", "exit", "r", "stop_pct"])
    sm = np.array([M[n].get(t, np.nan) for n, t in zip(x.sym, x.entry)])
    km = kmom.reindex(x.entry).to_numpy()
    lead = np.array([rank[sector_of[n]].get(t, 99) <= 3 for n, t in zip(x.sym, x.entry)])
    x = x[lead & (sm > km)].reset_index(drop=True)
    return params, x


# ---------------------------------------------------------------- 시장 상태 · 인버스 · 박스권
@lru_cache(maxsize=None)
def regime():
    kd, _ = index_data()
    k = kd.set_index("time")
    bear = gate(k.close)
    adx = tf_features(kd).set_index(kd.time)["adx"].shift(1)
    box = (~bear) & (adx < 20)
    state = pd.Series("상승", index=k.index)
    state[box] = "박스"
    state[bear] = "하락"
    return state


@lru_cache(maxsize=None)
def inverse_trades(mode):
    kd, inv = index_data()
    invc = inv.set_index("time").close
    k = kd.set_index("time").close
    bear = gate(k)
    if mode == "신호":
        ss.COST = 0.0005
        kx = ss.trades(ss.context(kd))
        ks = kx[(kx.side < 0) & bear.reindex(kx.entry).fillna(False).to_numpy().astype(bool)]
        rows = [("KODEX 인버스", "인버스", t.entry, t.exit, (invc[t.exit] / invc[t.entry] - 1 - 0.001) / t.stop_pct, t.stop_pct, 0.005)
                for t in ks.itertuples() if t.entry in invc.index and t.exit in invc.index]
    else:                                                   # 보유
        e50 = k.ewm(span=50, adjust=False).mean()
        cond = (bear & (k.shift(1) < e50.shift(1)))
        rows, inpos, t0 = [], False, None
        for t in k.index:
            if t not in invc.index:
                continue
            if not inpos and cond.get(t, False):
                inpos, t0 = True, t
            elif inpos and (not bear.get(t, False) or k[t] > e50[t]):
                ret = invc[t] / invc[t0] - 1 - 0.001
                rows.append(("KODEX 인버스", "인버스", t0, t, ret / 0.10, 0.10, 0.03))     # 계좌 30% 보유
                inpos = False
    return pd.DataFrame(rows, columns=["sym", "sector", "entry", "exit", "r", "stop_pct", "risk"])


@lru_cache(maxsize=None)
def box_trades():
    kd, _ = index_data()
    st = regime()
    c, o, l, a = kd.close.to_numpy(), kd.open.to_numpy(), kd.low.to_numpy(), tf_features(kd).atr.to_numpy()
    mid = kd.close.rolling(20).mean().to_numpy()
    low = mid - 2 * kd.close.rolling(20).std().to_numpy()
    rows, busy = [], -1
    for i in range(250, len(kd)):
        t = kd.time.iat[i]
        if i <= busy or st.get(t, "") != "박스" or not c[i] < low[i]:
            continue
        p0, stop = c[i], c[i] - 2 * a[i]
        ex, ei = None, None
        for j in range(i + 1, min(len(kd), i + 11)):
            if l[j] <= stop:
                ex, ei = min(stop, o[j]), j; break
            if c[j] > mid[j]:
                ex, ei = c[j], j; break
        if ex is None:
            ei = min(len(kd) - 1, i + 10); ex = c[ei]
        rows.append(("KODEX 200", "박스", t, kd.time.iat[ei], ((ex - p0) - 0.0005 * (p0 + ex)) / (p0 - stop), (p0 - stop) / p0, 0.01))
        busy = ei
    return pd.DataFrame(rows, columns=["sym", "sector", "entry", "exit", "r", "stop_pct", "risk"])


# ---------------------------------------------------------------- 계좌
def account(trades: pd.DataFrame, lo, hi, max_pos=None, max_sec=None):
    x = trades[(trades.entry >= lo) & (trades.entry < hi)].sort_values("entry")
    bal, op, ev, n_taken = CAP, [], [(pd.Timestamp(lo, tz="UTC"), CAP)], 0
    for t in x.itertuples():
        for p in sorted([p for p in op if p["exit"] <= t.entry], key=lambda p: p["exit"]):
            bal += p["pnl"]; op.remove(p); ev.append((p["exit"], bal))
        longs = [p for p in op if p["sector"] not in ("인버스", "박스")]
        if t.sector not in ("인버스", "박스"):
            if max_pos and len(longs) >= max_pos:
                continue
            if max_sec and sum(p["sector"] == t.sector for p in longs) >= max_sec:
                continue
        risk = getattr(t, "risk", 0.01)
        risk = 0.01 if not np.isfinite(risk) else risk
        size = min(bal * risk / t.stop_pct, bal - sum(p["notional"] for p in op))
        if size <= 0:
            continue
        op.append({"exit": t.exit, "pnl": size * t.stop_pct * t.r, "notional": size, "sector": t.sector})
        n_taken += 1
    for p in sorted(op, key=lambda p: p["exit"]):
        bal += p["pnl"]; ev.append((p["exit"], bal))
    eq = pd.Series([b for _, b in ev], index=pd.DatetimeIndex([e for e, _ in ev])).sort_index()
    eq = eq.groupby(level=0).last()
    yrs = (pd.Timestamp(hi) - pd.Timestamp(lo)).days / 365.25
    cagr = (eq.iloc[-1] / CAP) ** (1 / yrs) - 1
    mdd = (eq / eq.cummax() - 1).min()
    return dict(cagr=cagr, mdd=mdd, score=cagr / abs(mdd) if mdd < 0 else cagr, n=n_taken, final=eq.iloc[-1], eq=eq)


def yearly(trades, max_pos=None, max_sec=None):
    out = {}
    for y in range(2020, 2027):
        a = account(trades, f"{y}-01-01", f"{y + 1}-01-01", max_pos, max_sec)
        out[y] = a["final"] / CAP - 1
    return out


def main():
    universe(); filters(); regime()
    grid = list(product(NS, STOPS, TRAILS, HOLDS))
    with ProcessPoolExecutor(4) as pool:
        res = dict(pool.map(build_longs, grid))
    rows = []
    for p, x in res.items():
        a, b = account(x, *DESIGN), account(x, *TEST)
        rows.append(dict(N=p[0], stop=p[1], trail=p[2], hold=p[3], d_cagr=a["cagr"], d_mdd=a["mdd"], d_score=a["score"],
                         t_cagr=b["cagr"], t_mdd=b["mdd"], t_score=b["score"], n=len(x)))
    G = pd.DataFrame(rows)
    # 이웃 평균 점수 (각 값에서 한 칸씩 움직인 조합들 포함)
    def neigh(r):
        m = pd.Series(True, index=G.index)
        for col, vals in (("N", NS), ("stop", STOPS), ("trail", TRAILS), ("hold", HOLDS)):
            i = vals.index(r[col])
            near = vals[max(0, i - 1):i + 2]
            m &= G[col].isin(near)
        return G[m].d_score.mean()
    G["d_neigh"] = G.apply(neigh, axis=1)
    print("국내 시스템 다시 맞추기 · 고르기 = 2012~2019 · 채점 = 2020~2026 · 1,000만원, 롱 1%, 레버리지 없음\n")
    print("■ 1단계 롱 값 (설계 이웃 평균 점수 상위 8)  점수 = 연수익 ÷ |최대 낙폭|")
    print(f"  {'돌파':>4} {'손절':>4} {'추적':>4} {'보유':>4} | {'설계 연':>7} {'낙폭':>6} {'이웃점수':>7} | {'검증 연':>7} {'낙폭':>6}")
    for r in G.sort_values("d_neigh", ascending=False).head(8).itertuples():
        print(f"  {r.N:4} {r.stop:4} {r.trail:4} {r.hold:4} | {r.d_cagr*100:+6.1f}% {r.d_mdd*100:5.1f}% {r.d_neigh:7.2f} | {r.t_cagr*100:+6.1f}% {r.t_mdd*100:5.1f}%")
    cur = G[(G.N == 20) & (G.stop == 2.0) & (G.trail == 3.0) & (G.hold == 60)].iloc[0]
    print(f"  지금 값 (20일·2·3·60) | 설계 {cur.d_cagr*100:+.1f}% 낙폭 {cur.d_mdd*100:.1f}% | 검증 {cur.t_cagr*100:+.1f}% 낙폭 {cur.t_mdd*100:.1f}%")
    for col, vals in (("N", NS), ("stop", STOPS), ("trail", TRAILS), ("hold", HOLDS)):
        print(f"  {col:5} 값별 설계 점수 평균: " + " · ".join(f"{v}: {G[G[col] == v].d_score.mean():.2f}" for v in vals)
              + "  | 검증: " + " · ".join(f"{v}: {G[G[col] == v].t_score.mean():.2f}" for v in vals))
    best = G.loc[G.d_neigh.idxmax()]
    P = (int(best.N), float(best.stop), float(best.trail), int(best.hold))
    L = res[P]
    print(f"\n  → 고른 값: 돌파 {P[0]}일 · 손절 ATR×{P[1]} · 추적 ATR×{P[2]} · 최대 {P[3]}일")

    print("\n■ 2단계 동시 보유 제한 (설계 점수로 고름)")
    print(f"  {'최대 종목':>8} {'섹터당':>6} | {'설계 연':>7} {'낙폭':>6} {'점수':>5} | {'검증 연':>7} {'낙폭':>6}")
    lim = []
    for mp, ms in product((5, 8, 12, None), (1, 2, None)):
        a, b = account(L, *DESIGN, mp, ms), account(L, *TEST, mp, ms)
        lim.append((a["score"], mp, ms))
        print(f"  {str(mp or '제한없음'):>8} {str(ms or '제한없음'):>6} | {a['cagr']*100:+6.1f}% {a['mdd']*100:5.1f}% {a['score']:5.2f} | {b['cagr']*100:+6.1f}% {b['mdd']*100:5.1f}%")
    _, MP, MS = max(lim, key=lambda v: v[0])
    print(f"  → 고른 제한: 최대 {MP or '제한없음'}종목 · 섹터당 {MS or '제한없음'}")

    print("\n■ 3단계 시장 상태별 대응 (2단계까지 고른 값 위에)")
    st = regime()
    Lr = L.assign(state=st.reindex(L.entry).fillna("상승").to_numpy())
    long_modes = {"항상": Lr, "하락장 제외": Lr[Lr.state != "하락"], "상승장만": Lr[Lr.state == "상승"]}
    inv_modes = {"없음": inverse_trades("신호").iloc[0:0], "신호": inverse_trades("신호"), "보유": inverse_trades("보유")}
    box_modes = {"없음": box_trades().iloc[0:0], "평균회귀": box_trades()}
    bx = box_trades()
    print(f"  (참고) 박스권 평균회귀 단독: {len(bx)}건 · 승률 {(bx.r > 0).mean()*100:.0f}% · 평균 {bx.r.mean():+.2f}R"
          f" (설계 {bx[bx.entry < DESIGN[1]].r.mean():+.2f}R · 검증 {bx[bx.entry >= TEST[0]].r.mean():+.2f}R)")
    iv = inverse_trades("보유")
    print(f"  (참고) 하락장 인버스 보유 단독: {len(iv)}번 · 평균 보유 수익 {(iv.r * iv.stop_pct).mean()*100:+.1f}% · 이긴 비율 {(iv.r > 0).mean()*100:.0f}%")
    print(f"  {'롱':10} {'인버스':4} {'박스권':6} | {'설계 연':>7} {'낙폭':>6} {'점수':>5} | {'검증 연':>7} {'낙폭':>6} | 2020~2026 연도별")
    combos = []
    for (lm, lt), (im, it), (bm, bt) in product(long_modes.items(), inv_modes.items(), box_modes.items()):
        allt = pd.concat([lt.assign(risk=0.01), it, bt], ignore_index=True)
        a, b = account(allt, *DESIGN, MP, MS), account(allt, *TEST, MP, MS)
        ys = yearly(allt, MP, MS)
        combos.append((a["score"], lm, im, bm, a, b, ys))
        print(f"  {lm:10} {im:4} {bm:6} | {a['cagr']*100:+6.1f}% {a['mdd']*100:5.1f}% {a['score']:5.2f} | {b['cagr']*100:+6.1f}% {b['mdd']*100:5.1f}% | "
              + " ".join(f"{y % 100}:{v*100:+.0f}%" for y, v in ys.items()))
    s, lm, im, bm, a, b, ys = max(combos, key=lambda v: v[0])
    print(f"\n  → 설계 점수로 고른 최종: 롱 {lm} · 인버스 {im} · 박스권 {bm}")
    print(f"    2012~2019: 연 {a['cagr']*100:+.1f}% 낙폭 {a['mdd']*100:.1f}% · 1,000만원 → {a['final']:,.0f}원")
    print(f"    2020~2026: 연 {b['cagr']*100:+.1f}% 낙폭 {b['mdd']*100:.1f}% · 1,000만원 → {b['final']:,.0f}원 · 거래 {b['n']}건")


if __name__ == "__main__":
    main()
