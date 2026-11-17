"""균형형 국내 시스템 규칙 (일봉). 실매매(run_daily.py)와 검증(backtest.py)이 같은 함수를 쓴다.

시장 상태 (KODEX 200, 전날 종가): 종가 > 50일선 > 200일선 = 상승, 종가 < 50일선 < 200일선 = 하락, 나머지 = 박스
  상승: 20일 고점 돌파 롱 · 손절 ATR×2 · 추적 ATR×3 · 최대 60일
  박스: 60일 고점 돌파 롱 · 손절 ATR×3 · 추적 ATR×5 · 최대 60일  + KODEX 200 볼린저 하단 평균회귀
  하락: 새 롱 없음 · KODEX 200 숏 신호(S5·S2) 때만 KODEX 인버스
  강한 상승(상승 + ADX≥25): KODEX 200 코어 50%
종목 고르기: 120일 수익률 기준 주도 섹터 상위 3개 · 종목 120일 수익률 > KODEX 200 · 돌파일 종가가 캔들 위쪽 25% 안
위험: 거래당 1% (KODEX 200 이 전날 20일선 아래면 0.5%) · 인버스 0.5% · 박스 1% · 최대 8자리 · 레버리지 없음
"""
from __future__ import annotations

import numpy as np
import pandas as pd

KODEX200, INVERSE = "069500", "114800"
POOL = {
    "반도체": {"005930": "삼성전자", "000660": "SK하이닉스", "009150": "삼성전기", "042700": "한미반도체"},
    "자동차": {"005380": "현대차", "000270": "기아", "012330": "현대모비스"},
    "금융": {"105560": "KB금융", "055550": "신한지주", "086790": "하나금융지주", "032830": "삼성생명", "316140": "우리금융지주"},
    "바이오": {"068270": "셀트리온", "207940": "삼성바이오로직스", "000100": "유한양행"},
    "인터넷·게임": {"035420": "NAVER", "035720": "카카오", "036570": "엔씨소프트", "251270": "넷마블"},
    "2차전지·화학": {"051910": "LG화학", "006400": "삼성SDI", "373220": "LG에너지솔루션", "096770": "SK이노베이션", "003670": "포스코퓨처엠"},
    "철강·소재": {"005490": "POSCO홀딩스", "010130": "고려아연"},
    "조선·방산": {"329180": "HD현대중공업", "009540": "HD한국조선해양", "012450": "한화에어로스페이스", "034020": "두산에너빌리티"},
    "통신·유틸": {"017670": "SK텔레콤", "030200": "KT", "015760": "한국전력"},
    "소비재": {"051900": "LG생활건강", "090430": "아모레퍼시픽", "033780": "KT&G"},
    "지주·전자": {"066570": "LG전자", "028260": "삼성물산", "034730": "SK", "003550": "LG"},
}
SECTOR = {code: s for s, mem in POOL.items() for code in mem}
NAME = {code: n for mem in POOL.values() for code, n in mem.items()} | {KODEX200: "KODEX 200", INVERSE: "KODEX 인버스"}

FAST = dict(N=20, stop=2.0, trail=3.0, hold=60)     # 상승장
SLOW = dict(N=60, stop=3.0, trail=5.0, hold=60)     # 박스권
MAX_POS = 8              # 주식 + 코어 자리 수 (인버스·박스 매매는 따로)
RISK, RISK_WEAK = 0.01, 0.005
BOX_RISK, INV_RISK = 0.01, 0.005
CORE_W, ADX_MIN = 0.5, 25
TOP_SECTORS, LOOK, CPOS = 3, 120, 0.75
INV_STOP, INV_TRAIL, INV_HOLD = 2.0, 3.0, 60
BOX_STOP, BOX_HOLD = 2.0, 10
MIN_BARS = 300


# ---------------------------------------------------------------- 지표
def rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def indicators(d: pd.DataFrame) -> pd.DataFrame:
    """d: index = 날짜, 열 open high low close volume."""
    o, h, l, c = d.open, d.high, d.low, d.close
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    f = pd.DataFrame(index=d.index)
    f["o"], f["h"], f["l"], f["c"], f["atr"] = o, h, l, c, atr
    for n in (20, 50, 200):
        f[f"e{n}"] = c.ewm(span=n, adjust=False).mean()
    f["rsi"] = rsi(c)
    s50, s200 = c.rolling(50).mean(), c.rolling(200).mean()
    f["score"] = (np.sign(c - s200) + np.sign(s50 - s200) + np.sign(c / c.shift(90) - 1)).shift(1)
    for n in (20, 60):
        f[f"hh{n}"] = h.rolling(n).max().shift(1)
    rng = (h - l)
    f["cpos"] = np.where(rng > 0, (c - l) / rng.replace(0, np.nan), 0.5)
    f["mom"] = (c / c.shift(LOOK) - 1).shift(1)
    f["bars"] = np.arange(1, len(d) + 1)
    return f


def adx(f: pd.DataFrame) -> pd.Series:
    h, l = f.h, f.l
    upm, dnm = h.diff(), -l.diff()
    pdm = pd.Series(np.where((upm > dnm) & (upm > 0), upm, 0.0), index=f.index)
    ndm = pd.Series(np.where((dnm > upm) & (dnm > 0), dnm, 0.0), index=f.index)
    pdi = 100 * pdm.ewm(alpha=1 / 14, adjust=False).mean() / f.atr
    ndi = 100 * ndm.ewm(alpha=1 / 14, adjust=False).mean() / f.atr
    return (100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)).ewm(alpha=1 / 14, adjust=False).mean()


def swing_support(f: pd.DataFrame, k: int = 5) -> pd.Series:
    """확정된 마지막 스윙 저점 (좌우 5개 봉 최저, 확정은 피벗 + 5 봉, 쓰는 건 그다음 봉부터)."""
    l = f.l.to_numpy()
    lmin = pd.Series(l).rolling(2 * k + 1, center=True).min().to_numpy()
    sup = np.full(len(l), np.nan)
    for j in np.flatnonzero(l == lmin):
        if j + k + 1 < len(l):
            sup[j + k + 1] = l[j]
    return pd.Series(sup, index=f.index).ffill()


def breakout_entries(f: pd.DataFrame, N: int, stop: float, trail: float, hold: int) -> set[int]:
    """조건(섹터·상대강도·마감) 없이 본 돌파 진입 날짜들. 한 거래가 끝나기 전에는 다음 돌파를 세지 않는다. 그날까지의 값만 쓴다."""
    o, h, l, c, a = (f[k].to_numpy() for k in ("o", "h", "l", "c", "atr"))
    hh, e20, e200, sc, rs = (f[k].to_numpy() for k in (f"hh{N}", "e20", "e200", "score", "rsi"))
    idx = np.flatnonzero(np.isfinite(c))
    n, ent, busy = len(idx), set(), -1
    for jj in range(max(201, N + 1), n):
        i, ip = idx[jj], idx[jj - 1]
        if jj <= busy or not np.isfinite(a[i]):
            continue
        ev = int(c[i] > e200[i]) + int(sc[i] >= 3) + int(rs[i] > 60) + int((c[i] - e20[i]) / a[i] > 1.0)
        if not (c[i] > hh[i] and c[ip] <= hh[ip] and ev >= 3):
            continue
        ent.add(int(i))
        st, ext, end = c[i] - stop * a[i], c[i], None
        for tt in range(jj + 1, min(n, jj + hold + 1)):
            t = idx[tt]
            if o[t] <= st or l[t] <= st:
                end = tt
                break
            ext = max(ext, h[t])
            st = max(st, ext - trail * a[t])
        busy = end if end is not None else jj + hold
    return ent


class Market:
    """모든 종목 지표를 KODEX 200 거래일에 맞춰 둔다. data: {코드: OHLCV DataFrame(index=날짜)}"""

    def __init__(self, data: dict[str, pd.DataFrame]):
        kd = data[KODEX200]
        self.dates = kd.index
        self.k = indicators(kd)
        c = self.k.c
        st = pd.Series("박스", index=c.index)
        st[(c > self.k.e50) & (self.k.e50 > self.k.e200)] = "상승"
        st[(c < self.k.e50) & (self.k.e50 < self.k.e200)] = "하락"
        self.k["state"] = st.shift(1).fillna("박스")                     # 오늘 쓰는 시장 상태 = 전날 종가 기준
        self.k["adx_prev"] = adx(self.k).shift(1)
        self.k["weak"] = (c < self.k.e20).shift(1).fillna(False).astype(bool)
        self.k["core_on"] = (self.k.state == "상승") & (self.k.adx_prev >= ADX_MIN)
        self.k["mid"] = c.rolling(20).mean()
        self.k["bblo"] = self.k.mid - 2 * c.rolling(20).std()
        self.k["sup"] = swing_support(self.k)
        self.inv = data[INVERSE][["open", "high", "low", "close"]].reindex(self.dates) if INVERSE in data else None
        self.S = {code: indicators(d).reindex(self.dates) for code, d in data.items() if code in SECTOR}
        mom = pd.DataFrame({code: f.mom for code, f in self.S.items()})
        secm = pd.DataFrame({s: mom[[c for c in mom if SECTOR[c] == s]].mean(axis=1) for s in POOL})
        self.srank = secm.rank(axis=1, ascending=False)
        self.mom = mom
        # 돌파 '가상 거래' 추적: 조건 미달로 안 산 돌파도 그 거래가 끝나기 전까지 같은 종목 재진입 금지 (검증된 백테스트와 같은 규칙)
        self.allowed = {code: {"상승": breakout_entries(f, **FAST), "박스": breakout_entries(f, **SLOW)} for code, f in self.S.items()}

    def i_of(self, day) -> int:
        return int(self.dates.get_loc(day))

    # -------------------------------------------------- 신호 (i 번째 날 종가에 판단)
    def stock_signal(self, code: str, i: int) -> dict | None:
        state = self.k.state.iat[i]
        if state == "하락":
            return None
        p = FAST if state == "상승" else SLOW
        f = self.S[code]
        r = f.iloc[i]
        if not np.isfinite(r.c) or not np.isfinite(r.atr) or r.bars < MIN_BARS or i < 1:
            return None
        hh, hh_prev, c_prev = r[f"hh{p['N']}"], f[f"hh{p['N']}"].iat[i - 1], f.c.iat[i - 1]
        if not (r.c > hh and c_prev <= hh_prev):
            return None
        ev = int(r.c > r.e200) + int(r.score >= 3) + int(r.rsi > 60) + int((r.c - r.e20) / r.atr > 1.0)
        if ev < 3:
            return None
        if i not in self.allowed[code][state]:
            return None
        rank = self.srank[SECTOR[code]].iat[i]
        kmom = self.k.mom.iat[i]
        if not (rank <= TOP_SECTORS and r.mom > kmom and r.cpos >= CPOS):
            return None
        stop = r.c - p["stop"] * r.atr
        return dict(kind="stock", code=code, price=float(r.c), stop=float(stop), stop_pct=float((r.c - stop) / r.c),
                    trail=p["trail"], hold=p["hold"], mode=state,
                    risk=RISK_WEAK if self.k.weak.iat[i] else RISK, why=f"{state} {p['N']}일 돌파 · 섹터 {int(rank)}위")

    def box_signal(self, i: int) -> dict | None:
        r = self.k.iloc[i]
        if r.state != "박스" or not r.c < r.bblo:
            return None
        stop = r.c - BOX_STOP * r.atr
        return dict(kind="box", code=KODEX200, price=float(r.c), stop=float(stop), stop_pct=float((r.c - stop) / r.c),
                    risk=BOX_RISK, why="박스권 볼린저 하단")

    def inverse_signals(self, i: int) -> list[dict]:
        k = self.k
        r = k.iloc[i]
        if r.state != "하락" or i < 1 or self.inv is None or not np.isfinite(self.inv.close.iat[i]):
            return []
        out = []
        s5 = np.isfinite(r.sup) and r.c < r.sup and k.c.iat[i - 1] >= k.sup.iat[i - 1]
        s2 = r.score <= -1 and r.c < r.e200 and r.h >= r.e50 and r.c < r.e50 and r.c < r.o
        for src, on in (("S5", s5), ("S2", s2)):
            if on:
                istop = r.c + INV_STOP * r.atr
                out.append(dict(kind="inv", code=INVERSE, src=src, price=float(self.inv.close.iat[i]),
                                idx_entry=float(r.c), idx_stop=float(istop), stop_pct=float((istop - r.c) / r.c),
                                risk=INV_RISK, why=f"하락장 KODEX 200 숏 신호 {src}"))
        return out

    # -------------------------------------------------- 보유 관리
    def intraday_exit(self, pos: dict, i: int) -> float | None:
        """i 번째 날 장중 손절 (검증용: 시가·고가·저가로 판단). 실매매는 watch_stops.py 가 현재가로 한다."""
        if pos["kind"] == "stock":
            f = self.S[pos["code"]].iloc[i]
            if not np.isfinite(f.o):
                return None
            if f.o <= pos["stop"]:
                return float(f.o)
            return float(pos["stop"]) if f.l <= pos["stop"] else None
        if pos["kind"] == "box":
            r = self.k.iloc[i]
            return float(min(pos["stop"], r.o)) if r.l <= pos["stop"] else None
        if pos["kind"] == "inv":
            r, inv = self.k.iloc[i], self.inv.iloc[i]
            if r.o >= pos["idx_stop"]:
                return float(inv.open)
            if r.h >= pos["idx_stop"]:       # 지수가 손절가에 닿은 순간의 인버스 값 근사
                return float(self.inv.close.iat[i - 1] * (1 - (pos["idx_stop"] / self.k.c.iat[i - 1] - 1)))
        return None

    def close_update(self, pos: dict, i: int) -> str | None:
        """i 번째 날 종가에: 추적 손절 올리기 / 종가 청산 이유 (없으면 None)."""
        held = i - pos["entry_i"]
        if pos["kind"] == "stock":
            f = self.S[pos["code"]].iloc[i]
            if not np.isfinite(f.c):
                return None
            pos["ext"] = max(pos["ext"], float(f.h))
            pos["stop"] = max(pos["stop"], pos["ext"] - pos["trail"] * float(f.atr))
            return "최대 보유" if held >= pos["hold"] else None
        r = self.k.iloc[i]
        if pos["kind"] == "box":
            if r.c > r.mid:
                return "20일선 회복"
            return "최대 보유" if held >= BOX_HOLD else None
        if pos["kind"] == "inv":
            pos["idx_ext"] = min(pos["idx_ext"], float(r.l))
            pos["idx_stop"] = min(pos["idx_stop"], pos["idx_ext"] + INV_TRAIL * float(r.atr))
            return "최대 보유" if held >= INV_HOLD else None
        if pos["kind"] == "core":
            return None if r.core_on else "강한 상승 끝"
        return None

    def price(self, code: str, i: int) -> float:
        if code == KODEX200:
            return float(self.k.c.iat[i])
        if code == INVERSE:
            return float(self.inv.close.iat[i])
        return float(self.S[code].c.iat[i])


def plan_entries(mk: Market, i: int, positions: list[dict], last_exit: dict, equity: float, cash: float,
                 cost=lambda code: 0.0015) -> list[dict]:
    """i 번째 날 종가에 새로 살 것 (수량 포함). 주식 → 박스 → 인버스 → 코어 순서, 남은 현금 안에서."""
    out = []
    held = {p["code"] for p in positions if p["kind"] == "stock"}
    slots = MAX_POS - sum(p["kind"] in ("stock", "core") for p in positions)
    cand = []
    for code in SECTOR:
        if code in mk.S and code not in held and last_exit.get(code, -1) < i:
            s = mk.stock_signal(code, i)
            if s:
                cand.append(s)
    if not any(p["kind"] == "box" for p in positions) and last_exit.get("box", -1) < i:
        s = mk.box_signal(i)
        if s:
            cand.append(s)
    open_src = {p.get("src") for p in positions if p["kind"] == "inv"}
    for s in mk.inverse_signals(i):
        if s["src"] not in open_src and last_exit.get("inv" + s["src"], -1) < i:
            cand.append(s)
    if mk.k.core_on.iat[i] and not any(p["kind"] == "core" for p in positions) and last_exit.get("core", -1) < i:
        cand.append(dict(kind="core", code=KODEX200, price=mk.price(KODEX200, i), why="강한 상승장 코어"))
    for s in cand:
        if s["kind"] in ("stock", "core"):
            if slots <= 0:
                continue
        want = equity * CORE_W if s["kind"] == "core" else equity * s["risk"] / s["stop_pct"]
        money = min(want, cash)
        qty = int(money // (s["price"] * (1 + cost(s["code"]))))
        if qty <= 0:
            continue
        s.update(qty=qty, entry_i=i, ext=s["price"], idx_ext=s.get("idx_entry"))
        cash -= qty * s["price"] * (1 + cost(s["code"]))
        if s["kind"] in ("stock", "core"):
            slots -= 1
        out.append(s)
    return out


def cost_of(code: str) -> float:
    return 0.0015 if code in SECTOR else 0.0005
