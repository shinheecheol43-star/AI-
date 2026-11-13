"""최근 3년 상한가 이벤트 추출·특징 분석.

정의
- 상한가(종가): 종가 / 전일종가 - 1 >= 29.5%  (호가단위 반올림 감안)
- 상한가 터치: 고가 / 전일종가 - 1 >= 29.5% (종가는 미달 포함)
- +32% 초과 변동은 가격제한폭 밖(상장 첫날·감자/병합 후 재상장 등 기준가 재설정
  또는 데이터 오류)이므로 제외하고 별도 집계
- 분석 기간: 2023-11-13 ~ 최신 거래일
"""
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")
START = "2023-11-13"
LIMIT = 0.295
MAXOK = 0.32


def load():
    u = pd.read_csv(os.path.join(ROOT, "universe.csv"), dtype={"symbol": str})
    u["code"] = u.symbol.str[:6]
    u["share_class"] = np.where(u.code.str[-1] == "0", "보통주", "우선주")
    p = pd.read_csv(os.path.join(ROOT, "prices.csv.gz"))
    p = p.drop_duplicates(["symbol", "date"]).sort_values(["symbol", "date"])
    p = p[p.close > 0]
    return u, p


def features(p):
    g = p.groupby("symbol", group_keys=False)
    p["prev_close"] = g.close.shift(1)
    p["ret"] = p.close / p.prev_close - 1
    p["hi_ret"] = p.high / p.prev_close - 1
    p["vol_ma20"] = g.volume.transform(lambda s: s.shift(1).rolling(20, min_periods=10).mean())
    p["vol_ratio"] = p.volume / p.vol_ma20.replace(0, np.nan)
    p["high_252"] = g.high.transform(lambda s: s.shift(1).rolling(252, min_periods=120).max())
    p["dd_from_high"] = p.prev_close / p.high_252 - 1
    p["ret_20d_before"] = p.prev_close / g.close.shift(21) - 1
    for k in (1, 5, 20):
        p[f"fwd_{k}d"] = g.close.shift(-k) / p.close - 1
    p["next_open_gap"] = g.open.shift(-1) / p.close - 1
    p["next_ret"] = g.ret.shift(-1)
    p["prev_ret"] = g.ret.shift(1)
    p["next_hi_ret"] = g.hi_ret.shift(-1)
    return p


def bucket_cap(x):
    bins = [0, 50e9, 100e9, 300e9, 1e12, 5e12, np.inf]
    labels = ["500억 미만", "500억~1천억", "1천억~3천억", "3천억~1조", "1조~5조", "5조 이상"]
    return pd.cut(x, bins, labels=labels, right=False)


def year_label(d):
    if d < "2024-11-13":
        return "1년차 (23.11~24.11)"
    if d < "2025-11-13":
        return "2년차 (24.11~25.11)"
    return "3년차 (25.11~26.11)"


def main():
    u, p = load()
    p = features(p)
    p = p.merge(u[["symbol", "name", "market", "sector", "shares", "share_class"]],
                on="symbol", how="left")
    p["mcap_prev"] = p.prev_close * p.shares
    w = p[(p.date >= START) & p.prev_close.notna()].copy()

    abnormal = w[w.ret > MAXOK]
    lu = w[(w.ret >= LIMIT) & (w.ret <= MAXOK)].copy()
    touch = w[(w.hi_ret >= LIMIT) & (w.hi_ret <= MAXOK)]
    lu["period"] = lu.date.map(year_label)
    lu["cap_bucket"] = bucket_cap(lu.mcap_prev)
    lu["streak_next"] = lu.next_ret >= LIMIT
    lu["after_streak"] = lu.prev_ret >= LIMIT

    all_days = w.copy()
    all_days["cap_bucket"] = bucket_cap(all_days.mcap_prev)

    out = {}
    out["meta"] = {
        "start": START, "end": w.date.max(), "universe": int(u.shape[0]),
        "universe_by_market": u.market.value_counts().to_dict(),
        "trading_days": int(w.date.nunique()),
        "limit_up_events": int(len(lu)), "limit_up_stocks": int(lu.symbol.nunique()),
        "touch_events": int(len(touch)),
        "touch_close_ratio": float(len(lu) / len(touch)) if len(touch) else None,
        "abnormal_excluded": int(len(abnormal)),
    }
    out["by_period_market"] = (lu.groupby(["period", "market"]).size()
                               .unstack(fill_value=0).to_dict(orient="index"))
    out["stocks_by_period"] = lu.groupby("period").symbol.nunique().to_dict()
    out["by_month"] = lu.groupby([lu.date.str[:7], "market"]).size().unstack(fill_value=0)\
        .to_dict(orient="index")
    out["by_class"] = lu.share_class.value_counts().to_dict()

    sec = lu.groupby("sector").agg(events=("symbol", "size"), stocks=("symbol", "nunique"))
    sec["universe"] = u.groupby("sector").size()
    sec["stock_hit_rate"] = sec.stocks / sec.universe
    sec["events_per_100"] = sec.events / sec.universe * 100
    sec["kosdaq_share"] = lu[lu.market == "KOSDAQ"].groupby("sector").size() / sec.events
    sec["next_ret_mean"] = lu.groupby("sector").next_ret.mean()
    sec["fwd_20d_median"] = lu.groupby("sector").fwd_20d.median()
    out["by_sector"] = sec.sort_values("events", ascending=False).round(4).to_dict(orient="index")

    capd = pd.DataFrame({
        "events": lu.cap_bucket.value_counts(),
        "all_stock_days": all_days.cap_bucket.value_counts(),
    })
    capd["event_share"] = capd.events / capd.events.sum()
    capd["day_share"] = capd.all_stock_days / capd.all_stock_days.sum()
    capd["lift"] = capd.event_share / capd.day_share
    out["by_cap"] = capd.reindex(lu.cap_bucket.cat.categories).round(4).to_dict(orient="index")

    def dist(s, qs=(0.1, 0.25, 0.5, 0.75, 0.9)):
        s = s.replace([np.inf, -np.inf], np.nan).dropna()
        return {"n": int(s.size), "mean": float(s.mean()),
                **{f"p{int(q*100)}": float(s.quantile(q)) for q in qs}}

    out["pre_features"] = {
        "dd_from_high_limitup": dist(lu.dd_from_high),
        "dd_from_high_all": dist(all_days.dd_from_high.sample(min(300000, len(all_days)), random_state=0)),
        "ret_20d_before_limitup": dist(lu.ret_20d_before),
        "ret_20d_before_all": dist(all_days.ret_20d_before.sample(min(300000, len(all_days)), random_state=0)),
        "vol_ratio_limitup": dist(lu.vol_ratio),
        "price_limitup": dist(lu.prev_close),
        "price_all": dist(all_days.prev_close.sample(min(300000, len(all_days)), random_state=0)),
    }
    dd_bins = [-1, -0.7, -0.5, -0.3, -0.1, 0.0001]
    dd_lab = ["-70% 이하", "-70~-50%", "-50~-30%", "-30~-10%", "-10~0% (신고가 근처)"]
    out["dd_bucket"] = pd.DataFrame({
        "limitup": pd.cut(lu.dd_from_high, dd_bins, labels=dd_lab).value_counts(normalize=True),
        "all": pd.cut(all_days.dd_from_high, dd_bins, labels=dd_lab).value_counts(normalize=True),
    }).reindex(dd_lab).round(4).to_dict(orient="index")

    fw = {}
    for name, s in [("next_open_gap", lu.next_open_gap), ("next_ret", lu.next_ret),
                    ("fwd_5d", lu.fwd_5d), ("fwd_20d", lu.fwd_20d)]:
        s = s.dropna()
        fw[name] = {**dist(s), "win_rate": float((s > 0).mean())}
    fw["next_limitup_rate"] = float(lu.streak_next.mean())
    fw["next_touch_rate"] = float((lu.next_hi_ret >= LIMIT).mean())
    fw["next_hi_ret_median"] = float(lu.next_hi_ret.median())
    first = lu[~lu.after_streak]
    fw["first_limitup_next_ret_mean"] = float(first.next_ret.mean())
    fw["second_after_streak_rate"] = float(lu[lu.after_streak].streak_next.mean()) \
        if lu.after_streak.any() else None
    out["forward"] = fw
    out["forward_by_market"] = lu.groupby("market")[["next_ret", "fwd_5d", "fwd_20d"]]\
        .median().round(4).to_dict(orient="index")
    out["forward_by_cap"] = lu.groupby("cap_bucket", observed=True)[["next_ret", "fwd_20d"]]\
        .median().round(4).to_dict(orient="index")

    # 연속 상한가 길이
    lu_sorted = lu.sort_values(["symbol", "date"])
    streaks, cur = [], 0
    for _, r in lu_sorted.iterrows():
        cur = cur + 1 if r.after_streak else 1
        if not r.streak_next:
            streaks.append(cur)
            cur = 0
    out["streak_len"] = pd.Series(streaks).value_counts().sort_index().to_dict()

    rep = lu.groupby(["symbol", "name", "market", "sector"]).agg(
        count=("date", "size"), first=("date", "min"), last=("date", "max"))\
        .sort_values("count", ascending=False).head(30).reset_index()
    out["top_repeat"] = rep.to_dict(orient="records")
    com = lu[lu.share_class == "보통주"]
    out["top_repeat_common"] = com.groupby(["symbol", "name", "market", "sector"]).agg(
        count=("date", "size"), first=("date", "min"), last=("date", "max"),
        mcap_median=("mcap_prev", "median"))\
        .sort_values("count", ascending=False).head(20).reset_index().to_dict(orient="records")
    out["by_market_total"] = lu.market.value_counts().to_dict()
    out["sector_by_period"] = lu.groupby(["sector", "period"]).size().unstack(fill_value=0)\
        .to_dict(orient="index")
    rc = lu.groupby("symbol").size()
    out["repeat_dist"] = {"1회": int((rc == 1).sum()), "2회": int((rc == 2).sum()),
                          "3~4회": int(rc.between(3, 4).sum()), "5회 이상": int((rc >= 5).sum())}
    out["daily_count"] = lu.groupby("date").size().describe().round(2).to_dict()
    out["busiest_days"] = lu.groupby("date").size().sort_values(ascending=False).head(10).to_dict()
    out["weekday"] = lu.date.map(lambda d: pd.Timestamp(d).day_name()).value_counts().to_dict()
    out["kumho_check"] = lu[lu.symbol == "002990.KS"][["date", "ret", "next_ret"]]\
        .round(4).to_dict(orient="records")

    lu.drop(columns=["cap_bucket"]).to_csv(os.path.join(ROOT, "limit_up_events.csv"),
                                          index=False, float_format="%.4f")
    with open(os.path.join(ROOT, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print(json.dumps(out["meta"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
