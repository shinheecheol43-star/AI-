"""강의(쉽알남 '비밀 생존 전략' 1·2·5장)의 규칙을 코드로 옮긴 탐지기.

강의에서 '경험에 따른 주관적 판단'으로 남겨 둔 부분은 아래 Params의 숫자로 고정했다.
숫자를 바꿔 가며 백테스트하면 어떤 기준이 나은지 비교할 수 있다.

미래 참조 금지: 모든 신호는 '패턴의 마지막 캔들이 마감된 시점'(confirm 인덱스)부터 쓸 수 있다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Params:
    # 공통
    atr_len: int = 14
    doji_atr: float = 0.10       # 몸통이 ATR의 이 비율보다 작으면 도지로 보고 제외 (1장 Gap 규칙)
    # 1장 오더블럭: 두 번째 캔들 몸통이 첫 캔들 몸통의 몇 배 이상이어야 하나
    ob_body_ratio: float = 2.0
    # 2장 FVG: 가운데 캔들 몸통이 앞뒤 캔들 몸통의 몇 배 이상이어야 하나 (강의: 최소 2~3배)
    fvg_body_ratio: float = 2.0
    # 유동성 흡수(Sweep) 판정: 패턴의 꼬리가 직전 N개 캔들의 저점/고점을 깼는가
    sweep_lookback: int = 24
    # 5장 거짓 돌파: 스윙 고/저점 판정 폭(좌우 k개), 이탈 후 복귀까지 허용 캔들 수
    pivot_k: int = 5
    reclaim_within: int = 5
    level_max_age: int = 300     # 이보다 오래된 지지/저항은 쓰지 않음


@dataclass
class Zone:
    kind: str            # 'OB' | 'FVG'
    side: int            # +1 상승형(매수), -1 하락형(매도)
    confirm: int         # 이 인덱스 캔들이 마감되면 존재가 확정됨
    top: float
    bottom: float
    stop: float          # 강의의 '첫 번째 기준' 손절선 (패턴 캔들들의 꼬리 끝)
    sweep: bool = False  # 유동성 흡수 구간에서 생겼는가 (강의: 신뢰도 상승 조건)
    meta: dict = field(default_factory=dict)

    @property
    def entry(self) -> float:
        """존에 처음 닿는 가격(상승형은 윗변, 하락형은 아랫변)에 지정가 진입."""
        return self.top if self.side > 0 else self.bottom


def atr(df: pd.DataFrame, n: int = 14) -> np.ndarray:
    h, l, c = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def _swept(df: pd.DataFrame, i_first: int, low: float, high: float, side: int, lookback: int) -> bool:
    """패턴 직전 lookback개 캔들의 최저점(상승형)/최고점(하락형)을 패턴 꼬리가 깼는가."""
    start = max(0, i_first - lookback)
    if start >= i_first:
        return False
    if side > 0:
        return low < df["low"].to_numpy()[start:i_first].min()
    return high > df["high"].to_numpy()[start:i_first].max()


def find_order_blocks(df: pd.DataFrame, p: Params = Params()) -> list[Zone]:
    """1장 오더블럭 (2캔들형).

    상승형: 음봉 → 양봉. 양봉 몸통 ≥ 음봉 몸통 × ob_body_ratio, 양봉 종가가 음봉 고가 위에서 마감.
    존 = 음봉의 몸통 (강의 Q&A: '저는 캔들의 몸통 구간만 오더블럭으로 식별')
    손절 = 두 캔들의 최저점 (강의: 음봉→양봉이면 두 캔들의 최저점)
    하락형은 반대.
    """
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = atr(df, p.atr_len)
    zones = []
    for i in range(1, len(df)):
        j = i - 1
        b1, b2 = abs(c[j] - o[j]), abs(c[i] - o[i])
        if b1 < p.doji_atr * a[j] or b2 < p.ob_body_ratio * b1:
            continue
        lo, hi = min(l[j], l[i]), max(h[j], h[i])
        if c[j] < o[j] and c[i] > o[i] and c[i] > h[j]:
            side, top, bot, stop = 1, o[j], c[j], lo
        elif c[j] > o[j] and c[i] < o[i] and c[i] < l[j]:
            side, top, bot, stop = -1, c[j], o[j], hi
        else:
            continue
        zones.append(Zone("OB", side, i, top, bot, stop, _swept(df, j, lo, hi, side, p.sweep_lookback)))
    return zones


def find_fvgs(df: pd.DataFrame, p: Params = Params()) -> list[Zone]:
    """2장 FVG (3캔들형).

    상승형: 1번 고가 < 3번 저가 (빈 공간), 2번은 몸통 긴 양봉, 2번 몸통 ≥ 1·3번 몸통 × fvg_body_ratio.
    존 = 1번 고가 ~ 3번 저가
    손절 = 세 캔들의 최저점 (강의 손절 첫 번째 기준)
    하락형은 반대.
    """
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = atr(df, p.atr_len)
    zones = []
    for i in range(2, len(df)):
        m = i - 1
        bm = abs(c[m] - o[m])
        # 앞뒤 캔들이 도지면 비율이 부풀려지므로 ATR 기준 최소 몸통을 바닥값으로 쓴다
        floor = p.doji_atr * a[m]
        side_bodies = max(abs(c[i - 2] - o[i - 2]), abs(c[i] - o[i]), floor)
        if bm < p.fvg_body_ratio * side_bodies:
            continue
        lo, hi = l[i - 2:i + 1].min(), h[i - 2:i + 1].max()
        if c[m] > o[m] and l[i] > h[i - 2]:
            side, top, bot, stop = 1, l[i], h[i - 2], lo
        elif c[m] < o[m] and h[i] < l[i - 2]:
            side, top, bot, stop = -1, l[i - 2], h[i], hi
        else:
            continue
        zones.append(Zone("FVG", side, i, top, bot, stop, _swept(df, i - 2, lo, hi, side, p.sweep_lookback)))
    return zones


def pivots(df: pd.DataFrame, k: int) -> tuple[list[tuple[int, int, float]], list[tuple[int, int, float]]]:
    """스윙 고점/저점. (피벗 인덱스, 확정 인덱스 = 피벗 + k, 가격) 목록."""
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    # 좌우 k개 창의 최고/최저와 같은 캔들. 양 끝 k개는 창이 모자라 NaN → 제외
    hmax = pd.Series(h).rolling(2 * k + 1, center=True).max().to_numpy()
    lmin = pd.Series(l).rolling(2 * k + 1, center=True).min().to_numpy()
    highs = [(int(j), int(j) + k, float(h[j])) for j in np.flatnonzero(h == hmax)]
    lows = [(int(j), int(j) + k, float(l[j])) for j in np.flatnonzero(l == lmin)]
    return highs, lows


@dataclass
class FakeOut:
    side: int        # +1: 지지선 하향 이탈 후 복귀 → 매수, -1: 저항선 상향 이탈 후 복귀 → 매도
    confirm: int     # 복귀 캔들(종가로 라인 안쪽 마감) 인덱스 = 진입 시점
    level: float     # 지지/저항 기준 라인
    entry: float     # 복귀 캔들 종가
    stop: float      # 이탈 구간의 최저점(최고점) — 강의: 거짓 돌파 꼬리 끝 바로 아래
    targets: list    # 1차·2차 익절 후보 (반대편 스윙 고/저점, 가까운 순)
    trap: bool       # 이탈 구간이 2캔들 이상 → 함정(Trap), 1캔들 → 거짓 돌파(Fake out)


def find_fakeouts(df: pd.DataFrame, p: Params = Params()) -> list[FakeOut]:
    """5장 전략 A(확인 매매).

    지지선 = 확정된 스윙 저점. 가격이 그 아래로 내려갔다가(꼬리든 종가든)
    reclaim_within 캔들 안에 종가로 다시 위에서 마감하면 그 종가에 매수.
    손절 = 이탈 구간 최저점, 익절 = 위쪽 스윙 고점들(1차, 2차).
    저항선은 반대로 매도.
    """
    h, l, c = (df[k].to_numpy() for k in ("high", "low", "close"))
    highs, lows = pivots(df, p.pivot_k)
    out: list[FakeOut] = []
    for side, levels, opp in ((1, lows, highs), (-1, highs, lows)):
        used = set()
        for idx, (pj, pconf, lvl) in enumerate(levels):
            # 이 라인이 '살아 있는' 구간에서 첫 이탈을 찾는다
            end = min(len(df), pconf + p.level_max_age)
            i = pconf + 1
            while i < end:
                broke = l[i] < lvl if side > 0 else h[i] > lvl
                if not broke:
                    i += 1
                    continue
                # 이탈 시작. reclaim_within 안에 복귀 종가가 나오는지
                ext = l[i] if side > 0 else h[i]
                for r in range(i, min(len(df), i + p.reclaim_within)):
                    ext = min(ext, l[r]) if side > 0 else max(ext, h[r])
                    back = c[r] > lvl if side > 0 else c[r] < lvl
                    if back:  # 같은 캔들에서 꼬리만 찍고 복귀해도 거짓 돌파
                        if r in used:
                            break
                        tg = sorted(
                            {pr for (_, cf, pr) in opp if cf <= r and r - cf <= p.level_max_age
                             and ((pr > c[r]) if side > 0 else (pr < c[r]))},
                            reverse=side < 0,
                        )
                        if tg:
                            used.add(r)
                            out.append(FakeOut(side, r, lvl, c[r], ext, tg[:2], trap=r > i))
                        break
                break  # 라인은 한 번 깨지면 소멸 (성공이든 실패든)
    return sorted(out, key=lambda f: f.confirm)
