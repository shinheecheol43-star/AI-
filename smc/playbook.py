"""여러 패턴을 상황에 맞게 골라 쓰는 '종합 매매' 검증 (BTC·ETH, 1시간봉·4시간봉).

재료: research.py 의 7가지 진입 패턴 (강의 내용 포함)
  추세형  20봉돌파 · EMA교차 · OB(오더블럭 되돌림 지정가) · FVG(갭 되돌림 지정가)
  반전형  거짓돌파(= 스탑헌팅: 고·저점 쓸고 되돌아옴) · 채널반전 · RSI반전
  청산은 모두 같게: 손절 1.5 ATR, 목표 1.5R, 최대 1h 48봉 / 4h 30봉, 수수료 포함 (패턴끼리 공정하게 비교)
상황(장세) 판단 — 신호 방향 기준, 진입 시점에 알 수 있는 것만
  횡보   : ADX < 20
  순추세 : (횡보 아님) 일봉 국면 점수가 신호 방향 + 4시간봉 200EMA 도 신호 방향
  역추세 : (횡보 아님) 둘 다 반대 방향          혼합 : 나머지
종합 매매 방식 (A·C·D 는 결과를 보기 전에 정함)
  A 규칙 플레이북: 순추세면 추세형 4가지, 횡보면 반전형 3가지, 역추세·혼합이면 쉼
  B 데이터 플레이북: 설계 구간(~2021)에서 (봉·패턴·장세) 칸 중 80건 이상 & 평균 +0.10R 이상인 칸만
  C 겹침(컨플루언스): 같은 코인·방향으로 서로 다른 패턴 2개 이상이 3봉 안에 나오면 (+ A 의 장세 조건 있는/없는)
  D 모델: 해마다 다시 학습(그 해는 못 본 상태)한 모델이 '이길 확률'이 높다고 할 때만 (기준 0.50·0.55·0.60)
     특징 = 패턴 종류 + 장세 근거 20여 개 (일봉 점수·RSI·200일선 거리·4시간 추세·ADX·변동성·펀딩비·시각 등)
계좌: 거래당 0.5%, 레버리지 합계 ≤ 3배, 코인·봉마다 한 번에 한 거래
판정 (미리 정함): 검증(2022~) 연수익 > 0, 최대 낙폭 > −20%, 평균 R 이 '7가지 전부 그냥 다 매매'보다 0.05 이상 높음

사용:  python -m smc.playbook
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from .dd_brake import curve
from .research_report import SPLIT
from .swing_ls import describe

DATA = Path(__file__).resolve().parent.parent / "reports" / "signals.pkl"
TREND = ("20봉돌파", "EMA교차", "OB", "FVG")
REVERSAL = ("거짓돌파", "채널반전", "RSI반전")
RISK = 0.005
FEATS = ["day_score", "day_rsi", "day_dist200", "trend4h", "tf_trend", "rsi", "dist_ema20", "dist_ema200", "ret20",
         "close_pos", "funding", "funding_rank", "adx", "vol_rank", "bb_width_rank", "vol_ratio", "body_ratio", "hour",
         "weekday", "sweep", "limit_entry"]
BAR = {"1h": pd.Timedelta("1h"), "4h": pd.Timedelta("4h")}


def load() -> pd.DataFrame:
    d = pd.read_pickle(DATA)
    d = d[d.time >= pd.Timestamp("2018-03-15", tz="UTC")].copy()
    reg = np.where(d.adx < 20, "횡보",
                   np.where((d.day_score > 0) & (d.trend4h > 0), "순추세",
                            np.where((d.day_score < 0) & (d.trend4h < 0), "역추세", "혼합")))
    d["regime"] = reg
    d["entry"] = d.entry_time + d.tf.map(BAR)            # 진입 봉 시작 → 체결 시각 근사
    d["exit"] = d.exit_time
    d["kind"] = np.where(d.family.isin(TREND), "추세형", "반전형")
    return d.sort_values("entry").reset_index(drop=True)


def one_at_a_time(x: pd.DataFrame) -> pd.DataFrame:
    """코인·봉마다 한 번에 한 거래 (먼저 나온 것 우선)."""
    keep = []
    for _, g in x.sort_values("entry").groupby(["symbol", "tf"]):
        busy = None
        for t in g.itertuples():
            if busy is not None and t.entry < busy:
                continue
            keep.append(t.Index)
            busy = t.exit
    return x.loc[keep]


def account(x: pd.DataFrame):
    x = one_at_a_time(x)
    if len(x) < 5:
        return None
    y = x.assign(risk=RISK)
    cv, _ = curve(y[["entry", "exit", "r", "risk", "stop_pct"]])
    d = describe(cv)
    te = x[x.entry >= SPLIT]
    return dict(n=len(x), n_te=len(te), r_te=te.r.mean(), win_te=(te.r > 0).mean(), full=d["full"], design=d["design"],
                test=d["test"], years=d["years"], per_m=len(te) / 4.75 / 12)


def line(name: str, a: dict | None, base_r: float) -> str:
    if a is None:
        return f"  {name:34} | 거래 없음"
    ok = a["test"][0] > 0 and a["test"][1] > -0.20 and a["r_te"] - base_r >= 0.05
    ys = " ".join(f"{a['years'][y]*100:+4.0f}%" for y in range(2022, 2027))
    return (f"  {name:34} | 설계 연 {a['design'][0]*100:+6.1f}% | 검증 연 {a['test'][0]*100:+6.1f}% 낙폭 {a['test'][1]*100:5.1f}%"
            f" 승률 {a['win_te']*100:3.0f}% 평균 {a['r_te']:+.3f}R 월 {a['per_m']:4.1f}건 | {ys} | {'✅' if ok else '–'}")


def confluence(d: pd.DataFrame, need: int = 2, bars: int = 3) -> pd.DataFrame:
    rows = []
    for (sym, tf, side), g in d.groupby(["symbol", "tf", "side"]):
        g = g.sort_values("time")
        t, fam = g.time.to_numpy(), g.family.to_numpy()
        w = np.timedelta64(int(bars * BAR[tf].total_seconds()), "s")
        lo = 0
        for k in range(len(g)):
            while t[k] - t[lo] > w:
                lo += 1
            if len(set(fam[lo:k + 1])) >= need:
                rows.append(g.index[k])
    return d.loc[sorted(set(rows))]


def model(d: pd.DataFrame) -> pd.DataFrame:
    X = pd.get_dummies(d[FEATS + ["family", "tf"]].astype({"sweep": float, "limit_entry": float}), columns=["family", "tf"]).astype(float)
    y = (d.r > 0).astype(int)
    out = []
    for yr in range(2020, 2027):
        a, b = pd.Timestamp(f"{yr}-01-01", tz="UTC"), pd.Timestamp(f"{yr + 1}-01-01", tz="UTC")
        tr = d.exit < a
        te = (d.entry >= a) & (d.entry < b)
        if te.sum() == 0:
            continue
        m = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=200,
                                           l2_regularization=1.0, random_state=0)
        cols = X.columns[X[tr].notna().any() & (X[tr].nunique() > 1)]
        m.fit(X.loc[tr, cols], y[tr])
        out.append(pd.Series(m.predict_proba(X.loc[te, cols])[:, 1], index=d.index[te]))
    return pd.concat(out)


def main():
    d = load()
    print(f"신호 {len(d):,}개 (BTC·ETH, 1h·4h, 7가지 패턴) · 설계 ~2021 / 검증 2022~ · 청산 통일(손절 1.5ATR·목표 1.5R)\n")

    print("■ 1. 패턴 × 장세 평균 R (설계 / 검증, 건수) — '상황에 맞는 패턴'이 있는가")
    piv = []
    for (tf, fam, reg), g in d.groupby(["tf", "family", "regime"]):
        a, b = g[g.entry < SPLIT], g[g.entry >= SPLIT]
        piv.append(dict(tf=tf, family=fam, regime=reg, n_tr=len(a), r_tr=a.r.mean(), n_te=len(b), r_te=b.r.mean()))
    P = pd.DataFrame(piv)
    for tf in ("1h", "4h"):
        print(f"  [{tf}]  {'패턴':6} | " + " | ".join(f"{r:^19}" for r in ("순추세", "횡보", "혼합", "역추세")))
        for fam in TREND + REVERSAL:
            cells = []
            for reg in ("순추세", "횡보", "혼합", "역추세"):
                c = P[(P.tf == tf) & (P.family == fam) & (P.regime == reg)]
                cells.append(f"{c.r_tr.iat[0]:+.2f}/{c.r_te.iat[0]:+.2f} ({c.n_te.iat[0]:4})" if len(c) else " " * 19)
            print(f"        {fam:6} | " + " | ".join(cells))
    good_cells = P[(P.n_tr >= 80) & (P.r_tr >= 0.10)]
    print(f"\n  설계 구간에서 +0.10R 이상이던 칸 {len(good_cells)}개 중 검증에서도 플러스 {int((good_cells.r_te > 0).sum())}개"
          f" · 설계에서 마이너스였던 칸 중 검증 플러스 {int(((P.r_tr < 0) & (P.n_tr >= 80) & (P.r_te > 0)).sum())}/{int(((P.r_tr < 0) & (P.n_tr >= 80)).sum())}개")

    base = d[d.entry >= SPLIT].r.mean()
    print(f"\n■ 2. 종합 매매 방식별 한 계좌 (거래당 0.5%) · 비교 기준: 7가지 전부 다 매매 검증 평균 {base:+.3f}R")
    print(f"  {'방식':34} | {'':14} | {'':66} | 2022  2023  2024  2025  2026")
    for tf_sel, tf_name in ((("1h", "4h"), "1h+4h"), (("1h",), "1h"), (("4h",), "4h")):
        dd = d[d.tf.isin(tf_sel)]
        print(f"  ── {tf_name}")
        print(line("전부 다 매매 (비교 기준)", account(dd), base))
        rule = dd[((dd.regime == "순추세") & dd.family.isin(TREND)) | ((dd.regime == "횡보") & dd.family.isin(REVERSAL))]
        print(line("A 규칙 플레이북", account(rule), base))
        keys = set(map(tuple, good_cells[["tf", "family", "regime"]].to_numpy()))
        dsel = dd[[(t, f, r) in keys for t, f, r in zip(dd.tf, dd.family, dd.regime)]]
        print(line(f"B 데이터 플레이북 ({len(keys)}칸)", account(dsel), base))
        cf = confluence(dd)
        print(line("C 겹침 2개 이상", account(cf), base))
        cfr = cf[((cf.regime == "순추세") & cf.family.isin(TREND)) | ((cf.regime == "횡보") & cf.family.isin(REVERSAL))]
        print(line("C+A 겹침 + 장세 맞음", account(cfr), base))
        cf3 = confluence(dd, need=3)
        print(line("C 겹침 3개 이상", account(cf3), base))
    p = model(d)
    dp = d.loc[p.index].assign(p=p)
    print("  ── D 모델 (1h+4h, 해마다 다시 학습, 2020~ 만 판단 가능)")
    te = dp[dp.entry >= SPLIT]
    cal = te.groupby(pd.cut(te.p, [0, .35, .40, .45, .50, .55, .60, 1]), observed=True).r.agg(["count", lambda r: (r > 0).mean(), "mean"])
    print("     모델 확률 → 실제 승률·평균 R: " + " · ".join(f"{iv.left:.2f}~{iv.right:.2f}: {w*100:.0f}% {m:+.2f}R ({n})"
                                               for iv, (n, w, m) in cal.iterrows()))
    for th in (0.50, 0.55, 0.60):
        print(line(f"D 모델 확률 ≥ {th:.2f}", account(dp[dp.p >= th]), base))


if __name__ == "__main__":
    main()
