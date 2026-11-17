"""BTC 에서 '완성된' 엘리어트 5파 + ABC 를 규칙대로 찾아낸다 (일봉·4시간봉·1시간봉).

파동 세기는 사람마다 다르므로, 미리 정한 기계적 규칙으로만 찾는다.
  1) 지그재그 고·저점: 가격이 직전 극값에서 ATR(14) × k 이상 되돌리면 극값을 확정 (일봉 k=2.5, 4시간·1시간 k=3)
  2) 연속된 6개 꼭짓점 p0~p5 가 저-고-저-고-저-고 (상승 5파, 하락은 반대)
  3) 절대 규칙: 2파가 1파 시작점 아래로 안 감 · 3파가 1·3·5파 중 가장 짧지 않음 · 4파가 1파 고점 아래로 안 감
     + 3파 고점 > 1파 고점, 5파 고점 > 3파 고점
  4) 가이드라인 점수 (4점 만점): 2파 되돌림 38.2~78.6% · 3파 ≥ 1파 × 1.382 · 4파 되돌림 23.6~50% · 5파 = 1파 × 0.618~1.618
  5) 완성: 5파 뒤 꼭짓점 A(저)·B(고, 5파 고점 아래)·C(저, A 아래) 가 이어지고, C 까지 5파 전체의 38.2% 이상 되돌림
가장 최근의 '점수 3점 이상' 완성 패턴을 봉마다 하나씩 고른다.

사용:  python -m smc.elliott_scan
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .data import ARCHIVE, load_csv, resample

TFS = {"1D": 2.5, "4h": 3.0, "1h": 3.0}


def bars(tf: str) -> pd.DataFrame:
    h1 = load_csv(ARCHIVE / "BTCUSDT_1h.csv.gz")
    d = h1 if tf == "1h" else resample(h1, tf)
    d = d.reset_index(drop=True)
    pc = d.close.shift(1)
    tr = pd.concat([d.high - d.low, (d.high - pc).abs(), (d.low - pc).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    return d


def zigzag(d: pd.DataFrame, k: float) -> list[tuple[int, float, int]]:
    """[(봉 위치, 가격, +1 고점 / -1 저점)]"""
    h, l, a = d.high.to_numpy(), d.low.to_numpy(), d.atr.to_numpy()
    piv, trend = [], 0
    hi_i, lo_i = 0, 0
    for i in range(1, len(d)):
        if h[i] > h[hi_i]:
            hi_i = i
        if l[i] < l[lo_i]:
            lo_i = i
        if trend >= 0 and h[hi_i] - l[i] >= k * a[hi_i] and hi_i < i:
            if trend == 1 or not piv or piv[-1][2] != 1:
                piv.append((hi_i, h[hi_i], 1))
            trend, lo_i = -1, i
        elif trend <= 0 and h[i] - l[lo_i] >= k * a[lo_i] and lo_i < i:
            if trend == -1 or not piv or piv[-1][2] != -1:
                piv.append((lo_i, l[lo_i], -1))
            trend, hi_i = 1, i
    # 같은 종류가 연속되면 더 극단적인 것만
    out = []
    for p in piv:
        if out and out[-1][2] == p[2]:
            if (p[2] == 1 and p[1] > out[-1][1]) or (p[2] == -1 and p[1] < out[-1][1]):
                out[-1] = p
            continue
        out.append(p)
    return out


def find(d: pd.DataFrame, piv) -> list[dict]:
    found = []
    for s in range(len(piv) - 8):
        seq = piv[s:s + 9]
        side = -seq[0][2]                                   # 시작이 저점이면 상승 5파
        p = [x[1] * side for x in seq]                      # 하락은 뒤집어서 같은 규칙
        w1, w3, w5 = p[1] - p[0], p[3] - p[2], p[5] - p[4]
        if not (p[2] > p[0] and p[4] > p[1] and p[3] > p[1] and p[5] > p[3]):
            continue
        if w3 < min(w1, w5):
            continue
        r2 = (p[1] - p[2]) / w1
        r4 = (p[3] - p[4]) / w3
        score = int(0.382 <= r2 <= 0.786) + int(w3 >= 1.382 * w1) + int(0.236 <= r4 <= 0.5) + int(0.618 <= w5 / w1 <= 1.618)
        a_, b_, c_ = p[6], p[7], p[8]
        total = p[5] - p[0]
        done = b_ < p[5] and c_ < a_ and (p[5] - c_) >= 0.382 * total
        if score >= 3 and done:
            found.append(dict(side=side, piv=[(int(x[0]), float(x[1])) for x in seq], score=score,
                              r2=r2, w3_w1=w3 / w1, r4=r4, w5_w1=w5 / w1, retr=(p[5] - c_) / total,
                              start=str(d.time[seq[0][0]]), end=str(d.time[seq[8][0]])))
    return found


def main():
    out = {}
    for tf, k in TFS.items():
        d = bars(tf)
        piv = zigzag(d, k)
        f = find(d, piv)
        print(f"■ {tf}: 꼭짓점 {len(piv)}개 · 규칙+점수3↑+ABC 완성 패턴 {len(f)}개")
        for x in f[-4:]:
            print(f"   {'상승' if x['side'] > 0 else '하락'} {x['start'][:16]} ~ {x['end'][:16]} · 점수 {x['score']}/4 · 2파 {x['r2']*100:.0f}%"
                  f" · 3파/1파 {x['w3_w1']:.2f} · 4파 {x['r4']*100:.0f}% · 5파/1파 {x['w5_w1']:.2f} · ABC 되돌림 {x['retr']*100:.0f}%")
        if f:
            best = f[-1]
            lo, hi = best["piv"][0][0], best["piv"][-1][0]
            pad = max(5, (hi - lo) // 8)
            w = d.iloc[max(0, lo - pad):min(len(d), hi + pad)]
            out[tf] = dict(best, candles=[[str(t), o, h, l, c] for t, o, h, l, c in zip(w.time, w.open, w.high, w.low, w.close)],
                           times=[str(d.time[i]) for i, _ in best["piv"]])
    with open("/tmp/elliott_found.json", "w") as fh:
        json.dump(out, fh, ensure_ascii=False)


if __name__ == "__main__":
    main()
