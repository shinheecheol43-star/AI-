"""CHoCH → OB → FVG 리테스트: 이긴 거래와 진 거래의 조건 비교, 손실 경로 분석, 손실 줄이기 규칙 검증.

기본 설정 (지금까지 가장 나았던 것): FVG 윗변 지정가 진입, 손절 OB 꼬리 − 0.1 ATR, 추적 3ATR, 최대 보유 = choch_ob_fvg 의 3배
봉: 15분·30분·1시간·4시간 (5분은 모든 방식이 크게 손실이라 제외), BTC·ETH, 롱·숏
규칙은 결과를 보기 전에 정했다.

A. 진입 때 알 수 있는 조건 (롱 기준, 숏은 뒤집어 같은 값)
   돌파 힘      = (돌파 봉까지 파동 고점 − 마지막 저점) ÷ ATR
   돌파 봉 몸통  = CHoCH 봉 몸통 ÷ 봉 길이
   돌파 거래량  = CHoCH 봉 거래량 ÷ 직전 20봉 평균
   FVG 크기     = FVG 높이 ÷ ATR
   손절폭       = (진입가 − 손절가) ÷ ATR
   되돌림 깊이  = (파동 고점 − 진입가) ÷ (파동 고점 − 마지막 저점)
   대기 봉 수   = FVG 확인 뒤 체결까지 봉 수
   직전 하락    = CHoCH 전 50봉 수익률 ÷ ATR (클수록 하락이 약했음)
   상위 추세    = 일봉 장세가 진입 방향과 같으면 1
   각 조건을 설계 구간 3분위로 나눠 평균 R 비교. 위 − 아래 차이가 설계·검증에서 같은 부호이고 검증에서 0.1R 이상이면 '쓸 만한 조건'.
B. 손실 경로 (진입 뒤 실제 움직임, 진단용)
   바로 실패   = 한 번도 +0.3R 에 못 가고 손절
   되돌아옴    = +1R 이상 갔다가 결국 손실
   손절까지 걸린 봉 수
C. 손실 줄이기 규칙 (기본 설정 위에 하나씩 더함)
   약하면 탈출 N·m : 진입 뒤 N 봉(3·6·12) 안에 +m R(0.3·0.5)에 못 가면 N 봉째 종가에 청산
   본절 이동 x     : +x R(0.5·1.0) 에 닿으면 다음 봉부터 손절을 본절(+수수료)로
   시간 손절 N     : N 봉(6·12) 뒤 종가가 진입가 아래면 청산
   조건 필터       : A 에서 '설계 구간' 기준 가장 좋았던 조건 하나의 좋은 2/3 만 진입
   판정: 설계 구간에서 기본보다 평균 R 이 좋아진 규칙을 고르고, 검증 구간에서도 좋아졌는지 본다.
         같은 규칙을 무작위 진입에 붙였을 때도 같은 만큼 좋아지면 '신호와 무관한 청산 효과'.
비용: 진입 지정가 0.02%, 청산 0.075%

사용:  python -m smc.choch_loss
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from itertools import product

import numpy as np
import pandas as pd

from .bos_choch import arrays
from .choch_ob_fvg import HOLD, SYMS, WAIT, setups
from .daytrade import SPLIT
from .highwin import MAKER, TAKER, frame

TFS = ("15min", "30min", "1h", "4h")
FEATS = {"break_power": "돌파 힘", "break_body": "돌파 봉 몸통", "break_vol": "돌파 거래량", "fvg_size": "FVG 크기",
         "stop_atr": "손절폭", "retrace": "되돌림 깊이", "wait": "대기 봉 수", "prior_drop": "직전 하락", "htf": "상위 추세"}
RULES = [("기본", {})] + [(f"약하면 탈출 {n}봉·{m}R", {"weak": (n, m)}) for n, m in product((3, 6, 12), (0.3, 0.5))] \
        + [(f"본절 이동 {x}R", {"be": x}) for x in (0.5, 1.0)] + [(f"시간 손절 {n}봉", {"time": n}) for n in (6, 12)]


def trade_list(sym, tf, side):
    idx, o, h, l, c, atr, reg = arrays(sym, tf, side)
    vol = frame(sym, tf).volume.to_numpy()
    n, hold = len(c), HOLD[tf] * 3
    out = []
    for s in setups(sym, tf, side):
        stop = s["ob_lo"] - 0.1 * s["atr"]
        limit = s["top"]
        if not (0.3 * s["atr"] <= limit - stop <= 6 * s["atr"]):
            continue
        e = next((u for u in range(s["start"], min(n - hold - 1, s["start"] + WAIT)) if l[u] <= limit), None)
        if e is None:
            continue
        px = limit if o[e] <= stop else min(limit, o[e])
        t, ob, a = s["t"], s["ob"], s["atr"]
        lo = l[ob:t + 1].min()
        leg_hi = h[ob:e].max()
        rng = h[t] - l[t]
        out.append(dict(sym=sym, tf=tf, side=side, e=e, time=idx[e], px=px, stop=stop,
                        break_power=(h[ob:t + 1].max() - lo) / a,
                        break_body=abs(c[t] - o[t]) / rng if rng > 0 else 0.0,
                        break_vol=vol[t] / max(vol[max(0, t - 20):t].mean(), 1e-12),
                        fvg_size=(s["top"] - s["bot"]) / a, stop_atr=(px - stop) / a,
                        retrace=(leg_hi - px) / max(leg_hi - lo, 1e-12), wait=e - s["start"],
                        prior_drop=(c[t - 1] - c[max(0, t - 51)]) / a, htf=float(s["reg"]),
                        ob_wick=(min(o[ob], c[ob]) - l[ob]) / (h[ob] - l[ob]) if h[ob] > l[ob] else 0.0,
                        disp=abs(c[s["fi"] - 1] - o[s["fi"] - 1]) / a))
    return out


def run_trade(o, h, l, c, atr, e, px, stop, hold, rule):
    """한 거래를 봉 단위로 진행. 반환: R, 청산 봉, 최대 유리(R), 손절까지 걸린 봉."""
    dist = px - stop
    a = atr[e]
    best = px
    cur = stop
    mfe = 0.0
    for j in range(hold):
        u = e + j
        if l[u] <= cur:
            ex = min(cur, o[u]) if j > 0 else cur
            return (ex - px - (MAKER + TAKER) * abs(px)) / dist, u, mfe, j
        if j > 0:                                           # 체결 봉 안의 순서는 모르므로 그 봉 고가는 다음부터 반영
            best = max(best, h[u])
            mfe = max(mfe, (best - px) / dist)
        if "fixed" in rule:                                 # 고정 목표 (추적 없음)
            if j > 0 and h[u] >= px + rule["fixed"] * dist:
                return rule["fixed"] - (MAKER + MAKER) * abs(px) / dist, u, mfe, j
            continue
        new = best - 3.0 * a
        if "be" in rule and mfe >= rule["be"]:
            new = max(new, px + 2 * TAKER * abs(px))
        cur = max(cur, new)
        if "weak" in rule and j + 1 == rule["weak"][0] and mfe < rule["weak"][1]:
            return (c[u] - px - (MAKER + TAKER) * abs(px)) / dist, u, mfe, j
        if "time" in rule and j + 1 == rule["time"] and c[u] < px:
            return (c[u] - px - (MAKER + TAKER) * abs(px)) / dist, u, mfe, j
    u = e + hold - 1
    return (c[u] - px - (MAKER + TAKER) * abs(px)) / dist, u, mfe, hold


def evaluate(trades, rule, rng=None):
    """trades: 같은 (코인, 봉, 방향) 거래 목록. 코인마다 한 번에 한 거래. rng 가 있으면 무작위 시점으로 바꿔서."""
    res = []
    for (sym, tf, side), g in trades.groupby(["sym", "tf", "side"]):
        idx, o, h, l, c, atr, _ = arrays(sym, tf, side)
        hold = HOLD[tf] * 3
        if rng is not None:
            es = np.sort(rng.choice(np.arange(500, len(c) - hold - 2), len(g), replace=False))
            pct = ((g.px - g.stop) / g.px.abs()).to_numpy()
            rows = [(e_, o[e_], o[e_] - abs(o[e_]) * p) for e_, p in zip(es, rng.permutation(pct))]
        else:
            rows = list(zip(g.e, g.px, g.stop))
        busy = -1
        for k, (e, px, stop) in enumerate(rows):
            if e <= busy:
                continue
            r, ex, mfe, bars = run_trade(o, h, l, c, atr, int(e), px, stop, hold, rule)
            busy = ex
            rec = {"time": idx[int(e)], "r": r, "mfe": mfe, "bars": bars, "sym": sym, "tf": tf, "side": side}
            if rng is None:
                rec.update(g.iloc[k][list(FEATS)].to_dict())
            res.append(rec)
    return pd.DataFrame(res)


def build(cfg):
    sym, tf, side = cfg
    return trade_list(sym, tf, side)


def main():
    cfgs = list(product(SYMS, TFS, (1, -1)))
    with ProcessPoolExecutor(4) as pool:
        T = pd.DataFrame([r for rows in pool.map(build, cfgs) for r in rows]).sort_values(["sym", "tf", "side", "e"])
    base = evaluate(T, {})
    base["test"] = base.time >= SPLIT
    print("CHoCH → OB → FVG 리테스트 · 기본: FVG 윗변 · OB 꼬리 손절 · 추적 3ATR · BTC·ETH · 15분~4시간 · 설계 ~2021 / 검증 2022~\n")
    print(f"거래 {len(base):,}건 · 승률 {(base.r > 0).mean()*100:.0f}% · 평균 {base.r.mean():+.3f}R"
          f" · 평균 이익 {base[base.r > 0].r.mean():+.2f}R · 평균 손실 {base[base.r <= 0].r.mean():+.2f}R\n")

    print("■ 1. 이긴 거래 vs 진 거래: 진입 때 조건 (중간값)")
    W, Ls = base[base.r > 0], base[base.r <= 0]
    print(f"  {'조건':10} | {'이긴 거래':>9} {'진 거래':>9}")
    for f, name in FEATS.items():
        print(f"  {name:10} | {W[f].median():9.2f} {Ls[f].median():9.2f}")

    print("\n■ 2. 조건별 3분위 평균 R (설계 구간 기준으로 나눔) — 아래 / 중간 / 위, 위−아래 (설계 · 검증)")
    good_feats = []
    for f, name in FEATS.items():
        tr = base[~base.test]
        if f == "htf":
            cut = pd.Series(np.where(base[f] > 0.5, "위", "아래"), index=base.index)
        else:
            q1, q2 = tr[f].quantile([1 / 3, 2 / 3])
            cut = pd.cut(base[f], [-np.inf, q1, q2, np.inf], labels=["아래", "중간", "위"])
        d = base.assign(b=cut)
        cell = lambda m, b: d[m & (d.b == b)].r.mean()
        sp_tr = cell(~d.test, "위") - cell(~d.test, "아래")
        sp_te = cell(d.test, "위") - cell(d.test, "아래")
        cells = " / ".join(f"{d[d.b == b].r.mean():+.2f}" if (d.b == b).any() else "  –  " for b in ("아래", "중간", "위"))
        ok = np.sign(sp_tr) == np.sign(sp_te) and abs(sp_te) >= 0.1
        if ok:
            good_feats.append((abs(sp_tr), f, "위" if sp_tr > 0 else "아래"))
        print(f"  {name:10} | {cells} | 설계 {sp_tr:+.2f} · 검증 {sp_te:+.2f} {'✓ 일관' if ok else ''}")

    print("\n■ 3. 손실 거래는 어떻게 졌나 (전체 기간)")
    loss = base[base.r <= 0]
    fast = (loss.mfe < 0.3).mean()
    back = (loss.mfe >= 1.0).mean()
    print(f"  손실 {len(loss):,}건 중 바로 실패(+0.3R 도 못 감) {fast*100:.0f}% · +1R 이상 갔다가 되돌아옴 {back*100:.0f}%")
    print(f"  손실까지 걸린 봉 수 중간값 {loss.bars.median():.0f}봉 · 이긴 거래 보유 중간값 {W.bars.median():.0f}봉")
    for tf in TFS:
        z = loss[loss.tf == tf]
        print(f"   {tf:6} 바로 실패 {(z.mfe < 0.3).mean()*100:3.0f}% · 되돌아옴 {(z.mfe >= 1).mean()*100:3.0f}% · 손절까지 중간값 {z.bars.median():.0f}봉")
    print("  진입 뒤 3봉 안의 최대 유리(R)에 따라 나중 결과:")
    early = {}
    for lo_, hi_ in ((0, 0.3), (0.3, 0.6), (0.6, 1.0), (1.0, 99)):
        z = base[(base.mfe >= lo_) & (base.mfe < hi_)]
        early[(lo_, hi_)] = z
    print("  (참고: 최대 유리 전체 기간 기준) " + " · ".join(f"{a}~{b}R: {len(z)}건 평균 {z.r.mean():+.2f}R" for (a, b), z in early.items()))

    print("\n■ 4. 손실 줄이기 규칙 (기본 대비, 평균 R · 승률 · 평균 손실)")
    print(f"  {'규칙':18} | {'설계 R':>7} {'검증 R':>7} {'검증 승률':>8} {'검증 평균손실':>11} | {'무작위 설계':>9} {'무작위 검증':>9} | 판단")
    rows = []
    rng_seed = 11
    store = {}
    for name, rule in RULES:
        x = base if name == "기본" else evaluate(T, rule)
        x["test"] = x.time >= SPLIT
        store[name] = x
        rx = evaluate(T, rule, np.random.default_rng(rng_seed))
        rx["test"] = rx.time >= SPLIT
        rows.append((name, x[~x.test].r.mean(), x[x.test].r.mean(), (x[x.test].r > 0).mean(), x[x.test & (x.r <= 0)].r.mean(),
                     rx[~rx.test].r.mean(), rx[rx.test].r.mean()))
    b = rows[0]
    for name, a_tr, a_te, w, ml, r_tr, r_te in rows:
        d_sig, d_rand = a_te - b[2], r_te - rows[0][6]
        verdict = "" if name == "기본" else ("설계·검증 모두 개선" if a_tr > b[1] and a_te > b[2] else "–")
        if verdict.startswith("설계") and d_rand >= d_sig * 0.7:
            verdict += " (무작위도 비슷하게 개선 → 청산 효과)"
        print(f"  {name:18} | {a_tr:+7.3f} {a_te:+7.3f} {w*100:7.0f}% {ml:+11.2f} | {r_tr:+9.3f} {r_te:+9.3f} | {verdict}")

    if good_feats:
        good_feats.sort(reverse=True)
        _, f, side_ = good_feats[0]
        tr = base[~base.test]
        q = tr[f].quantile(1 / 3 if side_ == "위" else 2 / 3)
        keep = base[f] > q if side_ == "위" else base[f] < q
        z = base[keep]
        print(f"\n■ 5. 조건 필터: '{FEATS[f]}' {'아래 1/3 제외' if side_ == '위' else '위 1/3 제외'} (설계 구간에서 가장 차이가 컸던 일관 조건)")
        print(f"  설계 {z[~z.test].r.mean():+.3f}R ({(~z.test).sum()}건) · 검증 {z[z.test].r.mean():+.3f}R ({z.test.sum()}건)"
              f" · 기본 검증 {base[base.test].r.mean():+.3f}R")
    else:
        print("\n■ 5. 조건 필터: 설계·검증에서 일관된 조건이 없어 시험하지 않음")

    print("\n■ 6. 봉별: 기본 vs 설계 구간에서 가장 좋았던 규칙 (검증 구간)")
    for tf in TFS:
        best = max(((n, x[(x.tf == tf) & ~x.test].r.mean()) for n, x in store.items()), key=lambda v: v[1])[0]
        z0, z1 = store["기본"], store[best]
        a0, a1 = z0[(z0.tf == tf) & z0.test], z1[(z1.tf == tf) & z1.test]
        print(f"  {tf:6} 기본 {a0.r.mean():+.3f}R (승률 {(a0.r > 0).mean()*100:.0f}%, {len(a0)}건) → {best}: {a1.r.mean():+.3f}R"
              f" (승률 {(a1.r > 0).mean()*100:.0f}%, 평균 손실 {a1[a1.r <= 0].r.mean():+.2f}R)")

if __name__ == "__main__":
    main()
