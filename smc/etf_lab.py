"""ETF 전략 대량 비교: 반도체(SOXX)에 맞는 전략이 있는지, 같은 규칙이 SMH·QQQ 에서도 통하는지 본다.

판정 기준 (결과를 보기 전에 정함)
  1. 설계 구간(~2015)과 검증 구간(2016~) 모두 샤프 비율이 그냥 보유보다 높을 것
  2. SMH(다른 반도체 ETF)와 QQQ(나스닥)에서도 전체 기간 샤프가 그냥 보유보다 높을 것
  3. 통과한 전략에 대해서만, 최대 낙폭이 −35% 이내가 되는 레버리지(1~3배)를 찾는다
신호는 그날 종가(또는 시가)까지의 정보로만 정하고, 그다음 수익에 적용한다.
레버리지는 매일 맞추는 방식(레버리지 ETF와 같음). 비용: 매매 한쪽 0.05%, 빌린 돈 연 5%, 공매도 연 1%.

사용:  python -m smc.etf_lab
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .research import rsi
from .stock_swing import fetch

COST, BORROW, SHORT_FEE = 0.0005, 0.05, 0.01
SPLIT = pd.Timestamp("2016-01-01", tz="UTC")
LEVS = (1, 2, 3)


def load(sym: str, vix: pd.DataFrame, vix3m: pd.DataFrame, qqq: pd.DataFrame) -> pd.DataFrame:
    d = fetch(sym)
    d = d[d.close > 0].set_index("time")
    d["vix"] = vix.set_index("time").close.reindex(d.index).ffill()
    d["vix3m"] = vix3m.set_index("time").close.reindex(d.index).ffill()
    d["qqq"] = qqq.set_index("time").close.reindex(d.index).ffill()
    return d


# ---------------------------------------------------------------- 전략: (보유 비중 시리즈, 수익 종류)
# 비중은 그날 종가 기준으로 정해지고 다음 날 수익에 적용된다. 수익 종류: cc 종가→종가, on 종가→다음 날 시가, id 시가→종가
def strategies(d: pd.DataFrame) -> dict:
    c, h, l = d.close, d.high, d.low
    sma = lambda n: c.rolling(n).mean()
    ema = lambda n: c.ewm(span=n, adjust=False).mean()
    up200 = c > sma(200)
    ibs = (c - l) / (h - l).replace(0, np.nan)
    r2 = rsi(c, 2)
    dn3 = (c < c.shift(1)) & (c.shift(1) < c.shift(2)) & (c.shift(2) < c.shift(3))
    month = d.index.tz_localize(None).to_period("M")
    k = pd.Series(1, index=d.index).groupby(month).cumsum()
    left = pd.Series(1, index=d.index)[::-1].groupby(month[::-1]).cumsum()[::-1]
    rs = (c / d.qqq)
    S = {
        "보유": (pd.Series(1.0, index=d.index), "cc"),
        # 추세
        "추세 200일선": (up200.astype(float), "cc"),
        "추세 50/200 교차": ((sma(50) > sma(200)).astype(float), "cc"),
        "추세 EMA20>EMA50 & 200일선": (((ema(20) > ema(50)) & up200).astype(float), "cc"),
        "추세 12개월 모멘텀": ((c / c.shift(252) > 1).astype(float), "cc"),
        "추세 6개월 모멘텀": ((c / c.shift(126) > 1).astype(float), "cc"),
        "돌파 20/10 (단기 터틀)": (_breakout(c, h, l, 20, 10), "cc"),
        # 역발상
        "역발상 RSI2<10 (200일선 위)": (_hold_until(up200 & (r2 < 10), c > sma(5)), "cc"),
        "역발상 IBS<0.2 다음날": (((ibs < 0.2)).astype(float), "cc"),
        "역발상 IBS<0.2 & 200일선": (((ibs < 0.2) & up200).astype(float), "cc"),
        "역발상 3일 연속 하락": (_hold_until(dn3, c > c.shift(1)), "cc"),
        # 시간대
        "밤만 보유 (종가→시가)": (pd.Series(1.0, index=d.index), "on"),
        "낮만 보유 (시가→종가)": (pd.Series(1.0, index=d.index), "id"),
        "밤만 보유 & 200일선": (up200.astype(float), "on"),
        # 계절성
        "월말·월초 (마지막 1일 + 첫 3일)": (((left == 2) | (k <= 2)).astype(float), "cc"),
        "11~4월만 보유": (pd.Series(d.index.month.isin([11, 12, 1, 2, 3, 4]).astype(float), index=d.index), "cc"),
        # 공포지수
        "VIX < 20": ((d.vix < 20).astype(float), "cc"),
        "VIX < 50일 평균": ((d.vix < d.vix.rolling(50).mean()).astype(float), "cc"),
        "VIX 정상 구조 (VIX < VIX3M)": ((d.vix < d.vix3m).astype(float), "cc"),
        "VIX 정상 구조 & 200일선": (((d.vix < d.vix3m) & up200).astype(float), "cc"),
        # 상대 강도
        "상대강도 (나스닥 대비 100일선 위)": ((rs > rs.rolling(100).mean()).astype(float), "cc"),
        # 롱·숏
        "롱숏 200일선 (아래면 숏)": (np.where(up200, 1.0, -1.0) * c.rolling(200).count().ge(200), "cc"),
        "숏 200일선 아래만": ((~up200 & c.rolling(200).count().ge(200)).astype(float) * -1, "cc"),
    }
    return {name: (pd.Series(np.asarray(pos, dtype=float), index=d.index).fillna(0.0), kind) for name, (pos, kind) in S.items()}


def _breakout(c, h, l, n_in, n_out):
    hi, lo = h.rolling(n_in).max().shift(1), l.rolling(n_out).min().shift(1)
    s = pd.Series(np.nan, index=c.index)
    s[c > hi] = 1.0
    s[c < lo] = 0.0
    return s.ffill().fillna(0.0)


def _hold_until(enter: pd.Series, leave: pd.Series) -> pd.Series:
    out, held = [], 0.0
    for e, x in zip(enter.fillna(False), leave.fillna(False)):
        if held == 0 and e:
            held = 1.0
        elif held == 1 and x:
            held = 0.0
        out.append(held)
    return pd.Series(out, index=enter.index)


def returns(d: pd.DataFrame, pos: pd.Series, kind: str, lev: float) -> pd.Series:
    if kind == "cc":
        r, e = d.close.pct_change(), pos.shift(1)
        turnover = pos.diff().abs().shift(1)
    elif kind == "on":
        r, e = d.open / d.close.shift(1) - 1, pos.shift(1)
        turnover = 2 * e.abs()                       # 매일 종가에 사고 시가에 판다
    else:
        r, e = d.close / d.open - 1, pos.shift(1)
        turnover = 2 * e.abs()                       # 매일 시가에 사고 종가에 판다
    e, r, turnover = e.fillna(0), r.fillna(0), turnover.fillna(0)
    x = e * lev
    cost = turnover * lev * COST + (x.abs() - 1).clip(lower=0) * BORROW / 252 + (-x).clip(lower=0) * SHORT_FEE / 252
    return (x * r - cost).clip(lower=-0.999)


def stats(r: pd.Series) -> dict:
    eq = (1 + r).cumprod()
    yrs = (r.index[-1] - r.index[0]).days / 365.25
    sd = r.std()
    return {"cagr": eq.iloc[-1] ** (1 / yrs) - 1, "mdd": (eq / eq.cummax() - 1).min(),
            "sharpe": r.mean() / sd * np.sqrt(252) if sd > 0 else 0.0}


def evaluate(d: pd.DataFrame, start) -> dict:
    out = {}
    for name, (pos, kind) in strategies(d).items():
        row = {"time_in": pos[d.index >= start].abs().mean()}
        for lev in LEVS:
            r = returns(d, pos, kind, lev)
            r = r[r.index >= start]
            row[lev] = {"all": stats(r), "design": stats(r[r.index < SPLIT]), "test": stats(r[r.index >= SPLIT])}
        out[name] = row
    return out


def main():
    vix, vix3m, qqq = fetch("^VIX"), fetch("^VIX3M"), fetch("QQQ")
    data = {s: load(s, vix, vix3m, qqq) for s in ("SOXX", "SMH", "QQQ")}
    start = pd.Timestamp("2002-08-01", tz="UTC")                   # SOXX 200일선·12개월이 계산되는 시점
    res = {s: evaluate(d, start) for s, d in data.items()}
    print(f"비교 구간 {start:%Y-%m-%d} ~ {data['SOXX'].index[-1]:%Y-%m-%d} · 설계 ~2015 · 검증 2016~ · 비용 매매 {COST:.2%}·차입 연 {BORROW:.0%}\n")
    base = {s: res[s]["보유"][1] for s in res}
    print(f"{'전략 (SOXX 1배)':32} {'보유율':>5} | {'연평균':>7} {'낙폭':>7} {'샤프':>5} | {'설계샤프':>7} {'검증샤프':>7} | {'SMH샤프':>7} {'QQQ샤프':>7} | 판정")
    passed = []
    for name, row in res["SOXX"].items():
        s1 = row[1]
        ok = (s1["design"]["sharpe"] > base["SOXX"]["design"]["sharpe"] and s1["test"]["sharpe"] > base["SOXX"]["test"]["sharpe"]
              and res["SMH"][name][1]["all"]["sharpe"] > base["SMH"]["all"]["sharpe"]
              and res["QQQ"][name][1]["all"]["sharpe"] > base["QQQ"]["all"]["sharpe"])
        if ok and name != "보유":
            passed.append(name)
        a = s1["all"]
        print(f"{name:32} {row['time_in']*100:4.0f}% | {a['cagr']*100:+6.1f}% {a['mdd']*100:6.1f}% {a['sharpe']:5.2f} |"
              f" {s1['design']['sharpe']:7.2f} {s1['test']['sharpe']:7.2f} | {res['SMH'][name][1]['all']['sharpe']:7.2f}"
              f" {res['QQQ'][name][1]['all']['sharpe']:7.2f} | {'통과' if ok and name != '보유' else ''}")
    print(f"\n기준선 샤프 (보유): SOXX 설계 {base['SOXX']['design']['sharpe']:.2f} / 검증 {base['SOXX']['test']['sharpe']:.2f}"
          f" · SMH {base['SMH']['all']['sharpe']:.2f} · QQQ {base['QQQ']['all']['sharpe']:.2f}")
    print("\n■ 통과한 전략의 레버리지별 결과 (SOXX)")
    print(f"{'전략':32} {'배':>2} | {'연평균':>7} {'낙폭':>7} {'효율':>5} | {'설계 연평균':>9} {'낙폭':>7} | {'검증 연평균':>9} {'낙폭':>7}")
    for name in ["보유"] + passed:
        for lev in LEVS:
            s = res["SOXX"][name][lev]
            a, x, y = s["all"], s["design"], s["test"]
            print(f"{name:32} {lev:2} | {a['cagr']*100:+6.1f}% {a['mdd']*100:6.1f}% {a['cagr']/-a['mdd']:5.2f} |"
                  f" {x['cagr']*100:+8.1f}% {x['mdd']*100:6.1f}% | {y['cagr']*100:+8.1f}% {y['mdd']*100:6.1f}%")
        print()
    d = data["SOXX"]
    print(f"■ 지금 ({d.index[-1]:%Y-%m-%d}) SOXX {d.close.iat[-1]:.2f} · VIX {d.vix.iat[-1]:.2f} · VIX3M {d.vix3m.iat[-1]:.2f}")
    for name in passed:
        pos, kind = strategies(d)[name]
        print(f"  {name:32} → {'보유' if pos.iat[-1] > 0 else '숏' if pos.iat[-1] < 0 else '현금'}")


if __name__ == "__main__":
    main()
