"""계좌 낙폭 브레이크: 잔고가 최고점에서 일정 비율 빠지면 리스크를 줄였다가, 회복하면 되돌린다.

계좌: 스윙 롱 + 스윙 숏 S5·S2 + 데이 롱(시가범위 돌파 + 전일 고점 위), 모두 0.5%, 레버리지 합계 3배 이하
비용: 각 시뮬레이션의 수수료·펀딩비 + 슬리피지(진입·청산 각각 slip, 기본 0.05%)
브레이크 (실현 잔고 기준, 봇이 실제로 알 수 있는 값)
  dd      : 최고 잔고 대비 이만큼 빠지면 발동
  mult    : 발동 중 리스크 배수 (0 = 신규 진입 중지)
  recover : 최고 잔고 대비 낙폭이 이 값보다 작아지면 해제 (0 = 신고점 회복 시)
판단: 최대 낙폭이 줄어드는 만큼 수익을 잃는지, 회복이 늦어지지 않는지(가장 긴 회복 기간).

사용:  python -m smc.dd_brake
"""
from __future__ import annotations

import pandas as pd

from . import ls_combo
from .combo_all import day_trades
from .swing_ls import describe


def curve(rows: pd.DataFrame, dd=None, mult=0.5, recover=0.0, start=1000.0, max_lev=3.0):
    bal, peak, on, op, ev, n_on = start, start, False, [], [], 0
    for _, t in rows.sort_values("entry").iterrows():
        for p in sorted([p for p in op if p["exit"] <= t.entry], key=lambda p: p["exit"]):
            bal += p["pnl"]
            op.remove(p)
            ev.append((p["exit"], bal))
            peak = max(peak, bal)
            if dd is not None:
                if not on and bal <= peak * (1 - dd):
                    on, n_on = True, n_on + 1
                elif on and bal >= peak * (1 - recover):
                    on = False
        risk = t.risk * (mult if on else 1.0)
        if risk <= 0:
            continue
        planned = bal * risk / t.stop_pct
        n = min(planned, max_lev * bal - sum(p["notional"] for p in op))
        if n <= 0:
            continue
        op.append({"exit": t.exit, "pnl": bal * risk * n / planned * t.r, "notional": n})
    for p in sorted(op, key=lambda p: p["exit"]):
        bal += p["pnl"]
        ev.append((p["exit"], bal))
    return pd.Series([b for _, b in ev], index=pd.DatetimeIndex([e for e, _ in ev])).sort_index(), n_on


def underwater(cv: pd.Series) -> int:
    """최고점을 다시 넘기까지 가장 오래 걸린 날 수."""
    peak, since, worst = -1.0, None, 0
    for t, v in cv.items():
        if v >= peak:
            if since is not None:
                worst = max(worst, (t - since).days)
            peak, since = v, t
    return max(worst, (cv.index[-1] - since).days)


CONFIGS = {
    "브레이크 없음": {},
    "−5% 에서 절반, 신고점에 해제": {"dd": 0.05, "mult": 0.5},
    "−10% 에서 절반, 신고점에 해제": {"dd": 0.10, "mult": 0.5},
    "−10% 에서 절반, −5% 로 회복 시 해제": {"dd": 0.10, "mult": 0.5, "recover": 0.05},
    "−10% 에서 1/4, 신고점에 해제": {"dd": 0.10, "mult": 0.25},
    "−15% 에서 절반, 신고점에 해제": {"dd": 0.15, "mult": 0.5},
    "−10% 에서 중지, −5% 로 회복 시 해제": {"dd": 0.10, "mult": 0.0, "recover": 0.05},
    "단계: −7% 절반, −14% 1/4": "steps",
}


def main(slip=0.0005):
    P = ls_combo.closes()
    T = ls_combo.pool(P)
    x = pd.concat([ls_combo.build(T, long=0.005, s5=0.005, s2=0.005), day_trades().assign(risk=0.005)])
    x = x.assign(r=x.r - 2 * slip / x.stop_pct)
    print(f"모든 전략 0.5%, 슬리피지 {slip*100:.2f}% | {len(x)}거래\n")
    print(f"{'구성':34} | {'연평균':>7} {'최대낙폭':>7} {'효율':>5} | {'검증 연평균':>9} {'검증낙폭':>7} | {'최장 회복':>8} 발동 | "
          + " ".join(f"{y:>5}" for y in range(2018, 2027)))
    for name, kw in CONFIGS.items():
        if kw == "steps":
            cv, n_on = steps(x)
        else:
            cv, n_on = curve(x, **kw)
        if cv.index[-1] < pd.Timestamp("2022-01-01", tz="UTC"):
            print(f"{name:34} | {cv.index[-1]:%Y-%m} 이후 거래 없음: 진입을 멈추면 잔고가 회복할 방법이 없어 영원히 멈춤")
            continue
        d = describe(cv)
        f, b = d["full"], d["test"]
        print(f"{name:34} | {f[0]*100:+6.1f}% {f[1]*100:6.1f}% {f[0]/-f[1]:5.2f} | {b[0]*100:+8.1f}% {b[1]*100:6.1f}% |"
              f" {underwater(cv):6}일 {n_on:3} | " + " ".join(f"{d['years'][y]*100:+4.0f}%" for y in range(2018, 2027)))


def steps(rows: pd.DataFrame, start=1000.0, max_lev=3.0):
    """낙폭 −7% 이면 0.5배, −14% 이면 0.25배, 신고점이면 1배."""
    bal, peak, op, ev, n_on, lvl = start, start, [], [], 0, 0
    for _, t in rows.sort_values("entry").iterrows():
        for p in sorted([p for p in op if p["exit"] <= t.entry], key=lambda p: p["exit"]):
            bal += p["pnl"]
            op.remove(p)
            ev.append((p["exit"], bal))
            peak = max(peak, bal)
            new = 2 if bal <= peak * 0.86 else (1 if bal <= peak * 0.93 else (0 if bal >= peak else lvl))
            n_on += new > lvl
            lvl = new
        risk = t.risk * (1.0, 0.5, 0.25)[lvl]
        planned = bal * risk / t.stop_pct
        n = min(planned, max_lev * bal - sum(p["notional"] for p in op))
        if n <= 0:
            continue
        op.append({"exit": t.exit, "pnl": bal * risk * n / planned * t.r, "notional": n})
    for p in sorted(op, key=lambda p: p["exit"]):
        bal += p["pnl"]
        ev.append((p["exit"], bal))
    return pd.Series([b for _, b in ev], index=pd.DatetimeIndex([e for e, _ in ev])).sort_index(), n_on


if __name__ == "__main__":
    main()
