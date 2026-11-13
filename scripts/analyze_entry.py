"""상한가 전조 · 진입 신호 백테스트 · 손절/하한가 위험 분석 -> data/entry_summary.json

- 상한가(LU): 종가/전일종가-1 >= +29.5% (+32% 초과는 기준가 재설정으로 제외)
- 하한가(LD): <= -29.5% (-32% 미만 제외)
- 첫 상한가: 직전 20거래일 안에 상한가가 없던 상한가
- 신호일 t 종가에 진입(종가 동시호가 가정), 이후 최대 H=10거래일 관찰
"""
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
START = "2023-11-13"
H = 10


def load():
    u = pd.read_csv(os.path.join(ROOT, "universe.csv"))
    p = pd.read_csv(os.path.join(ROOT, "prices.csv.gz"))
    p = p.drop_duplicates(["symbol", "date"]).sort_values(["symbol", "date"]).reset_index(drop=True)
    p = p[(p.close > 0) & (p.low > 0)].reset_index(drop=True)
    p = p.merge(u[["symbol", "market", "sector", "shares"]], on="symbol", how="left")
    p["pref"] = p.symbol.str[5] != "0"
    return p


def build(p):
    g = p.groupby("symbol", group_keys=False)
    p["prev"] = g.close.shift(1)
    p["ret"] = p.close / p.prev - 1
    valid = p.ret.between(-0.32, 0.32)
    p["LU"] = (p.ret >= 0.295) & valid
    p["LD"] = (p.ret <= -0.295) & valid
    p["LD_lock"] = p.LD & (p.close <= p.low * 1.001)          # 하한가 잠김(팔 수 없음)
    p["vma20"] = g.volume.transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    p["vr"] = p.volume / p.vma20.replace(0, np.nan)
    p["hi252"] = g.high.transform(lambda s: s.shift(1).rolling(252, min_periods=120).max())
    p["dd"] = p.prev / p.hi252 - 1
    rng = (p.high - p.low).replace(0, np.nan)
    p["close_pos"] = (p.close - p.low) / rng                  # 1=고가 마감
    p["upper_shadow"] = (p.high - p.close) / p.prev
    p["hi_ret"] = p.high / p.prev - 1
    p["mcap"] = p.prev * p.shares
    p["lu_prev20"] = g.LU.transform(lambda s: s.shift(1).rolling(20, min_periods=1).sum()).fillna(0)
    p["first_LU"] = p.LU & (p.lu_prev20 == 0)
    # 미래 경로
    for k in range(1, H + 1):
        p[f"o{k}"] = g.open.shift(-k)
        p[f"l{k}"] = g.low.shift(-k)
        p[f"c{k}"] = g.close.shift(-k)
        p[f"lu{k}"] = g.LU.shift(-k).fillna(False).astype(bool)
        p[f"ld{k}"] = g.LD.shift(-k).fillna(False).astype(bool)
    # 과거 경로 (D-1..D-10)
    for k in range(1, 11):
        p[f"pret{k}"] = g.ret.shift(k)
        p[f"pvr{k}"] = g.vr.shift(k)
        p[f"phr{k}"] = g.hi_ret.shift(k)
    return p


def pre_footprint(p, w):
    ev = w[w.first_LU & ~w.pref]
    base = w[~w.LU & ~w.pref & w.vr.notna()].sample(300000, random_state=1)
    out = {"n_first_lu": int(len(ev))}
    days = {}
    for k in range(1, 11):
        days[f"D-{k}"] = {
            "ret_med": float(ev[f"pret{k}"].median()),
            "vr_med": float(ev[f"pvr{k}"].median()),
            "vr3_share": float((ev[f"pvr{k}"] >= 3).mean()),
            "up10_share": float((ev[f"pret{k}"] >= 0.10).mean()),
        }
    out["by_day"] = days
    out["base_vr3_share"] = float((base.vr >= 3).mean())
    out["base_up10_share"] = float((base.ret >= 0.10).mean())

    def any_k(df, col, cond, ks):
        m = np.zeros(len(df), bool)
        for k in ks:
            m |= cond(df[f"{col}{k}"]).fillna(False).values
        return m

    bp = base
    feats = {
        "D-5~D-1 중 거래량 3배 이상 하루 이상": ("pvr", lambda s: s >= 3),
        "D-5~D-1 중 거래량 5배 이상 하루 이상": ("pvr", lambda s: s >= 5),
        "D-5~D-1 중 +10% 이상 상승일": ("pret", lambda s: s >= 0.10),
        "D-5~D-1 중 장중 +15% 이상 터치": ("phr", lambda s: s >= 0.15),
        "D-1 거래량 2배 이상": None,
        "D-1 상승 마감": None,
    }
    res = {}
    for name, f in feats.items():
        if f is None:
            if name.startswith("D-1 거래량"):
                a, b = (ev.pvr1 >= 2).mean(), (bp.pvr1 >= 2).mean()
            else:
                a, b = (ev.pret1 > 0).mean(), (bp.pret1 > 0).mean()
        else:
            col, c = f
            a = any_k(ev, col, c, range(1, 6)).mean()
            b = any_k(bp, col, c, range(1, 6)).mean()
        res[name] = {"limitup": float(a), "base": float(b), "lift": float(a / b) if b else None}
    out["features"] = res
    out["cum5_med"] = float((ev[[f"pret{k}" for k in range(1, 6)]].add(1).prod(axis=1) - 1).median())
    out["quiet_share"] = float(((ev[[f"pvr{k}" for k in range(1, 6)]].max(axis=1) < 2) &
                                (ev[[f"pret{k}" for k in range(1, 6)]].abs().max(axis=1) < 0.05)).mean())
    out["lu_day_vr"] = {q: float(ev.vr.quantile(q)) for q in (0.25, 0.5, 0.75)}
    return out


def simulate(sig, stops=(0.05, 0.07, 0.10, 0.15, None), hold=H):
    """신호일 종가 진입. 매일: 시가<=손절가 -> 시가청산(갭손실), 저가<=손절가 -> 손절가 청산,
    상한가 마감 -> 그날 종가 청산, hold일째 종가 청산."""
    entry = sig.close.values
    res = {}
    for s in stops:
        stop = entry * (1 - s) if s else np.full(len(entry), -1.0)
        exitp = np.full(len(entry), np.nan)
        reason = np.full(len(entry), "", dtype=object)
        done = np.zeros(len(entry), bool)
        for k in range(1, hold + 1):
            o, l, c, lu = (sig[f"o{k}"].values, sig[f"l{k}"].values, sig[f"c{k}"].values,
                           sig[f"lu{k}"].values)
            na = np.isnan(c)
            m = ~done & na                                   # 데이터 끝: 직전 상태 유지
            if k == 1:
                exitp[m] = entry[m]
            else:
                exitp[m] = sig[f"c{k-1}"].values[m]
            reason[m] = "data_end"
            done |= m
            gap = ~done & (o <= stop)
            exitp[gap] = o[gap]; reason[gap] = "gap_stop"; done |= gap
            hit = ~done & (l <= stop)
            exitp[hit] = stop[hit]; reason[hit] = "stop"; done |= hit
            up = ~done & lu
            exitp[up] = c[up]; reason[up] = "limit_up"; done |= up
            if k == hold:
                t = ~done
                exitp[t] = c[t]; reason[t] = "time"; done |= t
        r = exitp / entry - 1
        ok = ~np.isnan(r)
        r, reason = r[ok], reason[ok]
        key = f"-{int(s*100)}%" if s else "손절 없음"
        res[key] = {
            "n": int(len(r)), "mean": float(r.mean()), "median": float(np.median(r)),
            "win": float((r > 0).mean()), "lu_exit": float((reason == "limit_up").mean()),
            "stop_exit": float(np.isin(reason, ["stop", "gap_stop"]).mean()),
            "gap_stop": float((reason == "gap_stop").mean()),
            "gap_loss_med": float(np.median(r[reason == "gap_stop"])) if (reason == "gap_stop").any() else None,
            "worst": float(r.min()), "p5": float(np.quantile(r, 0.05)),
        }
    return res


def signal_stats(sig, name):
    lus = sig[[f"lu{k}" for k in range(1, H + 1)]].values
    any_lu = lus.any(axis=1)
    first_k = np.where(any_lu, lus.argmax(axis=1) + 1, 0)
    lows = sig[[f"l{k}" for k in range(1, H + 1)]].values / sig.close.values[:, None] - 1
    # 상한가 전까지의 최대 역행폭(MAE)
    mask = np.arange(1, H + 1)[None, :] <= np.where(any_lu, first_k, H)[:, None]
    mae = np.where(mask, lows, np.nan)
    mae = np.nanmin(mae, axis=1)
    lds = sig[[f"ld{k}" for k in range(1, H + 1)]].values
    out = {
        "name": name, "n": int(len(sig)), "stocks": int(sig.symbol.nunique()),
        "lu_within": {f"{d}일": float(lus[:, :d].any(axis=1).mean()) for d in (1, 3, 5, 10)},
        "days_to_lu": {str(k): int((first_k == k).sum()) for k in range(1, H + 1)},
        "ld_within10": float(lds.any(axis=1).mean()),
        "mae_winners": {f"p{int(q*100)}": float(np.nanquantile(mae[any_lu], q))
                        for q in (0.5, 0.75, 0.9, 0.95)} if any_lu.any() else None,
        "mae_losers_med": float(np.nanmedian(mae[~any_lu])),
        "winner_survive": {f"-{int(x*100)}%": float((mae[any_lu] > -x).mean()) for x in (0.05, 0.07, 0.10, 0.15, 0.20)}
        if any_lu.any() else None,
        "vr_winners_med": float(sig.vr[any_lu].median()) if any_lu.any() else None,
        "vr_losers_med": float(sig.vr[~any_lu].median()),
        "lu_day_vr_med": float(np.nanmedian(np.array([sig[f"lu{k}"].values for k in range(1, H + 1)]).T.argmax(axis=1)[any_lu]))
        if False else None,
        "vr_med": float(sig.vr.median()),
        "sim": simulate(sig),
    }
    return out


def main():
    p = build(load())
    w = p[(p.date >= START) & p.prev.notna()].copy()
    out = {"pre": pre_footprint(p, w)}

    small = w.mcap < 3e11
    common = ~w.pref & w.vr.notna()
    base = w[common & ~w.LU]
    sigs = {
        "기준: 아무 날이나 종가 매수": base.sample(200000, random_state=2),
        "A. 거래량 3배↑ + 5~15% 상승 + 고가권 마감": w[common & small & (w.vr >= 3) & w.ret.between(0.05, 0.15)
                                              & (w.close_pos >= 0.7)],
        "B. A + 52주 고점 대비 -40% 이하": w[common & small & (w.vr >= 3) & w.ret.between(0.05, 0.15)
                                       & (w.close_pos >= 0.7) & (w.dd <= -0.4)],
        "C. 거래량 5배↑ + 15~29% 급등(상한가 실패)": w[common & small & (w.vr >= 5) & w.ret.between(0.15, 0.295)],
        "D. 장중 +20% 이상 갔다가 윗꼬리(종가 +10% 이하)": w[common & small & (w.hi_ret >= 0.20) & (w.ret <= 0.10)],
        "E. 첫 상한가 다음 날 종가 추격(따라잡기)": None,
        "F. 상한가 당일 종가 매수(상한가 따라잡기)": w[common & w.first_LU],
    }
    # E: 첫 상한가 다음 날 종가 진입
    g = w.groupby("symbol").first_LU.shift(1).fillna(False).astype(bool)
    sigs["E. 첫 상한가 다음 날 종가 추격(따라잡기)"] = w[common & g]
    out["signals"] = [signal_stats(s, n) for n, s in sigs.items()]

    # 하한가 위험
    ld = w[w.LD & ~w.pref]
    out["ld"] = {
        "events": int(len(ld)), "stocks": int(ld.symbol.nunique()),
        "lock_share": float(ld.LD_lock.mean()),
        "next_ld_rate": float(ld.ld1.mean()),
        "per_lu_ratio": float(len(ld) / w[w.LU & ~w.pref].shape[0]),
        "by_month": ld.groupby(ld.date.str[5:7]).size().to_dict(),
    }
    lu = w[w.LU & ~w.pref]
    ld20 = np.zeros(len(lu), bool)
    for k in range(1, H + 1):
        ld20 |= lu[f"ld{k}"].values
    out["ld"]["after_lu10"] = float(ld20.mean())
    # 상한가 후 10일 내 최저점 분포
    lows = lu[[f"l{k}" for k in range(1, H + 1)]].min(axis=1) / lu.close - 1
    out["ld"]["after_lu_low10"] = {f"p{int(q*100)}": float(lows.quantile(q)) for q in (0.1, 0.25, 0.5)}
    # 갭 하락 위험: 상한가 다음 날 시가가 -10% 이하로 출발한 비율
    gap = lu.o1 / lu.close - 1
    out["ld"]["lu_next_gap_le_-10"] = float((gap <= -0.10).mean())

    # 일정 효과: 실적 공시 시즌 (분기보고서 마감 5/15, 8/14, 11/14 전후 10일, 연간 2/15~3/31)
    md = w.date.str[5:]
    season = (md.between("05-05", "05-25") | md.between("08-04", "08-24") |
              md.between("11-04", "11-24") | md.between("02-15", "03-31"))
    audit = md.between("03-10", "04-05")
    cw = w[common]
    s_c = season.loc[cw.index]
    a_c = audit.loc[cw.index]
    out["calendar"] = {
        "lu_rate_season": float(cw[s_c].LU.mean()), "lu_rate_other": float(cw[~s_c].LU.mean()),
        "ld_rate_audit": float(cw[a_c].LD.mean()), "ld_rate_other": float(cw[~a_c].LD.mean()),
        "lu_by_month": cw.groupby(cw.date.str[5:7]).LU.mean().round(5).to_dict(),
        "ld_by_month": cw.groupby(cw.date.str[5:7]).LD.mean().round(5).to_dict(),
    }

    with open(os.path.join(ROOT, "entry_summary.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str)[:20000])


if __name__ == "__main__":
    main()
