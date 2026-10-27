"""공포·탐욕 지수로 스윙 타점을 거를 수 있는가 (코인 지수 alternative.me, 미국 주식 지수 CNN).

검증 전에 정한 기준 (결과를 보고 바꾸지 않는다)
  구간: 0–24 극단적 공포 · 25–44 공포 · 45–55 중립 · 56–75 탐욕 · 76–100 극단적 탐욕
  지수 값은 신호 시점에 이미 발표된 값만 쓴다 (코인: 그날 UTC 0시 값, 주식: 전날 미국장 마감 값)
1. 지수 구간별 BTC·ETH 이후 7일·30일 수익률 (역발상 매수가 통하는지)
2. 지금 스윙 전략(smc.system: 스윙 롱, 숏 S5, 숏 S2)의 거래를 진입 시점 지수 구간으로 나눈 평균 R
3. 필터를 붙인 한 계좌 결과 (BTC+ETH, 리스크 그대로)
   롱: 극단적 탐욕(>75)이면 건너뛰기 / 숏: 극단적 공포(<25)면 건너뛰기 / 둘 다
설계 구간 2018–2021, 검증 구간 2022– 로 나눠 두 구간 모두에서 같은 방향인지 본다.

인터넷이 되는 PC에서 실행 (이 두 사이트에 접속해야 함):
  python -m smc.fng_study            → 화면 출력 + reports/fng_study.txt 저장
"""
from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import pandas as pd

from . import sentiment, system as S
from .dd_brake import curve
from .research_report import SPLIT
from .swing_ls import describe

BINS = [-1, 24.5, 44.5, 55.5, 75.5, 101]
NAMES = ["극단적 공포", "공포", "중립", "탐욕", "극단적 탐욕"]
OUT = Path(__file__).resolve().parent.parent / "reports" / "fng_study.txt"


def bucket(v: pd.Series) -> pd.Series:
    return pd.cut(v, BINS, labels=NAMES)


def value_at(s: pd.Series, times: pd.Series, lag_days: int) -> np.ndarray:
    """각 시각에 이미 알 수 있었던 지수 값 (lag_days 일 전 날짜까지 발표된 값)."""
    idx = pd.DatetimeIndex(s.index)
    out = []
    for t in times:
        k = idx.searchsorted(t.floor("D") - pd.Timedelta(days=lag_days), side="right") - 1
        out.append(s.iloc[k] if k >= 0 else np.nan)
    return np.array(out, dtype=float)


def forward_returns(idx_name: str, s: pd.Series, Xs: dict, lag: int):
    print(f"\n■ 1. {idx_name} 구간별 이후 수익률 (일봉 종가 기준, 같은 날 진입)")
    print(f"{'코인':4} {'구간':10} {'일수':>5} | {'7일 평균':>8} {'상승 비율':>8} | {'30일 평균':>9} {'상승 비율':>8} | 30일 평균 설계/검증")
    for sym, X in Xs.items():
        d = X["dD"].set_index("time").close
        f = pd.DataFrame({"r7": d.shift(-7) / d - 1, "r30": d.shift(-30) / d - 1})
        f["v"] = value_at(s, pd.Series(d.index + pd.Timedelta("1D")), lag)   # 그날 마감 직후 기준
        f = f.dropna()
        for name in ["전체"] + NAMES:
            g = f if name == "전체" else f[bucket(f.v) == name]
            if len(g) < 20:
                continue
            a, b = g[g.index < SPLIT], g[g.index >= SPLIT]
            print(f"{sym:4} {name:10} {len(g):5} | {g.r7.mean()*100:+7.2f}% {(g.r7 > 0).mean()*100:7.0f}% | {g.r30.mean()*100:+8.2f}%"
                  f" {(g.r30 > 0).mean()*100:7.0f}% | {a.r30.mean()*100:+6.1f}% / {b.r30.mean()*100:+6.1f}%")


def trades_by_bucket(idx_name: str, x: pd.DataFrame):
    print(f"\n■ 2. 스윙 거래를 진입 시점 {idx_name} 구간으로 나눈 평균 R (슬리피지 포함)")
    print(f"{'전략':6} {'구간':10} {'거래':>5} {'승률':>6} {'평균R':>7} | {'설계 n/R':>12} {'검증 n/R':>12}")
    for src in ("스윙 롱", "숏 S5", "숏 S2"):
        y = x[x.src == src]
        for name in NAMES:
            g = y[bucket(y.v) == name]
            if len(g) < 5:
                continue
            a, b = g[g.entry < SPLIT], g[g.entry >= SPLIT]
            print(f"{src:6} {name:10} {len(g):5} {(g.r > 0).mean()*100:5.0f}% {g.r.mean():+.3f} |"
                  f" {len(a):4}/{a.r.mean():+.2f} {len(b):5}/{b.r.mean():+.2f}")


def filters(idx_name: str, x: pd.DataFrame):
    print(f"\n■ 3. {idx_name} 필터를 붙인 BTC+ETH 한 계좌 ($1,000, 리스크 그대로)")
    print(f"{'구성':30} | {'연평균':>7} {'낙폭':>7} {'효율':>5} | {'설계':>7} {'검증':>7} {'검증낙폭':>7} | 거래")
    cfg = {"필터 없음 (지금)": x,
           "롱: 극단적 탐욕이면 건너뛰기": x[~((x.side > 0) & (x.v > 75.5))],
           "숏: 극단적 공포면 건너뛰기": x[~((x.side < 0) & (x.v < 24.5))],
           "둘 다": x[~(((x.side > 0) & (x.v > 75.5)) | ((x.side < 0) & (x.v < 24.5)))]}
    for name, y in cfg.items():
        cv, _ = curve(y)
        d = describe(cv)
        f, a, b = d["full"], d["design"], d["test"]
        print(f"{name:30} | {f[0]*100:+6.1f}% {f[1]*100:6.1f}% {f[0]/-f[1]:5.2f} | {a[0]*100:+6.1f}% {b[0]*100:+6.1f}% {b[1]*100:6.1f}% | {len(y)}")


def run():
    print("공포·탐욕 지수 받는 중...")
    crypto = sentiment.crypto_fng(0)
    try:
        stock = sentiment.cnn_fng("2018-01-01")["hist"]
    except Exception as e:
        print(f"CNN 지수를 받지 못했습니다 ({e}). 코인 지수만 연구합니다.")
        stock = None
    print(f"코인 지수 {crypto.index[0]:%Y-%m-%d} ~ {crypto.index[-1]:%Y-%m-%d} ({len(crypto)}일)"
          + (f" · CNN 지수 {stock.index[0]:%Y-%m-%d} ~ {stock.index[-1]:%Y-%m-%d} ({len(stock)}일)" if stock is not None else ""))
    Xs = {s: S.context(s) for s in S.SYMS}
    sw = pd.concat([S.swing_trades(X) for X in Xs.values()], ignore_index=True)
    sw = sw[~sw.open.astype(bool)]
    sw = sw.assign(risk=sw.src.map(S.RISK), r=sw.r - 2 * S.SLIP / sw.stop_pct)
    for idx_name, s, lag in (("코인 공포·탐욕", crypto, 0), ("미국 주식 공포·탐욕(CNN)", stock, 1)):
        if s is None:
            continue
        x = sw.assign(v=value_at(s, sw.entry - pd.Timedelta("4h"), lag))
        x = x[x.v.notna()]
        print(f"\n{'=' * 20} {idx_name} (거래 {len(x)}건, {x.entry.min():%Y-%m} 부터) {'=' * 20}")
        forward_returns(idx_name, s, Xs, lag)
        trades_by_bucket(idx_name, x)
        filters(idx_name, x)


def main():
    buf = io.StringIO()
    with redirect_stdout(buf):
        run()
    text = buf.getvalue()
    print(text)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"결과 저장: {OUT}")


if __name__ == "__main__":
    main()
