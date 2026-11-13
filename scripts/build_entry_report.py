"""data/entry_summary.json -> report/entry.html"""
import json
import os

import pandas as pd

ROOT = os.path.join(os.path.dirname(__file__), "..")
d = json.load(open(os.path.join(ROOT, "data", "entry_summary.json"), encoding="utf-8"))
vol = pd.read_csv(os.path.join(ROOT, "data", "first_lu_by_volume.csv"))
pre, sigs, ld, cal = d["pre"], d["signals"], d["ld"], d["calendar"]


def pct(x, k=1, sign=False):
    if x is None:
        return "-"
    return f"{x*100:+.{k}f}%" if sign else f"{x*100:.{k}f}%"


days = [{"k": k, "vr": v["vr_med"], "vr3": v["vr3_share"], "up10": v["up10_share"]}
        for k, v in reversed(list(pre["by_day"].items()))]
sig_short = ["기준(아무 날)", "A 거래량↑+5~15%", "B A+낙폭과대", "C 15~29% 급등",
             "D 장중+20% 윗꼬리", "E 상한가 다음날", "F 상한가 종가"]
sigc = [{"k": sig_short[i], "lu10": s["lu_within"]["10일"], "ev": s["sim"]["-10%"]["mean"]}
        for i, s in enumerate(sigs)]
DATA = json.dumps({"days": days, "sigs": sigc}, ensure_ascii=False)

feat_rows = "".join(
    f"<tr><td>{k}</td><td class=n>{pct(v['limitup'],0)}</td><td class=n>{pct(v['base'],0)}</td><td class=n><b>{v['lift']:.1f}배</b></td></tr>"
    for k, v in pre["features"].items())
sig_rows = ""
for i, s in enumerate(sigs):
    lw = s["lu_within"]
    sig_rows += (f"<tr><td>{s['name']}</td><td class=n>{s['n']:,}</td><td class=n>{pct(lw['1일'])}</td><td class=n>{pct(lw['3일'])}</td>"
                 f"<td class=n>{pct(lw['5일'])}</td><td class=n><b>{pct(lw['10일'])}</b></td>"
                 f"<td class=n>{lw['10일']/sigs[0]['lu_within']['10일']:.1f}배</td><td class=n>{pct(s['ld_within10'])}</td></tr>")
days_rows = ""
for i, s in enumerate(sigs[1:], 1):
    tot = sum(s["days_to_lu"].values())
    cum, c3 = 0, None
    for k in range(1, 11):
        cum += s["days_to_lu"][str(k)]
        if k == 3:
            c3 = cum / tot
    d1 = s["days_to_lu"]["1"] / tot
    days_rows += (f"<tr><td>{sig_short[i]}</td><td class=n>{pct(d1,0)}</td><td class=n>{pct(c3,0)}</td>"
                  f"<td class=n>{s['vr_med']:.1f}배</td><td class=n>{s['vr_winners_med']:.1f}배</td><td class=n>{s['vr_losers_med']:.1f}배</td></tr>")
stop_cols = ["-5%", "-7%", "-10%", "-15%", "손절 없음"]
ev_rows = ""
for i, s in enumerate(sigs):
    cells = ""
    best = max(stop_cols, key=lambda c: s["sim"][c]["mean"])
    for c in stop_cols:
        v = s["sim"][c]["mean"]
        cls = "pos" if v > 0 else "neg"
        cells += f"<td class='n {cls}'>{'<b>' if c == best else ''}{pct(v,2,True)}{'</b>' if c == best else ''}</td>"
    ev_rows += f"<tr><td>{sig_short[i]}</td>{cells}</tr>"
surv_rows = ""
for i, s in enumerate(sigs[1:], 1):
    w = s["winner_survive"]
    surv_rows += (f"<tr><td>{sig_short[i]}</td>" + "".join(f"<td class=n>{pct(w[c],0)}</td>" for c in ["-5%", "-7%", "-10%", "-15%", "-20%"])
                  + f"<td class=n>{pct(s['sim']['-10%']['stop_exit'],0)}</td></tr>")
gap_rows = ""
for i, s in enumerate(sigs):
    g = s["sim"]
    gap_rows += (f"<tr><td>{sig_short[i]}</td>" + "".join(
        f"<td class=n>{pct(g[c]['gap_stop'],1)} <span class=dim>({pct(g[c]['gap_loss_med'],1,True)})</span></td>" for c in ["-5%", "-10%", "-15%"])
        + f"<td class='n neg'>{pct(g['-10%']['worst'],0,True)}</td></tr>")
vol_rows = "".join(f"<tr><td>{r.vb}</td><td class=n>{r.n:,}</td><td class=n><b>{pct(r.next_lu,1)}</b></td><td class=n>{pct(r.next_ret,1,True)}</td><td class=n>{pct(r.f20,1,True)}</td></tr>"
                   for r in vol.itertuples())
mon = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]
cal_rows = "".join(f"<tr><td>{int(m)}월</td><td class=n>{cal['lu_by_month'][m]*1000:.2f}</td><td class=n>{cal['ld_by_month'][m]*10000:.2f}</td></tr>" for m in mon)
F = sigs[6]
A = sigs[1]

HTML = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>상한가 전조와 진입·손절 전략 분석</title>
<style>
.viz-root{{color-scheme:light;--surface-1:#fcfcfb;--page:#f9f9f7;--text-primary:#0b0b0b;--text-secondary:#52514e;--muted:#898781;
--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);--series-1:#2a78d6;--series-2:#eb6834;--good:#006300;--bad:#d03b3b}}
@media (prefers-color-scheme:dark){{:root:where(:not([data-theme="light"])) .viz-root{{color-scheme:dark;--surface-1:#1a1a19;--page:#0d0d0d;
--text-primary:#f0efec;--text-secondary:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--series-1:#3987e5;--series-2:#d95926;--good:#0ca30c;--bad:#e66767}}}}
:root[data-theme="dark"] .viz-root{{color-scheme:dark;--surface-1:#1a1a19;--page:#0d0d0d;--text-primary:#f0efec;--text-secondary:#c3c2b7;--grid:#2c2c2a;
--axis:#383835;--border:rgba(255,255,255,.10);--series-1:#3987e5;--series-2:#d95926;--good:#0ca30c;--bad:#e66767}}
*{{box-sizing:border-box}} body{{margin:0}}
.viz-root{{background:var(--page);color:var(--text-primary);font:15px/1.6 system-ui,-apple-system,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif;min-height:100vh}}
main{{max-width:1040px;margin:0 auto;padding:32px 20px 64px}}
h1{{font-size:28px;margin:0 0 4px}} h2{{font-size:20px;margin:40px 0 8px}} h3{{font-size:16px;margin:18px 0 6px}}
.sub{{color:var(--text-secondary);margin:0 0 20px}}
.card{{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:18px 20px;margin:14px 0}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}
.tile{{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:14px 16px}}
.tile .v{{font-size:26px;font-weight:650}} .tile .l{{color:var(--text-secondary);font-size:13px}}
table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{padding:7px 8px;border-bottom:1px solid var(--grid);text-align:left;vertical-align:top}}
th{{color:var(--text-secondary);font-weight:600;font-size:13px}}
td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
td.pos{{color:var(--good)}} td.neg{{color:var(--bad)}} .dim{{color:var(--muted);font-size:12px}}
.scroll{{overflow-x:auto}} .note{{color:var(--text-secondary);font-size:13px}}
.legend{{display:flex;gap:16px;font-size:13px;color:var(--text-secondary);margin:4px 0 8px}}
.legend i{{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px}}
ul.k li{{margin:6px 0}}
.callout{{border-left:3px solid var(--series-1);padding:4px 0 4px 14px;margin:12px 0}}
.warn{{border-left:3px solid var(--bad);padding:4px 0 4px 14px;margin:12px 0}}
.tip{{position:fixed;pointer-events:none;background:var(--surface-1);color:var(--text-primary);border:1px solid var(--border);border-radius:8px;padding:8px 10px;font-size:13px;box-shadow:0 4px 16px rgba(0,0,0,.12);display:none;z-index:9;white-space:nowrap}}
svg text{{fill:var(--muted);font-size:11px;font-family:inherit}} svg .lab{{fill:var(--text-secondary);font-size:12px}}
</style></head><body><div class="viz-root"><main>
<h1>상한가 전조와 진입·손절 전략 분석</h1>
<p class="sub">2023-11-13 ~ 2026-11-13 · 코스피·코스닥 보통주 · 진입은 신호일 종가, 이후 최대 10거래일 관찰</p>

<div class="tiles">
 <div class="tile"><div class="v">{pct(1-pre['features']['D-5~D-1 중 거래량 3배 이상 하루 이상']['limitup'],0)}</div><div class="l">첫 상한가 직전 5일 동안 거래량 3배 넘게 터진 날이 하루도 없던 비율</div></div>
 <div class="tile"><div class="v">{pre['by_day']['D-1']['vr_med']:.2f}배</div><div class="l">상한가 전날 거래량 (20일 평균 대비, 중앙값)</div></div>
 <div class="tile"><div class="v">{pre['lu_day_vr']['0.5']:.0f}배</div><div class="l">상한가 당일 거래량 (중앙값)</div></div>
 <div class="tile"><div class="v">{pct(sigs[0]['lu_within']['10일'])}</div><div class="l">아무 종목이나 샀을 때 10일 안에 상한가 갈 확률 (기준선)</div></div>
</div>

<h2>결론부터</h2>
<div class="card"><ul class="k">
<li><b>상한가의 대부분은 차트로 미리 알 수 없습니다.</b> 첫 상한가 종목의 전날 거래량은 평소 수준(중앙값 {pre['by_day']['D-1']['vr_med']:.2f}배)이고, {pct(pre['quiet_share'],0)}는 직전 5일 동안 거래량도 주가도 조용했습니다. 상한가는 <b>당일 장중에 나온 공시·기사·테마 확산</b>으로 터지는 경우가 대부분입니다.</li>
<li><b>그래도 흔적은 있습니다.</b> 직전 5일 안에 장중 +15% 터치, 거래량 2~5배 급증, +10% 상승일이 있던 비율이 평소보다 2~3배 높습니다. 다만 이런 흔적이 있어도 실제로 10일 안에 상한가를 가는 건 <b>4~9%</b>뿐입니다.</li>
<li><b>차트 신호만으로 들어가면 기대수익이 0 근처이거나 마이너스입니다.</b> 상한가 확률은 기준선의 2~5배로 높아지지만, 상한가를 못 간 경우의 손실이 그 이익을 상쇄합니다. 특히 '상한가 실패한 급등주', '윗꼬리 단 종목', '상한가 다음 날 추격'은 모든 손절 설정에서 손실이었습니다.</li>
<li><b>유일하게 플러스였던 건 '상한가 당일 종가 매수 + -5% 손절'(평균 {pct(F['sim']['-5%']['mean'],1,True)})입니다.</b> 그런데 상한가에 매수 주문이 쌓여 있으면 체결 자체가 어렵습니다. 체결이 잘 되는 날은 오히려 상한가가 풀릴 위험이 큰 날이라, 실제 수익은 이보다 낮을 가능성이 큽니다.</li>
<li><b>손절은 -10% 전후가 타협점이지만, 손절가대로 팔리지 않을 위험이 실재합니다.</b> 3~9%의 거래는 손절가 아래에서 시가가 시작(갭 하락)해 손절가보다 더 손해 보고 팔렸습니다. 하한가로 마감한 날의 {pct(ld['lock_share'],0)}는 하한가에 매도 주문이 쌓여 <b>아예 팔 수 없는 상태</b>였습니다.</li>
</ul></div>

<h2>1. 상한가 전에 어떤 움직임이 있었나</h2>
<div class="card">
<h3>첫 상한가 D-10 ~ D-1: 거래량 (20일 평균 대비, 중앙값)</h3>
<div id="c-pre"></div>
<p class="note">상한가 직전 10일 동안 거래량은 오히려 평소보다 적습니다(0.6~0.7배). 전날 겨우 평균 수준(0.95배)으로 올라오고, 당일 {pre['lu_day_vr']['0.5']:.0f}배로 폭발합니다. '조용하다가 갑자기'가 전형적인 패턴입니다.</p>
</div>
<div class="card scroll">
<h3>직전 5일 흔적: 상한가 종목 vs 평소</h3>
<table><tr><th>흔적</th><th class=n>첫 상한가 종목</th><th class=n>평소 (임의의 날)</th><th class=n>배율</th></tr>{feat_rows}</table>
<p class="note">'장중 +15% 터치'가 가장 강한 전조(3.0배)입니다. 누군가 먼저 사고 있다는 신호일 수 있습니다. 하지만 상한가 종목의 4분의 3은 이런 흔적 없이 바로 상한가를 갔습니다.</p>
</div>

<h2>2. 공시·기사·예정 일정</h2>
<div class="card"><ul class="k">
<li><b>공시형 (당일 장중 공시 → 즉시 상한가):</b> 단일판매·공급계약(시총 대비 대형 수주, 금호건설 사례), 무상증자, 자사주 소각, 최대주주 변경·M&A, 최대주주의 유상증자 참여, 기술이전·FDA 허가(HLB 그룹주 10곳 동시 상한가). 공시 시각에 바로 오르기 때문에 미리 사 둔 사람만 이득을 봅니다.</li>
<li><b>기사·리포트형:</b> 증권사 첫 리포트(효성화학), 정부 정책(메가프로젝트, 반도체 클러스터 → 서산·금호건설·금호전기), 해외 이슈(미국 광통신·양자컴퓨터·MS 실적 → 국내 관련주 동조).</li>
<li><b>테마·수급형 (공시 없음):</b> 품절주(유통주식이 적은 종목), 우선주, 정치 테마, 동전주. 상한가 기사에서 '뚜렷한 재료 없이'라고 나오는 종목들로, 지수가 폭락한 날 오히려 몰립니다(2026년 7월 7일·28일).</li>
<li><b>예정된 일정형:</b> 학회 임상 발표(ASCO·ESMO·CTAD 등), 실적 발표, FDA 결정일, 공개매수. 일정은 미리 알 수 있지만 결과는 모릅니다. 기대감에 미리 오르고 발표 당일 '재료 소멸'로 빠지는 경우가 흔합니다.</li>
<li><b>실적 시즌 효과는 없었습니다.</b> 분기·연간 실적 공시 시즌의 상한가 발생률(하루·종목당 {cal['lu_rate_season']*1000:.2f}‰)은 그 외 기간({cal['lu_rate_other']*1000:.2f}‰)과 같습니다. 달력보다 개별 재료가 중요합니다.</li>
<li><b>미공개정보 주의:</b> 공시 직전의 거래량 급증은 내부자 거래일 수 있고, 실제로 금융당국 적발 사례가 이어지고 있습니다. 이런 정보를 듣고 매매하면 불법입니다.</li>
</ul>
<p class="note">공시와 상한가를 1:1로 붙이는 정량 분석에는 DART(전자공시) API 키가 필요합니다. 위 분류는 상한가 기사 표본을 바탕으로 정리했습니다.</p></div>

<h2>3. 진입 신호별 백테스트</h2>
<div class="card">
<h3>10일 안에 상한가 갈 확률</h3>
<div id="c-sig"></div>
</div>
<div class="card scroll"><table>
<tr><th>신호 (신호일 종가 매수)</th><th class=n>건수</th><th class=n>1일 내</th><th class=n>3일 내</th><th class=n>5일 내</th><th class=n>10일 내</th><th class=n>기준 대비</th><th class=n>10일 내 하한가</th></tr>
{sig_rows}</table>
<p class="note">A~D는 시가총액 3천억 미만 소형주만 대상입니다. '고가권 마감'은 당일 고가·저가 범위의 상위 30% 안에서 끝났다는 뜻입니다.</p>
</div>
<div class="card scroll">
<h3>상한가는 며칠 안에 왔나 · 거래량은 얼마였나</h3>
<table><tr><th>신호</th><th class=n>상한가 중 1일차</th><th class=n>3일 안 누적</th><th class=n>신호일 거래량</th><th class=n>성공 종목</th><th class=n>실패 종목</th></tr>{days_rows}</table>
<p class="note">10일 안에 상한가를 간 경우 절반 정도는 3일 안에 갔습니다. <b>3일 안에 안 가면 확률이 빠르게 떨어집니다.</b> 신호일 거래량은 성공·실패 간 차이가 거의 없어서 거래량만으로는 걸러지지 않습니다.</p>
</div>

<h3>상한가 당일 거래량이 적을수록 다음 날도 상한가</h3>
<div class="card scroll"><table>
<tr><th>첫 상한가 당일 거래량 (20일 평균 대비)</th><th class=n>건수</th><th class=n>다음 날 또 상한가</th><th class=n>다음 날 종가 중앙값</th><th class=n>20일 후 중앙값</th></tr>{vol_rows}</table>
<p class="note">거래량이 적은 상한가는 팔려는 사람이 적고 일찍 잠겼다는 뜻입니다. 이런 상한가는 다음 날도 상한가 갈 확률이 18%로, 거래량이 40배 넘게 터진 상한가(6%)의 3배입니다. 거래량이 폭발한 상한가는 차익 실현 매물이 많았다는 신호입니다.</p></div>

<h2>4. 손절선은 어디에</h2>
<div class="card scroll">
<h3>손절선별 1회 평균 수익률 (최대 10일 보유)</h3>
<table><tr><th>신호</th><th class=n>-5% 손절</th><th class=n>-7%</th><th class=n>-10%</th><th class=n>-15%</th><th class=n>손절 없음</th></tr>{ev_rows}</table>
<p class="note">규칙: 시가가 손절가 아래면 시가에 매도, 장중 손절가를 건드리면 손절가에 매도, 상한가로 마감하면 그날 종가에 매도, 10일째 종가에 매도. 수수료·세금(약 0.2%)과 체결 실패는 반영하지 않았습니다. 굵은 글씨는 신호별 최선의 손절선입니다.</p>
</div>
<div class="card scroll">
<h3>너무 좁은 손절은 '될 놈'도 털어냅니다</h3>
<table><tr><th>신호</th><th class=n>-5%</th><th class=n>-7%</th><th class=n>-10%</th><th class=n>-15%</th><th class=n>-20%</th><th class=n>-10% 손절 발동률</th></tr>{surv_rows}</table>
<p class="note">표의 숫자는 결국 상한가를 간 종목 중 상한가 전까지 해당 손절선을 건드리지 않은 비율입니다. 예를 들어 A 신호에서 -5% 손절을 쓰면, 결국 상한가 간 종목의 절반 가까이를 그 전에 손절했습니다. -10%면 약 80%가 살아남고, -15%면 90% 이상이 살아남습니다.</p>
</div>
<div class="callout"><b>손절선 가이드</b><br>
· 거래량 동반 초기 돌파(A·B)에 진입: <b>-10%</b>가 균형점입니다. 상한가 간 종목의 약 80%를 지키면서 기대값이 플러스입니다.<br>
· 상한가 당일 종가에 진입(F): <b>-5% 손절 + 다음 날 상한가 못 가면 정리</b>가 가장 나았습니다. 다음 날 시가가 평균 +6% 갭 상승하므로 손절보다 익절할 기회가 먼저 옵니다.<br>
· 이미 크게 오른 종목(C·D·E)은 손절선을 어떻게 잡아도 마이너스였습니다. <b>진입하지 않는 게 최선</b>입니다.<br>
· 시간 손절: 진입 후 <b>3거래일 안에 움직임이 없으면 정리</b>하는 게 좋습니다. 상한가는 대부분 초반에 옵니다.</div>

<h2>5. 손절이 안 되고 하한가로 갈 수 있나</h2>
<div class="tiles">
 <div class="tile"><div class="v">{ld['events']}건</div><div class="l">3년간 보통주 하한가 마감 ({ld['stocks']}종목). 상한가의 약 {ld['per_lu_ratio']*100:.0f}% 규모</div></div>
 <div class="tile"><div class="v">{pct(ld['lock_share'],0)}</div><div class="l">하한가 날 중 하한가에 잠긴 채 마감한 비율 (팔 수 없음)</div></div>
 <div class="tile"><div class="v">{pct(ld['next_ld_rate'],0)}</div><div class="l">하한가 다음 날도 하한가</div></div>
 <div class="tile"><div class="v">{pct(ld['after_lu10'],1)}</div><div class="l">상한가 이후 10일 안에 하한가</div></div>
</div>
<div class="card scroll">
<h3>손절가 아래로 갭 하락해서 시작한 비율 (괄호: 그때 실제 손실 중앙값)</h3>
<table><tr><th>신호</th><th class=n>-5% 손절</th><th class=n>-10% 손절</th><th class=n>-15% 손절</th><th class=n>-10% 손절 최악</th></tr>{gap_rows}</table>
<p class="note">손절가를 정해도 3~9%의 거래에서는 다음 날 아침 손절가 아래로 시작해서 손절가보다 1~2%p 더 손해를 봤습니다. 최악의 경우(하한가 연속, 거래정지 후 재개)는 -10% 손절을 걸어도 <b>-50% 이상</b> 손실이 났습니다.</p>
</div>
<div class="warn"><b>하한가 위험이 큰 상황</b><br>
· <b>상한가 직후:</b> 상한가 종가 기준으로 이후 10일 안의 최저점이 중앙값 {pct(ld['after_lu_low10']['p50'],0,True)}, 하위 10%는 {pct(ld['after_lu_low10']['p10'],0,True)}까지 빠졌습니다.<br>
· <b>2~3월 감사보고서 시즌:</b> 감사의견 거절·상장폐지 사유가 이 시기에 나옵니다. 하한가 발생률이 연중 가장 높은 구간 중 하나입니다(7월 폭락장 다음).<br>
· <b>관리종목·적자 지속·잦은 유상증자 종목:</b> 상한가 단골이면서 하한가와 거래정지 위험도 가장 큽니다.<br>
· <b>재료 소멸:</b> 임상 결과 실패, 수주 계약 해지, 최대주주 변경 무산 같은 공시는 바로 하한가로 이어지고, 대부분 하한가에 잠겨 매도할 수 없습니다.<br>
· 이 분석은 상장폐지된 종목이 빠져 있어서 <b>실제 하한가·거래정지 위험은 여기 숫자보다 큽니다.</b></div>

<div class="card scroll"><h3>월별 발생률 (하루·종목당)</h3>
<table style="max-width:420px"><tr><th>월</th><th class=n>상한가 (‰)</th><th class=n>하한가 (‱)</th></tr>{cal_rows}</table>
<p class="note">‰는 1,000분의 1, ‱는 10,000분의 1입니다. 상한가는 4월에 가장 많고 9~11월에 적습니다. 하한가는 2~3월과 7월(2026년 폭락장)에 높습니다.</p></div>

<h2>6. 실전 체크리스트</h2>
<div class="card"><ol>
<li><b>재료부터 확인:</b> 오늘 공시나 기사가 있는지, 시가총액 대비 크기가 의미 있는지(수주라면 시총의 30% 이상) 봅니다. 재료 없는 테마 수급 상한가는 지속성이 낮습니다.</li>
<li><b>시가총액·주가:</b> 3천억 원 미만, 52주 고점 대비 크게 빠진 종목에서 상한가가 잦습니다. 대신 하한가 위험도 같이 큽니다.</li>
<li><b>진입 시점:</b> 장중 +15%를 터치했다가 밀린 종목, 이미 +15~29% 오른 종목을 다음 날 추격하는 건 통계적으로 손실이었습니다.</li>
<li><b>상한가 당일 거래량:</b> 적게 터지고 일찍 잠긴 상한가가 다음 날에도 강합니다. 거래량이 40배 넘게 폭발한 상한가는 이미 손바뀜이 끝났다는 신호입니다.</li>
<li><b>손절:</b> -10%(초기 진입) 또는 -5%(상한가 추격)와 함께 3일 시간 손절. 손절가는 미리 주문으로 걸어 두되, 갭 하락으로 손절가보다 더 손해 볼 수 있다는 걸 감안해서 포지션 크기를 정합니다.</li>
<li><b>비중:</b> 하한가가 연속으로 나오거나 거래정지가 되면 손절이 아예 안 됩니다. <b>한 종목 손실이 전체 자산의 1~2%를 넘지 않도록</b> 비중을 잡습니다. 예를 들어 -10% 손절이면 종목당 비중을 10~20% 이하로, 최악의 -50%까지 감안하면 그보다 더 작게 잡습니다.</li>
<li><b>매도:</b> 상한가 다음 날은 77% 확률로 갭 상승해서 시작하고, 20일 뒤에는 68%가 상한가 가격보다 아래에 있습니다. <b>다음 날 아침 갭 상승 구간에서 분할 매도</b>하는 게 유리했습니다.</li>
</ol></div>

<h2>방법과 한계</h2>
<div class="card note"><ul>
<li>Yahoo Finance 일봉 기준입니다. 장중 시각(몇 시에 상한가에 잠겼는지)과 호가 잔량은 없어서 '체결 가능 여부'는 반영하지 못했습니다.</li>
<li>상장폐지 종목이 빠져 있어(생존 편향) 손실과 하한가 위험이 과소평가돼 있습니다.</li>
<li>수수료·세금, 슬리피지는 반영하지 않았습니다. 수익률이 1% 미만인 플러스 결과는 실전에서 사라질 수 있습니다.</li>
<li>과거 통계이고 투자 권유가 아닙니다.</li>
</ul></div>
</main><div class="tip" id="tip"></div></div>
<script>
const D={DATA};
const css=n=>getComputedStyle(document.querySelector('.viz-root')).getPropertyValue(n).trim();
const tip=document.getElementById('tip');
function showTip(e,h){{tip.innerHTML=h;tip.style.display='block';tip.style.left=Math.min(e.clientX+14,innerWidth-tip.offsetWidth-8)+'px';tip.style.top=(e.clientY+14)+'px'}}
function hideTip(){{tip.style.display='none'}}
const NS='http://www.w3.org/2000/svg';
function el(t,a,p){{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);if(p)p.appendChild(e);return e}}
const pct=(v,d=1)=>(v*100).toFixed(d)+'%';
function bar(x,y,w,h,fill,p,r=4){{if(h<=0)return;r=Math.min(r,w/2,h);
 return el('path',{{d:`M${{x}},${{y+h}}V${{y+r}}Q${{x}},${{y}} ${{x+r}},${{y}}H${{x+w-r}}Q${{x+w}},${{y}} ${{x+w}},${{y+r}}V${{y+h}}Z`,fill}},p)}}
function hbar(x,y,w,h,fill,p,r=4){{if(w<=0)return;r=Math.min(r,h/2,w);
 return el('path',{{d:`M${{x}},${{y}}H${{x+w-r}}Q${{x+w}},${{y}} ${{x+w}},${{y+r}}V${{y+h-r}}Q${{x+w}},${{y+h}} ${{x+w-r}},${{y+h}}H${{x}}Z`,fill}},p)}}
function preChart(){{const box=document.getElementById('c-pre');box.innerHTML='';
 const W=box.clientWidth,H=220,m={{l:40,r:8,t:16,b:26}},s=el('svg',{{width:W,height:H}},box);
 const data=D.days,max=1.2,iw=W-m.l-m.r,ih=H-m.t-m.b,y=v=>m.t+ih-v/max*ih,bw=iw/data.length;
 [0,0.4,0.8,1.2].forEach(v=>{{el('line',{{x1:m.l,x2:W-m.r,y1:y(v),y2:y(v),stroke:css(v?'--grid':'--axis')}},s);
  el('text',{{x:m.l-6,y:y(v)+4,'text-anchor':'end'}},s).textContent=v.toFixed(1)+'배'}});
 el('line',{{x1:m.l,x2:W-m.r,y1:y(1),y2:y(1),stroke:css('--muted'),'stroke-dasharray':'4 4'}},s);
 el('text',{{x:W-m.r,y:y(1)-4,'text-anchor':'end'}},s).textContent='평소 수준';
 data.forEach((d,i)=>{{const x=m.l+i*bw+bw*0.2,w=bw*0.6;bar(x,y(d.vr),w,m.t+ih-y(d.vr),css('--series-1'),s);
  el('text',{{x:x+w/2,y:H-8,'text-anchor':'middle',class:'lab'}},s).textContent=d.k;
  el('text',{{x:x+w/2,y:y(d.vr)-4,'text-anchor':'middle'}},s).textContent=d.vr.toFixed(2);
  const h=el('rect',{{x:m.l+i*bw,y:m.t,width:bw,height:ih,fill:'transparent'}},s);
  h.addEventListener('mousemove',e=>showTip(e,`<b>${{d.k}}</b><br>거래량 중앙값 ${{d.vr.toFixed(2)}}배<br>3배 이상 급증 ${{pct(d.vr3)}}<br>+10% 이상 상승 ${{pct(d.up10)}}`));
  h.addEventListener('mouseleave',hideTip)}})}}
function sigChart(){{const box=document.getElementById('c-sig');box.innerHTML='';
 const data=D.sigs,W=box.clientWidth,row=30,m={{l:140,r:150,t:4,b:4}},H=m.t+m.b+row*data.length,s=el('svg',{{width:W,height:H}},box);
 const max=Math.max(...data.map(d=>d.lu10)),iw=W-m.l-m.r;
 data.forEach((d,i)=>{{const y0=m.t+i*row;
  el('text',{{x:m.l-8,y:y0+row/2+4,'text-anchor':'end',class:'lab'}},s).textContent=d.k;
  hbar(m.l,y0+7,d.lu10/max*iw,row-14,css(i?'--series-1':'--muted'),s);
  const t=el('text',{{x:m.l+d.lu10/max*iw+6,y:y0+row/2+4,class:'lab'}},s);t.textContent=pct(d.lu10)+'  ·  기대값 '+(d.ev>0?'+':'')+pct(d.ev,2);
  const h=el('rect',{{x:0,y:y0,width:W,height:row,fill:'transparent'}},s);
  h.addEventListener('mousemove',e=>showTip(e,`<b>${{d.k}}</b><br>10일 내 상한가 ${{pct(d.lu10)}}<br>-10% 손절 시 평균 수익 ${{(d.ev>0?'+':'')+pct(d.ev,2)}}`));
  h.addEventListener('mouseleave',hideTip)}})}}
function draw(){{preChart();sigChart()}}draw();addEventListener('resize',draw);
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',draw);
</script></body></html>"""
with open(os.path.join(ROOT, "report", "entry.html"), "w", encoding="utf-8") as f:
    f.write(HTML)
print("ok")
