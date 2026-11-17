"""엘리어트 2파 구간에서 반전 캔들을 확인하고 사면 어떤가 (BTC 일봉·4시간봉, 롱·숏).

실시간으로 할 수 있는 순서만 쓴다. 규칙은 결과를 보기 전에 정했다. (롱 기준, 숏은 가격을 뒤집어 같은 규칙)
  1) 지그재그(ATR×k) 로 1파 고점이 '확정된 봉' 이후부터 감시 (확정 전 정보 사용 안 함)
  2) 2파 구간: 1파 고점에서 1파 길이의 38.2% ~ 78.6% 아래. 1파 시작점이 깨지면 그 구조는 끝
  3) 구간 안에서 처음 나온 신호 캔들의 종가에 진입 (구조 하나당 한 번)
     망치형    : 아래꼬리 ≥ 몸통×2, 윗꼬리 ≤ 봉 길이의 30%, 종가가 봉 위쪽 1/3
     상승 장악형: 앞 봉 음봉, 이번 봉 양봉, 이번 몸통이 앞 몸통을 덮음
     샛별형    : 2봉 전 음봉 몸통 ≥ ATR×0.6, 1봉 전 몸통 ≤ ATR×0.3, 이번 양봉 종가 > 2봉 전 몸통 중간
     비교      : 신호 없이 구간에 처음 들어온 봉 종가
  손절: 신호 캔들 저점 − 0.1 ATR  또는  1파 시작점
  목표: 2파 저점(그때까지 최저가) + 1파 × 1.618 (3파 목표). 최대 보유 120봉, 비용 왕복 0.1%
채점: 2021년까지 / 2022년 이후, 롱·숏 따로. R 과 '전액 투자 시 수익률' 둘 다

사용:  python -m smc.elliott_candle
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .elliott_scan import bars

FEE = 0.001
SPLIT = pd.Timestamp("2022-01-01", tz="UTC")
TFS = {"1D": 2.5, "4h": 3.0}
PATTERNS = ("망치형", "상승 장악형", "샛별형", "아무 캔들(비교)")


def zigzag_confirmed(d: pd.DataFrame, k: float):
    """[(꼭짓점 봉, 가격, +1/-1, 확정 봉)]"""
    h, l, a = d.high.to_numpy(), d.low.to_numpy(), d.atr.to_numpy()
    piv, trend, hi_i, lo_i = [], 0, 0, 0
    for i in range(1, len(d)):
        if h[i] > h[hi_i]:
            hi_i = i
        if l[i] < l[lo_i]:
            lo_i = i
        if trend >= 0 and hi_i < i and h[hi_i] - l[i] >= k * a[hi_i]:
            piv.append((hi_i, h[hi_i], 1, i)); trend, lo_i = -1, i
        elif trend <= 0 and lo_i < i and h[i] - l[lo_i] >= k * a[lo_i]:
            piv.append((lo_i, l[lo_i], -1, i)); trend, hi_i = 1, i
    out = []
    for p in piv:
        if out and out[-1][2] == p[2]:
            if (p[2] == 1 and p[1] > out[-1][1]) or (p[2] == -1 and p[1] < out[-1][1]):
                out[-1] = p
            continue
        out.append(p)
    return out


def signal(kind, o, h, l, c, a, i):
    body = abs(c[i] - o[i]); rng = h[i] - l[i]
    if rng <= 0:
        return False
    if kind == "망치형":
        lw = min(o[i], c[i]) - l[i]; uw = h[i] - max(o[i], c[i])
        return lw >= 2 * max(body, 1e-9) and uw <= 0.3 * rng and (c[i] - l[i]) >= rng * 2 / 3
    if kind == "상승 장악형":
        return c[i - 1] < o[i - 1] and c[i] > o[i] and c[i] >= o[i - 1] and o[i] <= c[i - 1]
    if kind == "샛별형":
        return (o[i - 2] - c[i - 2] >= 0.6 * a[i - 2] and abs(c[i - 1] - o[i - 1]) <= 0.3 * a[i - 1]
                and c[i] > o[i] and c[i] > (o[i - 2] + c[i - 2]) / 2)
    return True


def run(tf: str, k: float):
    d = bars(tf)
    piv = zigzag_confirmed(d, k)
    rows = []
    for side in (1, -1):
        s = side
        o, c = (d.open * s).to_numpy(), (d.close * s).to_numpy()
        h = (d.high if s > 0 else -d.low).to_numpy()
        l = (d.low if s > 0 else -d.high).to_numpy()
        a = d.atr.to_numpy()
        trend = (np.sign(d.close - d.close.ewm(span=200, adjust=False).mean()) * s).to_numpy()
        for n in range(1, len(piv)):
            (i0, p0, t0, _), (i1, p1, t1, conf1) = piv[n - 1], piv[n]
            if t0 != -s or t1 != s:                         # 롱: 저점(0) → 고점(1)
                continue
            P0, P1 = p0 * s, p1 * s
            w1 = P1 - P0
            if w1 <= 0:
                continue
            z_hi, z_lo = P1 - 0.382 * w1, P1 - 0.786 * w1
            for kind in PATTERNS:
                lowest = P1
                for i in range(conf1, min(len(d) - 1, conf1 + 120)):
                    lowest = min(lowest, l[i])
                    if l[i] <= P0 or h[i] > P1:              # 1파 시작점 깨짐 / 2파 없이 신고점 → 구조 끝
                        break
                    if not (z_lo <= c[i] <= z_hi) and not (z_lo <= l[i] <= z_hi):
                        continue
                    if i < 2 or not signal(kind, o, h, l, c, a, i):
                        continue
                    entry = c[i]
                    tgt = lowest + 1.618 * w1
                    for stop_mode, stop in (("신호 캔들 저점", l[i] - 0.1 * a[i]), ("1파 시작점", P0)):
                        if stop >= entry or tgt <= entry:
                            continue
                        dist = entry - stop
                        ex, why = None, "시간"
                        for j in range(i + 1, min(len(d), i + 121)):
                            if l[j] <= stop:
                                ex, why = min(stop, o[j]), "손절"; break
                            if h[j] >= tgt:
                                ex, why = tgt, "목표"; break
                        if ex is None:
                            j = min(len(d) - 1, i + 120); ex = c[j]
                        ret = (ex - entry) / abs(entry) - FEE
                        rows.append(dict(tf=tf, side=s, kind=kind, stop=stop_mode, time=d.time[i], r=ret / (dist / abs(entry)),
                                         ret=ret, stop_pct=dist / abs(entry), why=why, exit=d.time[j], trend=trend[i] > 0,
                                         struct=n))
                    break
    return pd.DataFrame(rows)


def main():
    R = pd.concat([run(tf, k) for tf, k in TFS.items()], ignore_index=True)
    print("엘리어트 2파 구간 반전 캔들 진입 · BTC 2017~2026 · 비용 포함\n")
    for tf in TFS:
        for side in (1, -1):
            print(f"■ {tf} {'롱 (상승 1파 뒤 2파)' if side > 0 else '숏 (하락 1파 뒤 2파)'}")
            print(f"  {'캔들':12} {'손절':10} | {'건수':>4} {'승률':>4} {'평균R':>6} {'전액 평균':>8} {'손절폭':>6} | {'~2021 R':>8} {'2022~ R':>8} | 목표/손절/시간")
            for kind in PATTERNS:
                for stop_mode in ("신호 캔들 저점", "1파 시작점"):
                    g = R[(R.tf == tf) & (R.side == side) & (R.kind == kind) & (R.stop == stop_mode)]
                    if not len(g):
                        continue
                    a_, b_ = g[g.time < SPLIT], g[g.time >= SPLIT]
                    print(f"  {kind:12} {stop_mode:10} | {len(g):4} {(g.ret > 0).mean()*100:3.0f}% {g.r.mean():+6.2f} {g.ret.mean()*100:+7.1f}% {g.stop_pct.median()*100:5.1f}% |"
                          f" {a_.r.mean():+8.2f} {b_.r.mean():+8.2f} | {(g.why == '목표').sum()}/{(g.why == '손절').sum()}/{(g.why == '시간').sum()}")
            print()


if __name__ == "__main__":
    main()
