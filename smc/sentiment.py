"""시장 심리 지표: 코인 공포·탐욕 지수(alternative.me), 미국 주식 공포·탐욕 지수(CNN)와 아침 브리핑.

두 지수 모두 인증 없이 공개 주소에서 받는다. 받은 과거 값은 data/sentiment/ 에 저장해 연구에 쓴다.
  코인 : https://api.alternative.me/fng/ (2018-02 부터, 하루 한 번, UTC 0시 기준)
  주식 : https://production.dataviz.cnn.io/index/fearandgreed/graphdata/<시작일> (CNN 페이지가 쓰는 데이터,
         브라우저처럼 보이는 헤더가 없으면 거절된다)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

DIR = Path(__file__).resolve().parent.parent / "data" / "sentiment"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "application/json, text/plain, */*", "Referer": "https://edition.cnn.com/", "Origin": "https://edition.cnn.com"}
LABEL = {"extreme fear": "극단적 공포", "fear": "공포", "neutral": "중립", "greed": "탐욕", "extreme greed": "극단적 탐욕"}
CNN_PARTS = {"market_momentum_sp500": "S&P500 추세", "stock_price_strength": "52주 신고가", "stock_price_breadth": "상승 종목 폭",
             "put_call_options": "풋/콜", "market_volatility_vix": "VIX 변동성", "junk_bond_demand": "정크본드", "safe_haven_demand": "안전자산"}


def label(v: float) -> str:
    """0~100 값을 다섯 구간 이름으로 (두 지수 공통 기준)."""
    return "극단적 공포" if v < 25 else "공포" if v < 45 else "중립" if v <= 55 else "탐욕" if v <= 75 else "극단적 탐욕"


def _save(s: pd.Series, name: str) -> pd.Series:
    DIR.mkdir(parents=True, exist_ok=True)
    out = DIR / f"{name}.csv"
    if out.exists():                                   # 예전에 받은 값과 합친다 (새 값 우선)
        old = pd.read_csv(out, index_col=0, parse_dates=True).iloc[:, 0]
        s = pd.concat([old[~old.index.isin(s.index)], s]).sort_index()
    s.rename(name).to_csv(out)
    return s


def crypto_fng(limit: int = 0) -> pd.Series:
    """코인 공포·탐욕 지수 (날짜 → 0~100). limit=0 이면 전체 기간."""
    import requests

    r = requests.get("https://api.alternative.me/fng/", params={"limit": limit, "format": "json"}, timeout=20)
    r.raise_for_status()
    s = pd.Series({pd.Timestamp(int(d["timestamp"]), unit="s", tz="UTC").normalize(): float(d["value"]) for d in r.json()["data"]})
    return _save(s.sort_index(), "crypto_fng")


def cnn_fng(start: str = "2018-01-01") -> dict:
    """CNN 공포·탐욕 지수: 지금 값, 비교 값(1주·1달·1년 전), 세부 지표 7개, 과거 일별 값."""
    import requests

    r = requests.get(f"https://production.dataviz.cnn.io/index/fearandgreed/graphdata/{start}", headers=UA, timeout=20)
    r.raise_for_status()
    j = r.json()
    hist = pd.Series({pd.Timestamp(int(p["x"]), unit="ms", tz="UTC").normalize(): float(p["y"])
                      for p in j["fear_and_greed_historical"]["data"]})
    hist = _save(hist.sort_index(), "cnn_fng")
    fg = j["fear_and_greed"]
    parts = {name: (j[k]["score"], j[k]["rating"]) for k, name in CNN_PARTS.items() if isinstance(j.get(k), dict) and "score" in j[k]}
    return {"score": float(fg["score"]), "rating": fg.get("rating", ""), "week": fg.get("previous_1_week"),
            "month": fg.get("previous_1_month"), "year": fg.get("previous_1_year"), "parts": parts, "hist": hist}


def load(name: str) -> pd.Series:
    """저장해 둔 과거 값 (연구용)."""
    return pd.read_csv(DIR / f"{name}.csv", index_col=0, parse_dates=True).iloc[:, 0]


# ---------------------------------------------------------------- 아침 브리핑
def _ago(s: pd.Series, days: int) -> str:
    t = s.index[-1] - pd.Timedelta(days=days)
    v = s[s.index <= t]
    return f"{v.iloc[-1]:.0f}" if len(v) else "–"


def briefing(snap: dict, now_kst: pd.Timestamp) -> str:
    """snap: signal_bot.snapshot 결과 (가격·국면·진행 중 신호)."""
    lines = [f"☀️ 아침 브리핑 {now_kst:%m-%d} ({'월화수목금토일'[now_kst.weekday()]})"]
    try:
        c = crypto_fng(40)
        lines.append(f"코인 공포·탐욕 {c.iloc[-1]:.0f} {label(c.iloc[-1])} (어제 {_ago(c, 1)} · 1주 전 {_ago(c, 7)} · 1달 전 {_ago(c, 30)})")
    except Exception as e:
        lines.append(f"코인 공포·탐욕: 가져오지 못함 ({type(e).__name__})")
    try:
        s = cnn_fng((now_kst - pd.Timedelta(days=40)).strftime("%Y-%m-%d"))
        fmt = lambda v: f"{v:.0f}" if isinstance(v, (int, float)) else "–"
        lines.append(f"미국 주식 공포·탐욕(CNN) {s['score']:.0f} {LABEL.get(s['rating'], s['rating'])}"
                     f" (1주 전 {fmt(s['week'])} · 1달 전 {fmt(s['month'])})")
        if s["parts"]:
            lines.append("  " + " · ".join(f"{n} {LABEL.get(r, r)}" for n, (_, r) in s["parts"].items()))
    except Exception as e:
        lines.append(f"미국 주식 공포·탐욕: 가져오지 못함 ({type(e).__name__})")
    for sym, X in snap["Xs"].items():
        i, cur = len(X["c"]) - 1, snap["last"][sym]
        h1 = X.get("h1")
        chg = f" (24h {(cur / h1.close.iloc[-25] - 1) * 100:+.1f}%)" if h1 is not None and len(h1) > 25 else ""
        fmtp = f"{cur:,.0f}" if cur >= 1000 else f"{cur:,.2f}"
        lines.append(f"{sym} {fmtp}{chg} · 일봉 국면 {X['score'][i]:+.0f} · 4h 200EMA {'위' if X['c'][i] > X['e200'][i] else '아래'}")
    opened = snap["x"][snap["x"].open.astype(bool)]
    if opened.empty:
        lines.append("진행 중 신호 없음")
    for t in opened.itertuples():
        one_r = t.p0 * t.stop_pct
        stop = f"{t.stop:,.0f}" if t.stop >= 1000 else f"{t.stop:,.2f}"
        lines.append(f"진행 중 {t.symbol} {t.src}: 손절 {stop} · {t.side * (snap['last'][t.symbol] - t.p0) / one_r:+.2f}R")
    return "\n".join(lines)
