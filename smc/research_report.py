"""signals.pkl(신호 + 근거)을 분석해서 '어떤 근거가 붙으면 성적이 좋아지는가'를 찾는다.

설계 구간 2018-03 ~ 2021-12 에서만 근거를 고르고, 검증 구간 2022-01 ~ 2026-09 에서 확인한다.
BTC와 ETH에서 모두 같은 방향이어야 '쓸 만한 근거'로 인정한다.

사용:  python -m smc.research_report
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .research import OUT as DATA

SPLIT = pd.Timestamp("2022-01-01", tz="UTC")
NUMERIC = ["day_score", "day_rsi", "day_dist200", "trend4h", "tf_trend", "rsi", "dist_ema20", "dist_ema200",
           "ret20", "close_pos", "funding", "funding_rank", "adx", "vol_rank", "bb_width_rank", "vol_ratio",
           "body_ratio"]
LABEL = {
    "day_score": "일봉 국면 점수 (신호 방향 기준)", "day_rsi": "일봉 RSI (방향 기준)", "day_dist200": "일봉 200일선 이격 (방향 기준)",
    "trend4h": "4시간봉 200EMA 추세 일치", "tf_trend": "같은 봉 200EMA 추세 일치", "rsi": "RSI (방향 기준)",
    "dist_ema20": "20EMA 이격 (ATR 배수, 방향 기준)", "dist_ema200": "200EMA 이격 (방향 기준)", "ret20": "최근 20봉 수익률 (방향 기준)",
    "close_pos": "신호 캔들 종가 위치 (방향 기준)", "funding": "전날 펀딩비 (방향 기준)", "funding_rank": "펀딩비 순위 (방향 기준)",
    "adx": "ADX 추세 강도", "vol_rank": "변동성 순위", "bb_width_rank": "볼린저 폭 순위", "vol_ratio": "거래량 배수",
    "body_ratio": "신호 캔들 몸통 비율", "sweep": "유동성 흡수 동반", "session": "시간대(UTC)",
}


def summary(x: pd.DataFrame) -> dict:
    if len(x) == 0:
        return {"n": 0}
    r = x["r"]
    return {"n": int(len(r)), "win": float((r > 0).mean()), "avg_r": float(r.mean()),
            "se": float(r.std() / np.sqrt(len(r))) if len(r) > 1 else float("nan")}


def baseline(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (tf, fam, side), x in d.groupby(["tf", "family", "side"]):
        tr, te = x[x.time < SPLIT], x[x.time >= SPLIT]
        rows.append({"tf": tf, "신호": fam, "방향": "롱" if side > 0 else "숏",
                     **{f"설계_{k}": v for k, v in summary(tr).items()},
                     **{f"검증_{k}": v for k, v in summary(te).items()},
                     "BTC검증": summary(te[te.symbol == "BTC"]).get("avg_r"),
                     "ETH검증": summary(te[te.symbol == "ETH"]).get("avg_r")})
    return pd.DataFrame(rows)


def add_session(d: pd.DataFrame) -> pd.DataFrame:
    d = d.copy()
    d["session"] = pd.cut(d["hour"], [-1, 7, 12, 20, 23], labels=["아시아 0-7", "유럽 8-12", "미국 13-20", "심야 21-23"])
    return d


def evidence(d: pd.DataFrame) -> pd.DataFrame:
    """근거별로 설계 구간 3분위(하·중·상) 기준 평균 R. 상위 − 하위 차이가 두 구간·두 코인에서 같은 방향인가."""
    tr = d[d.time < SPLIT]
    rows = []
    for feat in NUMERIC + ["sweep", "session"]:
        if feat in ("sweep", "session") or d[feat].nunique() <= 7:
            groups = sorted(d[feat].dropna().unique(), key=lambda v: str(v))
            buckets = {str(g): d[feat] == g for g in groups}
        else:
            q1, q2 = tr[feat].quantile([1 / 3, 2 / 3])
            buckets = {"하위": d[feat] <= q1, "중간": (d[feat] > q1) & (d[feat] <= q2), "상위": d[feat] > q2}
        stats = {}
        for name, m in buckets.items():
            for per, pm in (("설계", d.time < SPLIT), ("검증", d.time >= SPLIT)):
                for sym in ("BTC", "ETH"):
                    x = d[m & pm & (d.symbol == sym)]
                    stats[(name, per, sym)] = x.r.mean() if len(x) >= 30 else np.nan
                stats[(name, per, "합")] = d[m & pm].r.mean()
                stats[(name, per, "n")] = int((m & pm).sum())
        names = list(buckets)
        best = max(names, key=lambda b: stats[(b, "설계", "합")] if np.isfinite(stats[(b, "설계", "합")]) else -9)
        worst = min(names, key=lambda b: stats[(b, "설계", "합")] if np.isfinite(stats[(b, "설계", "합")]) else 9)
        diffs = {k: stats[(best, p, s)] - stats[(worst, p, s)] for k, (p, s) in
                 {"설계BTC": ("설계", "BTC"), "설계ETH": ("설계", "ETH"), "검증BTC": ("검증", "BTC"), "검증ETH": ("검증", "ETH")}.items()}
        rows.append({"근거": LABEL.get(feat, feat), "key": feat, "좋은 구간": best, "나쁜 구간": worst,
                     **{f"차이_{k}": v for k, v in diffs.items()},
                     "일관": all(np.isfinite(v) and v > 0 for v in diffs.values()),
                     "검증_좋은구간_R": stats[(best, "검증", "합")], "검증_나쁜구간_R": stats[(worst, "검증", "합")],
                     "버킷": {b: {"설계R": stats[(b, "설계", "합")], "검증R": stats[(b, "검증", "합")],
                                 "설계n": stats[(b, "설계", "n")], "검증n": stats[(b, "검증", "n")]} for b in names}})
    return pd.DataFrame(rows).sort_values("일관", ascending=False)


def conditions(d: pd.DataFrame) -> dict[str, pd.Series]:
    """규칙 탐색 후보. 기준값은 설계 구간 분위수로만 정한다."""
    tr = d[d.time < SPLIT]
    c = {"일봉 국면이 신호 방향(점수 ≥ 1)": d.day_score >= 1,
         "일봉 국면이 강하게 신호 방향(점수 = 3)": d.day_score >= 3,
         "4시간봉 추세 일치": d.trend4h > 0, "같은 봉 추세 일치": d.tf_trend > 0,
         "유동성 흡수 동반": d.sweep, "지정가 진입(FVG·OB)": d.limit_entry}
    for feat in ("rsi", "dist_ema20", "ret20", "adx", "vol_rank", "bb_width_rank", "vol_ratio", "funding_rank",
                 "close_pos", "body_ratio", "day_rsi"):
        q1, q2 = tr[feat].quantile([1 / 3, 2 / 3])
        c[f"{LABEL[feat]} 하위 1/3 (≤ {q1:.3g})"] = d[feat] <= q1
        c[f"{LABEL[feat]} 상위 1/3 (> {q2:.3g})"] = d[feat] > q2
    return c


def greedy_rules(d: pd.DataFrame, base: pd.Series, max_rules: int = 3, min_frac: float = 0.15) -> list[str]:
    """설계 구간 평균 R이 가장 많이 오르는 조건을 하나씩 추가. 설계 표본이 원래의 min_frac 이상일 때만."""
    cond = conditions(d)
    tr = d.time < SPLIT
    chosen, m = [], base.copy()
    n0 = (m & tr).sum()
    for _ in range(max_rules):
        best, best_r = None, d[m & tr].r.mean()
        for name, cm in cond.items():
            if name in chosen:
                continue
            mm = m & cm
            if (mm & tr).sum() < max(200, min_frac * n0):
                continue
            # 두 코인 모두 설계 구간에서 좋아져야 채택 (한 코인만 좋은 조건 배제)
            ok = all(d[mm & tr & (d.symbol == s)].r.mean() > d[m & tr & (d.symbol == s)].r.mean() for s in ("BTC", "ETH"))
            r = d[mm & tr].r.mean()
            if ok and r > best_r + 0.01:
                best, best_r = name, r
        if best is None:
            break
        chosen.append(best)
        m &= cond[best]
    return chosen


def model_scores(d: pd.DataFrame) -> pd.Series:
    """설계 구간으로 학습한 그래디언트 부스팅이 매긴 '이길 확률'. 검증 구간 신호에만 점수를 매긴다."""
    from sklearn.ensemble import HistGradientBoostingClassifier

    X = pd.get_dummies(d[NUMERIC + ["sweep", "limit_entry", "hour", "weekday", "family", "tf"]].assign(
        sweep=d.sweep.astype(int), limit_entry=d.limit_entry.astype(int)), columns=["family", "tf"], dtype=float)
    y = (d.r > 0).astype(int)
    tr = d.time < SPLIT
    clf = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=200,
                                         l2_regularization=1.0, random_state=0)
    clf.fit(X[tr], y[tr])
    return pd.Series(clf.predict_proba(X)[:, 1], index=d.index)


def equity(x: pd.DataFrame, start=1000.0, risk=0.01, max_open=4) -> dict:
    """동시에 max_open개까지만 보유. 거래당 잔고의 risk만큼 손절 위험."""
    x = x.sort_values("time")
    open_until, pnl_by_exit = [], []
    for _, t in x.iterrows():
        now = t.time
        done = [p for p in pnl_by_exit if p[0] <= now]
        bal = start + sum(p[1] for p in done)
        open_until = [e for e in open_until if e > now]
        if len(open_until) >= max_open or bal <= 0:
            continue
        pnl_by_exit.append((t.exit_time, bal * risk * t.r))
        open_until.append(t.exit_time)
    pnl_by_exit.sort()
    curve = start + np.cumsum([p[1] for p in pnl_by_exit]) if pnl_by_exit else np.array([start])
    peak = np.maximum.accumulate(np.r_[start, curve])[1:]
    return {"final": float(curve[-1]), "mdd": float((curve / peak - 1).min()), "trades": len(pnl_by_exit)}


def main():
    d = add_session(pd.read_pickle(DATA))
    res = {}
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)

    b = baseline(d)
    res["baseline"] = b.to_dict("records")
    print("■ 1. 신호별 기본 성적 (손절 1.5ATR, 익절 1.5R 통일)")
    print(b[["tf", "신호", "방향", "설계_n", "설계_win", "설계_avg_r", "검증_n", "검증_win", "검증_avg_r", "BTC검증", "ETH검증"]]
          .round(3).to_string(index=False))

    ev = evidence(d)
    res["evidence"] = ev.drop(columns=["버킷"]).to_dict("records")
    res["evidence_buckets"] = {r["key"]: r["버킷"] for r in ev.to_dict("records")}
    print("\n■ 2. 근거별 효과 (좋은 구간 − 나쁜 구간 평균 R 차이, 네 칸 모두 + 면 일관)")
    print(ev[["근거", "좋은 구간", "나쁜 구간", "차이_설계BTC", "차이_설계ETH", "차이_검증BTC", "차이_검증ETH", "일관",
              "검증_좋은구간_R", "검증_나쁜구간_R"]].round(3).to_string(index=False))

    print("\n■ 3. 규칙 탐색 (설계 구간에서만 고르고 검증 구간에서 확인)")
    rules = {}
    allm = pd.Series(True, index=d.index)
    targets = {"전체 신호": allm, **{f"{tf} {fam}": (d.tf == tf) & (d.family == fam)
                                    for tf in ("1h", "4h") for fam in d.family.unique()}}
    cond = conditions(d)
    for name, base in targets.items():
        chosen = greedy_rules(d, base)
        m = base.copy()
        for c in chosen:
            m &= cond[c]
        tr, te = d[m & (d.time < SPLIT)], d[m & (d.time >= SPLIT)]
        row = {"대상": name, "고른 근거": chosen, "설계": summary(tr), "검증": summary(te),
               "검증BTC": summary(te[te.symbol == "BTC"]), "검증ETH": summary(te[te.symbol == "ETH"]),
               "원래검증": summary(d[base & (d.time >= SPLIT)]),
               "자금_검증": equity(te), "자금_전체": equity(d[m])}
        rules[name] = row
        print(f"  {name:14} {(' + '.join(chosen) or '(개선 조건 없음)')[:110]}")
        print(f"     설계 {row['설계']['n']}건 승률 {row['설계'].get('win', 0)*100:.1f}% {row['설계'].get('avg_r', 0):+.3f}R"
              f" | 검증 {row['검증']['n']}건 승률 {row['검증'].get('win', 0)*100:.1f}% {row['검증'].get('avg_r', 0):+.3f}R"
              f" (BTC {row['검증BTC'].get('avg_r', float('nan')):+.3f} / ETH {row['검증ETH'].get('avg_r', float('nan')):+.3f})"
              f" | 원래 검증 {row['원래검증'].get('avg_r', 0):+.3f}R | 검증기간 $1,000 → ${row['자금_검증']['final']:,.0f}")
    res["rules"] = rules

    print("\n■ 4. 머신러닝 점수로 거르기 (설계 구간 학습 → 검증 구간 적용)")
    p = model_scores(d)
    te = d.time >= SPLIT
    ml = {}
    for th in (0.0, 0.45, 0.5, 0.55, 0.6):
        x = d[te & (p >= th)]
        s = summary(x)
        ml[str(th)] = {**s, "BTC": summary(x[x.symbol == "BTC"]), "ETH": summary(x[x.symbol == "ETH"]),
                       "자금": equity(x) if len(x) else None}
        if s["n"]:
            print(f"  점수 ≥ {th:.2f}: {s['n']:6}건 승률 {s['win']*100:5.1f}% 평균 {s['avg_r']:+.3f}R ±{s['se']:.3f}"
                  f" (BTC {ml[str(th)]['BTC'].get('avg_r', float('nan')):+.3f} / ETH {ml[str(th)]['ETH'].get('avg_r', float('nan')):+.3f})"
                  f"  $1,000 → ${ml[str(th)]['자금']['final']:,.0f}")
    res["ml"] = ml
    out = Path(DATA).with_name("research.json")
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=lambda o: o if not hasattr(o, "item") else o.item()))
    print(f"\n저장: {out}")


if __name__ == "__main__":
    main()
