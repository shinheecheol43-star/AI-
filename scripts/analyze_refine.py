"""전략 다듬기: 개발(train)/검증(test) 분할 · 지수 영향 · 진입 타이밍 비교 -> data/refine_summary.json

- 개발 구간: 2023-11-13 ~ 2025-10-31 / 검증 구간: 2025-11-01 ~ (조건 조정 없이 한 번만 평가)
- 손절 -10%(진입가 기준), 최대 보유 10거래일, 왕복 비용 0.25% 차감
- 청산: (X1) 상한가 마감일 종가 / (X2) 상한가 다음 날 시가
"""
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(__file__))
from analyze_entry import load  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
START, SPLIT = "2023-11-13", "2025-11-01"
K = 16           # 앞으로 볼 거래일 수
HOLD = 10
STOP = 0.10
COST = 0.0025


def build(p):
    g = p.groupby("symbol", group_keys=False)
    p["prev"] = g.close.shift(1)
    p["ret"] = p.close / p.prev - 1
    ok = p.ret.between(-0.32, 0.32)
    p["LU"] = (p.ret >= 0.295) & ok
    p["vma20"] = g.volume.transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    p["vr"] = p.volume / p.vma20.replace(0, np.nan)
    p["hi252"] = g.high.transform(lambda s: s.shift(1).rolling(252, min_periods=120).max())
    p["dd"] = p.prev / p.hi252 - 1
    p["close_pos"] = (p.close - p.low) / (p.high - p.low).replace(0, np.nan)
    p["mcap"] = p.prev * p.shares
    p["lu_prev20"] = g.LU.transform(lambda s: s.shift(1).rolling(20, min_periods=1).sum()).fillna(0)
    p["first_LU"] = p.LU & (p.lu_prev20 == 0)
    cols = {}
    for k in range(1, K):
        for c in ("open", "high", "low", "close"):
            cols[f"{c[0]}{k}"] = g[c].shift(-k)
        cols[f"lu{k}"] = g.LU.shift(-k).astype("boolean").fillna(False).astype(bool)
    return pd.concat([p, pd.DataFrame(cols)], axis=1)


def add_index(p):
    ix = pd.read_csv(os.path.join(ROOT, "index.csv"))
    out = []
    for name, d in ix.groupby("index"):
        d = d.sort_values("date").copy()
        d["ret"] = d.close.pct_change()
        d["ma20"] = d.close.rolling(20).mean()
        d["above"] = d.close > d.ma20
        d["r20"] = d.close / d.close.shift(20) - 1
        d = d.rename(columns={c: f"{name}_{c}" for c in ("ret", "above", "r20", "close")})
        out.append(d[["date", f"{name}_ret", f"{name}_above", f"{name}_r20"]])
    ix = out[0].merge(out[1], on="date")
    return p.merge(ix, on="date", how="left")


def path(sig, k, c):
    return sig[f"{c}{k}"].values if k > 0 else sig[{"o": "open", "h": "high", "l": "low", "c": "close"}[c]].values


def simulate(sig, entry, exit_mode="X1"):
    """entry: dict(kind=..., ...) -> 진입일 오프셋/가격 계산 후 시뮬레이션."""
    n = len(sig)
    ek = np.full(n, -1)            # 진입 오프셋
    ep = np.full(n, np.nan)        # 진입가
    intraday = np.zeros(n, bool)   # 장중 진입(진입일 종가부터 판단)
    kind = entry["kind"]
    if kind == "close0":
        ek[:] = 0; ep = sig.close.values.copy()
    elif kind == "open1":
        ek[:] = 1; ep = sig.o1.values.copy(); intraday[:] = True
    elif kind == "close1":
        ek[:] = 1; ep = sig.c1.values.copy()
    elif kind == "open1_gapdown":           # 다음 날 시가가 전일 종가보다 낮을 때만 시가 매수
        m = sig.o1.values < sig.close.values
        ek[m] = 1; ep[m] = sig.o1.values[m]; intraday[m] = True
    elif kind == "dip":                     # 신호일 종가 대비 -x% 지정가, wait 일 동안 대기
        lim = sig.close.values * (1 - entry["x"])
        for k in range(1, entry["wait"] + 1):
            o, l = path(sig, k, "o"), path(sig, k, "l")
            m = (ek < 0) & ~np.isnan(l) & (l <= lim)
            ek[m] = k; ep[m] = np.minimum(o[m], lim[m]); intraday[m] = True
    elif kind == "confirm":                 # 다음 날 종가가 신호일 종가 이상이면 그날 종가 매수
        m = sig.c1.values >= sig.close.values
        ek[m] = 1; ep[m] = sig.c1.values[m]
    filled = (ek >= 0) & ~np.isnan(ep)
    r = np.full(n, np.nan)
    hit = np.zeros(n, bool)
    for i in np.where(filled)[0]:
        e, k0, px = ep[i], ek[i], None
        stop = e * (1 - STOP)
        res, lu = None, False
        last = min(k0 + HOLD, K - 1)
        for k in range(k0, last + 1):
            if k == k0 and not intraday[i]:
                continue
            o, l, c = sig_o[i, k], sig_l[i, k], sig_c[i, k]
            if np.isnan(c):
                res = sig_c[i, k - 1] if k > k0 else e
                break
            if k > k0 and o <= stop:
                res = o; break
            if l <= stop and not (k == k0):
                res = stop; break
            if k == k0 and c <= stop:
                res = c; break
            if sig_lu[i, k] and (k > 0):
                lu = True
                if exit_mode == "X1" or k + 1 >= K or np.isnan(sig_o[i, k + 1]):
                    res = c
                else:
                    res = sig_o[i, k + 1]
                break
            res = c
        r[i] = res / e - 1 - COST
        hit[i] = lu
    return r, filled, hit


def summarize(sig, r, filled, hit, mask):
    m = filled & mask
    rr = r[m]
    if len(rr) == 0:
        return None
    return {"signals": int(mask.sum()), "fills": int(m.sum()), "fill_rate": float(m.sum() / max(mask.sum(), 1)),
            "mean": float(rr.mean()), "median": float(np.median(rr)), "win": float((rr > 0).mean()),
            "lu_hit": float(hit[m].mean()), "p5": float(np.quantile(rr, 0.05)),
            "total_per_100_signals": float(rr.sum() / max(mask.sum(), 1) * 100)}


def main():
    global sig_o, sig_l, sig_c, sig_lu
    p = build(load())
    p = add_index(p)
    w = p[(p.date >= START) & p.prev.notna() & ~p.pref].copy()
    w["period"] = np.where(w.date < SPLIT, "train", "test")
    out = {"split": {"train": [START, SPLIT], "test": [SPLIT, w.date.max()]}}

    # ---------- 1) 지수와 상한가의 관계 ----------
    w["kq_bucket"] = pd.cut(w.KOSDAQ_ret, [-1, -0.03, -0.01, 0.01, 0.03, 1],
                            labels=["-3% 이하 급락", "-3~-1%", "-1~+1% 보합", "+1~+3%", "+3% 이상 급등"])
    out["lu_rate_by_kq_day"] = w.groupby("kq_bucket", observed=True).agg(
        days=("date", "nunique"), lu_rate=("LU", "mean")).round(5).to_dict(orient="index")
    daily = w.groupby("date").agg(lu=("LU", "sum"), kq=("KOSDAQ_ret", "first"),
                                  above=("KOSDAQ_above", "first"), r20=("KOSDAQ_r20", "first"))
    out["daily_corr_lu_kq"] = float(daily.lu.corr(daily.kq))
    out["daily_corr_lu_absk"] = float(daily.lu.corr(daily.kq.abs()))
    out["lu_per_day_by_regime"] = daily.groupby("above").lu.mean().round(2).to_dict()
    daily["r20b"] = pd.cut(daily.r20, [-1, -0.1, -0.03, 0.03, 0.1, 1],
                           labels=["-10% 이하", "-10~-3%", "-3~+3%", "+3~+10%", "+10% 이상"])
    out["lu_per_day_by_r20"] = daily.groupby("r20b", observed=True).lu.agg(["mean", "size"]).round(2).to_dict(orient="index")

    first = w[w.first_LU].copy()
    first["above"] = first.KOSDAQ_above.map({True: "코스닥 20일선 위", False: "코스닥 20일선 아래"})
    first["fwd1"] = first.c1 / first.close - 1
    first["fwd5"] = first.c5 / first.close - 1
    first["fwd10"] = first.c10 / first.close - 1
    first["next_lu"] = first.lu1
    out["first_lu_by_regime"] = first.groupby("above").agg(
        n=("symbol", "size"), next_lu=("next_lu", "mean"), next_ret=("fwd1", "median"),
        fwd5=("fwd5", "median"), fwd10=("fwd10", "median")).round(4).to_dict(orient="index")
    first["kq_day"] = first.kq_bucket
    out["first_lu_by_kq_day"] = first.groupby("kq_day", observed=True).agg(
        n=("symbol", "size"), next_lu=("next_lu", "mean"), fwd5=("fwd5", "median")).round(4).to_dict(orient="index")

    # ---------- 2) 진입 타이밍 비교 ----------
    small = w.mcap < 3e11
    base_A = small & (w.vr >= 3) & w.ret.between(0.05, 0.15) & (w.close_pos >= 0.7)
    signals = {
        "A. 거래량 3배↑+5~15% 상승+고가권 마감": base_A,
        "B. A + 52주 고점 대비 -40% 이하": base_A & (w.dd <= -0.4),
        "L. 첫 상한가": w.first_LU,
        "L2. 첫 상한가 + 당일 거래량 7배 미만": w.first_LU & (w.vr < 7),
    }
    entries = {
        "신호일 종가": {"kind": "close0"},
        "다음 날 시가": {"kind": "open1"},
        "다음 날 시가(갭하락 때만)": {"kind": "open1_gapdown"},
        "다음 날 종가": {"kind": "close1"},
        "다음 날 종가(신호일 종가 이상 확인 후)": {"kind": "confirm"},
        "눌림 -3% 지정가 (3일 대기)": {"kind": "dip", "x": 0.03, "wait": 3},
        "눌림 -5% 지정가 (3일 대기)": {"kind": "dip", "x": 0.05, "wait": 3},
        "눌림 -10% 지정가 (5일 대기)": {"kind": "dip", "x": 0.10, "wait": 5},
    }
    res = {}
    for sname, smask in signals.items():
        sig = w[smask].reset_index(drop=True)
        sig_o = np.column_stack([sig.open.values] + [sig[f"o{k}"].values for k in range(1, K)])
        sig_l = np.column_stack([sig.low.values] + [sig[f"l{k}"].values for k in range(1, K)])
        sig_c = np.column_stack([sig.close.values] + [sig[f"c{k}"].values for k in range(1, K)])
        sig_lu = np.column_stack([sig.LU.values] + [sig[f"lu{k}"].values for k in range(1, K)])
        tr = (sig.period == "train").values
        res[sname] = {}
        for ename, e in entries.items():
            if sname.startswith("L") and ename == "신호일 종가":
                ename_disp = "상한가 종가 (체결 가정)"
            else:
                ename_disp = ename
            row = {}
            for xm in ("X1", "X2"):
                r, f, h = simulate(sig, e, xm)
                row[xm] = {"train": summarize(sig, r, f, h, tr), "test": summarize(sig, r, f, h, ~tr)}
            res[sname][ename_disp] = row
        # 지수 필터 효과 (신호일 종가 진입·X2 기준)
        r, f, h = simulate(sig, {"kind": "open1"} if sname.startswith("L") else {"kind": "close0"}, "X2")
        ab = sig.KOSDAQ_above.fillna(False).values
        res[sname]["_regime"] = {
            "above": {"train": summarize(sig, r, f, h, tr & ab), "test": summarize(sig, r, f, h, ~tr & ab)},
            "below": {"train": summarize(sig, r, f, h, tr & ~ab), "test": summarize(sig, r, f, h, ~tr & ~ab)},
        }
    out["timing"] = res
    with open(os.path.join(ROOT, "refine_summary.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=str)
    print("ok")


if __name__ == "__main__":
    main()
