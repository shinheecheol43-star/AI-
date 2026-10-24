"""강의 1장 '오더블럭'을 강의안 그대로 옮긴 판정·매매 규칙과 검증 리포트.

강의안에서 가져온 규칙
  식별   : 반대색 캔들 → 장대 캔들. 장대 캔들 몸통이 반대색 캔들 몸통의 2배 이상(Gap).
           첫 캔들이 도지처럼 몸통이 기형적으로 작으면 제외.
           존 = 반대색 캔들의 몸통 (Q&A: '캔들의 몸통 구간만 오더블럭으로 식별')
  진입   : 오더블럭 구간에 닿으면 진입, 닿지 않으면 진입하지 않음
  손절 1 : 패턴 캔들들의 꼬리 끝. 양봉→음봉→양봉(3캔들)이면 세 캔들의 최저점
  손절 2 : 꼬리 끝을 벗어나 '봉 마감'하면 손절
  익절   : 파동 고점 탈환 시 1/2 익절, 나머지는 평단에 스탑로스(교과서적 방법).
           반대 방향 오더블럭이 나오면 남은 물량 종료.
  신뢰도 : ① 유동성 흡수(의미 있는 저점·고점 갱신) ② 구조물(FVG 등) ③ Gap
           강의 3절: 급등 단계에서 구조물 돌파(BOS)와 FVG가 발생
           Q&A: 모든 타임프레임을 확인하고 겹치는 구간에서 진입

사용:  python -m smc.ob_lecture            (BTC/USD 1시간봉 + 4시간봉, Bybit 수수료)
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .data import DEFAULT_CSV, load, resample
from .detectors import atr, find_fvgs, pivots

MAKER, TAKER = 0.0002, 0.00055  # Bybit USDT 무기한: 지정가 0.02%, 시장가 0.055%


@dataclass
class OB:
    side: int
    first: int          # 패턴 첫 캔들 (반대색 캔들, 3캔들형이면 그 앞 캔들)
    impulse: int        # 장대 캔들
    confirm: int        # 태그 판정까지 끝나 진입 가능한 첫 캔들 (미래 참조 방지)
    top: float
    bottom: float
    stop: float
    three: bool = False
    tags: dict = field(default_factory=dict)

    @property
    def entry(self):
        return self.top if self.side > 0 else self.bottom


def find(df: pd.DataFrame, ratio: float = 2.0, doji: float = 0.10, strict_close: bool = False,
         pivot_k: int = 5, sweep_age: int = 120) -> list[OB]:
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = atr(df)
    n = len(c)
    ph, pl = pivots(df, pivot_k)
    fvg_mid = {(z.side, z.confirm - 1) for z in find_fvgs(df)}  # FVG 가운데 캔들 = 장대 캔들인가
    out = []
    for i in range(1, n):
        j = i - 1
        bj, bi = abs(c[j] - o[j]), abs(c[i] - o[i])
        if bj < doji * a[j] or bi < ratio * bj:
            continue
        if c[j] < o[j] and c[i] > o[i]:
            s = 1
        elif c[j] > o[j] and c[i] < o[i]:
            s = -1
        else:
            continue
        if strict_close and not (c[i] > h[j] if s > 0 else c[i] < l[j]):
            continue
        top, bot = max(o[j], c[j]), min(o[j], c[j])
        # 3캔들형: 반대색 캔들 앞이 장대 캔들과 같은 색이면 세 캔들로 본다 (양봉→음봉→양봉)
        k = j - 1
        three = k >= 0 and ((c[k] > o[k]) if s > 0 else (c[k] < o[k]))
        first = k if three else j
        lo, hi = l[first:i + 1].min(), h[first:i + 1].max()
        stop = lo if s > 0 else hi

        # ① 유동성 흡수: 패턴 또는 직전 3캔들의 꼬리가 가장 최근 확정 스윙 저점(고점)을 갱신했는가
        #    (강의 4쪽 그림: 손절 물량을 쓸어낸 장대 음봉 직후에 오더블럭이 생김)
        w0 = max(0, first - 3)
        swept_px = l[w0:i + 1].min() if s > 0 else h[w0:i + 1].max()
        levels = [lvl for (pj, pc, lvl) in (pl if s > 0 else ph) if pc <= w0 and w0 - pj <= sweep_age]
        sweep = bool(levels) and ((swept_px < levels[-1]) if s > 0 else (swept_px > levels[-1]))
        # ② 구조물: 장대 캔들이 FVG를 만들었는가 (FVG는 다음 캔들 마감에 확정)
        fvg = (s, i) in fvg_mid
        # 급등 단계의 BOS: 장대 캔들부터 2캔들 안에 직전 스윙 고점(저점)을 종가로 돌파
        opp = ph if s > 0 else pl
        last = next((lvl for (pj, pc, lvl) in reversed(opp) if pc <= i), None)
        bos_at = None
        if last is not None:
            for t in range(i, min(n, i + 3)):
                if (c[t] > last) if s > 0 else (c[t] < last):
                    bos_at = t
                    break
        confirm = max(i + (1 if fvg else 0), bos_at if bos_at is not None else i)
        out.append(OB(s, first, i, confirm, top, bot, stop, three,
                      {"sweep": sweep, "fvg": fvg, "bos": bos_at is not None}))
    return out


def tag_htf(obs: list[OB], df: pd.DataFrame, df_htf: pd.DataFrame, max_wait_htf: int = 24) -> None:
    """상위(4시간봉) 존 안에서 생긴 하위 OB인가. 상위 존은 확정된 뒤 max_wait 동안 유효."""
    zones = [(z.side, z.confirm, z.top, z.bottom) for z in find_fvgs(df_htf)]
    zones += [(z.side, z.confirm, z.top, z.bottom) for z in find(df_htf)]
    step = df_htf["time"].iloc[1] - df_htf["time"].iloc[0]
    htf_close = (df_htf["time"] + step).to_numpy()
    times = df["time"].to_numpy()
    for ob in obs:
        t = times[ob.impulse]
        ob.tags["htf"] = any(
            zs == ob.side and htf_close[zc] <= t and t < htf_close[min(zc + max_wait_htf, len(htf_close) - 1)]
            and ob.bottom <= zt and ob.top >= zb
            for zs, zc, zt, zb in zones)


def simulate(df: pd.DataFrame, obs: list[OB], exit_mode: str = "lecture", stop_mode: str = "wick",
             max_wait: int = 48, max_hold: int = 240) -> pd.DataFrame:
    """exit_mode 'lecture': 파동 고점에서 1/2 익절 + 나머지 본절 스탑, 반대 OB 출현 시 종료.
                 'full'   : 파동 고점에서 전량 익절.
       stop_mode 'wick'   : 꼬리 끝 손절(손절 첫 번째 기준), 'close': 꼬리 끝 밖에서 봉 마감 시 손절."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    n = len(c)
    opp_at = {1: set(), -1: set()}
    for b in obs:
        opp_at[b.side].add(b.impulse)
    rows = []
    for b in obs:
        s, entry, stop = b.side, b.entry, b.stop
        wave = h[b.impulse:b.confirm + 1].max() if s > 0 else l[b.impulse:b.confirm + 1].min()
        t0 = None
        for t in range(b.confirm + 1, min(n, b.confirm + 1 + max_wait)):
            if (l[t] <= entry) if s > 0 else (h[t] >= entry):
                t0 = t
                break
            wave = max(wave, h[t]) if s > 0 else min(wave, l[t])
        if t0 is None or ((o[t0] <= stop) if s > 0 else (o[t0] >= stop)):
            continue
        fill = min(o[t0], entry) if s > 0 else max(o[t0], entry)
        risk = abs(fill - stop)
        if risk < 0.001 * fill or s * (wave - fill) <= 0:
            continue
        hard = fill - s * 3 * risk  # 봉 마감 손절일 때의 재앙 방지선
        legs = []                   # (비중, 청산가, 수수료율)
        rest, be = 1.0, False
        for u in range(t0, min(n, t0 + 1 + max_hold)):
            cur_stop = fill if be else stop
            if stop_mode == "close" and not be:
                if (l[u] <= hard) if s > 0 else (h[u] >= hard):
                    legs.append((rest, hard, TAKER)); rest = 0; break
            else:
                if (l[u] <= cur_stop) if s > 0 else (h[u] >= cur_stop):
                    px = (min(o[u], cur_stop) if s > 0 else max(o[u], cur_stop)) if u > t0 else cur_stop
                    legs.append((rest, px, TAKER)); rest = 0; break
            if u > t0 and not be and ((h[u] >= wave) if s > 0 else (l[u] <= wave)):
                if exit_mode == "full":
                    legs.append((rest, wave, MAKER)); rest = 0; break
                legs.append((0.5, wave, MAKER)); rest = 0.5; be = True
                continue
            if stop_mode == "close" and not be and ((c[u] < stop) if s > 0 else (c[u] > stop)):
                legs.append((rest, c[u], TAKER)); rest = 0; break
            if be and u in opp_at[-s]:   # 반대 오더블럭 출현 → 남은 물량 종료
                legs.append((rest, c[u], TAKER)); rest = 0; break
        if rest > 0:
            u = min(n - 1, t0 + max_hold)
            legs.append((rest, c[u], TAKER))
        pnl = sum(w * (s * (px - fill) - MAKER * fill - fee * px) for w, px, fee in legs)
        rows.append({"entry_time": df["time"].iloc[t0], "exit_time": df["time"].iloc[u], "side": s,
                     "r": pnl / risk, "stop_pct": risk / fill, "three": b.three, **b.tags})
    return pd.DataFrame(rows)


FILTERS = {
    "전체 (근거 없이 OB만)": lambda x: x.index == x.index,
    "① 유동성 흡수": lambda x: x.sweep,
    "② FVG 동반": lambda x: x.fvg,
    "BOS 동반": lambda x: x.bos,
    "상위 타임프레임 존과 겹침": lambda x: x.htf,
    "근거 2개 이상": lambda x: (x.sweep.astype(int) + x.fvg.astype(int) + x.bos.astype(int) + x.htf.astype(int)) >= 2,
    "유동성 흡수 + FVG": lambda x: x.sweep & x.fvg,
}


def summarize(res: pd.DataFrame, split_year: int = 2018) -> pd.DataFrame:
    res = res.copy()
    if "htf" not in res:
        res["htf"] = False
    yr = pd.DatetimeIndex(res["entry_time"]).year
    rows = []
    for name, f in FILTERS.items():
        m = np.asarray(f(res), dtype=bool)
        x, tr, te = res.r[m], res.r[m & (yr <= split_year)], res.r[m & (yr > split_year)]
        rows.append({"조건": name, "학습 건수": len(tr), "학습 평균R": tr.mean(), "검증 건수": len(te),
                     "검증 평균R": te.mean(), "전체 평균R": x.mean(),
                     "오차(±)": x.std() / np.sqrt(len(x)) if len(x) > 1 else np.nan,
                     "승률": f"{(x > 0).mean() * 100:.0f}%" if len(x) else "-"})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=str(DEFAULT_CSV))
    ap.add_argument("--symbol")
    ap.add_argument("--count", type=int, default=20000)
    a = ap.parse_args()
    pd.set_option("display.width", 200)
    pd.set_option("display.float_format", lambda v: f"{v:+.3f}")

    df1 = load(a.source, a.symbol, "1h", a.count)
    df4 = resample(df1, "4h")
    for tf, df, mw, mh in (("1시간봉", df1, 48, 240), ("4시간봉", df4, 24, 120)):
        obs = find(df)
        if tf == "1시간봉":
            tag_htf(obs, df1, df4)
        for exit_mode, stop_mode, label in (("lecture", "wick", "강의 교과서: 꼬리 손절 + 1/2 익절·본절"),
                                            ("full", "wick", "꼬리 손절 + 파동 고점 전량 익절"),
                                            ("lecture", "close", "봉 마감 손절 + 1/2 익절·본절")):
            res = simulate(df, obs, exit_mode, stop_mode, mw, mh)
            print(f"\n[{tf}] {label}  (OB {len(obs)}개 중 체결 {len(res)}건, 학습 2017–18 / 검증 2019)")
            print(summarize(res).to_string(index=False))


if __name__ == "__main__":
    main()
