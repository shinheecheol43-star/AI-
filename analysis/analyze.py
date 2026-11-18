"""대화용 차트 분석 도구.

사용법:
    python3 analysis/analyze.py BTCUSDT 1d [--bars 300] [--out chart.png]

바이낸스 공개 시세를 받아 지표를 계산하고, 요약 수치와 차트 이미지를 만든다.
"""
import argparse
import json
import sys
import urllib.request

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402

try:
    import koreanize_matplotlib  # noqa: F401  (한글 글꼴)
except ImportError:
    pass

HOSTS = ["https://data-api.binance.vision", "https://api.binance.com"]


def fetch(symbol: str, interval: str, limit: int) -> pd.DataFrame:
    last_err = None
    for host in HOSTS:
        url = f"{host}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                rows = json.load(r)
            df = pd.DataFrame(rows).iloc[:, :6]
            df.columns = ["time", "open", "high", "low", "close", "volume"]
            df["time"] = pd.to_datetime(df["time"], unit="ms")
            df[["open", "high", "low", "close", "volume"]] = df[["open", "high", "low", "close", "volume"]].astype(float)
            return df.set_index("time")
        except Exception as e:  # 다음 서버 시도
            last_err = e
    raise SystemExit(f"시세를 가져오지 못했습니다: {last_err}")


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    for n in (20, 60, 120):
        df[f"ma{n}"] = c.rolling(n).mean()
    std = c.rolling(20).std(ddof=0)
    df["bb_up"] = df["ma20"] + 2 * std
    df["bb_lo"] = df["ma20"] - 2 * std
    df["bb_pctb"] = (c - df["bb_lo"]) / (df["bb_up"] - df["bb_lo"])
    df["bb_width"] = (df["bb_up"] - df["bb_lo"]) / df["ma20"]

    d = c.diff()
    gain = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    df["rsi"] = 100 - 100 / (1 + gain / loss)

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_sig"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_sig"]

    tr = pd.concat([df["high"] - df["low"], (df["high"] - c.shift()).abs(), (df["low"] - c.shift()).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    return df


def last_cross(fast: pd.Series, slow: pd.Series):
    diff = (fast - slow).dropna()
    sign = np.sign(diff)
    changes = sign[sign != sign.shift()].iloc[1:]
    if changes.empty:
        return None
    t = changes.index[-1]
    return ("골든크로스" if changes.iloc[-1] > 0 else "데드크로스", t, len(diff.loc[t:]) - 1)


def summarize(df: pd.DataFrame, symbol: str, interval: str) -> dict:
    last = df.iloc[-1]
    c = df["close"]
    pct = lambda n: (c.iloc[-1] / c.iloc[-1 - n] - 1) * 100 if len(c) > n else None  # noqa: E731
    mas = {n: last[f"ma{n}"] for n in (20, 60, 120)}
    if all(pd.notna(v) for v in mas.values()):
        if last["close"] > mas[20] > mas[60] > mas[120]:
            align = "정배열 (상승 추세)"
        elif last["close"] < mas[20] < mas[60] < mas[120]:
            align = "역배열 (하락 추세)"
        else:
            align = "혼조"
    else:
        align = "데이터 부족"

    cross = last_cross(df["ma20"], df["ma60"])
    width = df["bb_width"].dropna()
    width_rank = (width.rank(pct=True).iloc[-1] * 100) if len(width) else None
    hist = df["macd_hist"]
    recent = df.iloc[-60:]
    return {
        "종목": f"{symbol} ({interval})",
        "기준 시각(UTC)": str(df.index[-1]),
        "종가": round(last["close"], 6),
        "변화율 %": {"1봉": pct(1), "7봉": pct(7), "30봉": pct(30)},
        "이동평균": {f"MA{n}": round(v, 4) if pd.notna(v) else None for n, v in mas.items()},
        "종가-MA 이격 %": {f"MA{n}": round((last["close"] / v - 1) * 100, 2) if pd.notna(v) else None for n, v in mas.items()},
        "배열": align,
        "최근 20/60 크로스": f"{cross[0]} ({cross[1].date()}, {cross[2]}봉 전)" if cross else "없음",
        "RSI14": round(last["rsi"], 1),
        "MACD": {
            "MACD": round(last["macd"], 4),
            "시그널": round(last["macd_sig"], 4),
            "히스토그램": round(last["macd_hist"], 4),
            "히스토그램 3봉 추이": "증가" if hist.iloc[-1] > hist.iloc[-3] else "감소",
        },
        "볼린저 %B": round(last["bb_pctb"], 2),
        "밴드폭 백분위(기간 내)": round(width_rank, 0) if width_rank is not None else None,
        "ATR14 (종가 대비 %)": round(last["atr"] / last["close"] * 100, 2),
        "거래량 / 20봉 평균": round(last["volume"] / last["vol_ma20"], 2),
        "최근 60봉 고점": round(recent["high"].max(), 4),
        "최근 60봉 저점": round(recent["low"].min(), 4),
        "기간 내 최고/최저": [round(df["high"].max(), 4), round(df["low"].min(), 4)],
    }


def plot(df: pd.DataFrame, title: str, out: str, show_bars: int = 150):
    d = df.iloc[-show_bars:]
    x = mdates.date2num(d.index.to_pydatetime())
    w = (x[1] - x[0]) * 0.7 if len(x) > 1 else 0.5
    up = d["close"] >= d["open"]
    gc, rc = "#26a69a", "#ef5350"

    plt.style.use("dark_background")
    fig, axes = plt.subplots(4, 1, figsize=(13, 9), sharex=True,
                             gridspec_kw={"height_ratios": [4, 1, 1.2, 1.2]})
    fig.patch.set_facecolor("#0f1217")
    for ax in axes:
        ax.set_facecolor("#0f1217")
        ax.grid(color="#1e232d", linewidth=0.6)
        ax.yaxis.tick_right()

    ax = axes[0]
    colors = np.where(up, gc, rc)
    ax.vlines(x, d["low"], d["high"], color=colors, linewidth=0.8)
    ax.bar(x, np.maximum((d["close"] - d["open"]).abs(), d["close"] * 1e-4), bottom=np.minimum(d["open"], d["close"]),
           width=w, color=colors)
    ax.plot(x, d["ma20"], color="#f0b90b", lw=1, label="MA20")
    ax.plot(x, d["ma60"], color="#ab47bc", lw=1, label="MA60")
    ax.plot(x, d["ma120"], color="#29b6f6", lw=1, label="MA120")
    ax.fill_between(x, d["bb_lo"], d["bb_up"], color="#5c6bc0", alpha=0.12, label="볼린저(20,2)")
    diff = np.sign(d["ma20"] - d["ma60"])
    for i in range(1, len(d)):
        if pd.notna(diff.iloc[i - 1]) and diff.iloc[i] != diff.iloc[i - 1] and diff.iloc[i - 1] != 0:
            golden = diff.iloc[i] > 0
            y = d["low"].iloc[i] * 0.985 if golden else d["high"].iloc[i] * 1.015
            ax.annotate("GC" if golden else "DC", (x[i], y), color=gc if golden else rc, ha="center",
                        va="top" if golden else "bottom", fontsize=9, fontweight="bold")
    ax.axhline(d["close"].iloc[-1], color="#888", lw=0.6, ls=":")
    ax.set_title(title, loc="left", fontsize=13)
    ax.legend(loc="upper left", fontsize=8, framealpha=0.2)

    axes[1].bar(x, d["volume"], width=w, color=np.where(up, gc + "88", rc + "88"))
    axes[1].plot(x, d["vol_ma20"], color="#aaa", lw=0.8)
    axes[1].set_ylabel("거래량", fontsize=8)

    axes[2].plot(x, d["rsi"], color="#7e57c2", lw=1.2)
    axes[2].axhline(70, color=rc, ls="--", lw=0.7)
    axes[2].axhline(30, color=gc, ls="--", lw=0.7)
    axes[2].set_ylim(0, 100)
    axes[2].set_ylabel("RSI14", fontsize=8)

    axes[3].bar(x, d["macd_hist"], width=w, color=np.where(d["macd_hist"] >= 0, gc + "aa", rc + "aa"))
    axes[3].plot(x, d["macd"], color="#2962ff", lw=1, label="MACD")
    axes[3].plot(x, d["macd_sig"], color="#ff6d00", lw=1, label="Signal")
    axes[3].set_ylabel("MACD", fontsize=8)
    axes[3].xaxis_date()
    axes[3].xaxis.set_major_formatter(mdates.DateFormatter("%y-%m-%d"))

    fig.tight_layout()
    fig.savefig(out, dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("symbol")
    p.add_argument("interval", nargs="?", default="1d")
    p.add_argument("--bars", type=int, default=300)
    p.add_argument("--show", type=int, default=150, help="차트에 보여줄 봉 개수")
    p.add_argument("--out", default="chart.png")
    a = p.parse_args()

    sym = a.symbol.upper()
    df = add_indicators(fetch(sym, a.interval, a.bars))
    s = summarize(df, sym, a.interval)
    plot(df, f"{sym} · {a.interval}", a.out, a.show)
    json.dump(s, sys.stdout, ensure_ascii=False, indent=2, default=lambda v: None if v is None else round(float(v), 2))
    print()


if __name__ == "__main__":
    main()
