"""data/refine_summary.json -> report/refine.html"""
import json
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")
d = json.load(open(os.path.join(ROOT, "data", "refine_summary.json"), encoding="utf-8"))
style = re.search(r"<style>.*?</style>", open(os.path.join(ROOT, "report", "entry.html"), encoding="utf-8").read(), re.S).group(0)
T = d["timing"]


def pct(x, k=1, sign=False):
    if x is None:
        return "-"
    return f"{x*100:+.{k}f}%" if sign else f"{x*100:.{k}f}%"


def cell(s, key="mean"):
    if s is None:
        return "<td class=n>-</td>"
    v = s[key]
    cls = "pos" if v > 0 else "neg"
    return f"<td class='n {cls}'>{pct(v,2,True)}</td>"


def timing_table(sname, note=""):
    rows = ""
    for en, row in T[sname].items():
        if en.startswith("_"):
            continue
        x1, x2 = row["X1"], row["X2"]
        both = x2["train"] and x2["test"] and x2["train"]["mean"] > 0 and x2["test"]["mean"] > 0
        rows += (f"<tr><td>{'<b>' if both else ''}{en}{'</b>' if both else ''}</td>"
                 f"<td class=n>{pct(x2['train']['fill_rate'],0)}</td>"
                 f"{cell(x1['train'])}{cell(x1['test'])}{cell(x2['train'])}{cell(x2['test'])}"
                 f"<td class=n>{pct(x2['test']['win'],0)}</td><td class=n>{pct(x2['test']['lu_hit'],1)}</td></tr>")
    return (f"<div class='card scroll'><h3>{sname}</h3><table><tr><th>진입 방법</th><th class=n>체결률</th>"
            f"<th class=n>X1 개발</th><th class=n>X1 검증</th><th class=n>X2 개발</th><th class=n>X2 검증</th>"
            f"<th class=n>승률(검증)</th><th class=n>상한가 도달(검증)</th></tr>{rows}</table>"
            f"<p class=note>X1 = 상한가 마감일 종가에 매도, X2 = 상한가 다음 날 시가에 매도. 1회 평균 수익률(비용 0.25% 차감). "
            f"굵은 글씨는 개발·검증 구간 모두 플러스(X2 기준)인 진입 방법입니다. {note}</p></div>")


def regime_table():
    rows = ""
    for sname in T:
        rg = T[sname]["_regime"]
        rows += (f"<tr><td>{sname}</td>{cell(rg['above']['train'])}{cell(rg['below']['train'])}"
                 f"{cell(rg['above']['test'])}{cell(rg['below']['test'])}</tr>")
    return rows


kq = d["lu_rate_by_kq_day"]
kq_rows = "".join(f"<tr><td>{k}</td><td class=n>{v['days']}</td><td class=n>{v['lu_rate']*1000:.2f}‰</td></tr>" for k, v in kq.items())
r20 = d["lu_per_day_by_r20"]
r20_rows = "".join(f"<tr><td>{k}</td><td class=n>{v['size']}</td><td class=n>{v['mean']:.1f}개</td></tr>" for k, v in r20.items())
fr = d["first_lu_by_regime"]
fr_rows = "".join(f"<tr><td>{k}</td><td class=n>{v['n']:,}</td><td class=n>{pct(v['next_lu'],1)}</td><td class=n>{pct(v['fwd5'],1,True)}</td><td class=n>{pct(v['fwd10'],1,True)}</td></tr>" for k, v in fr.items())
fk = d["first_lu_by_kq_day"]
fk_rows = "".join(f"<tr><td>{k}</td><td class=n>{v['n']:,}</td><td class=n>{pct(v['next_lu'],1)}</td><td class=n>{pct(v['fwd5'],1,True)}</td></tr>" for k, v in fk.items())
reg = d["lu_per_day_by_regime"]
A = T["A. 거래량 3배↑+5~15% 상승+고가권 마감"]
L2 = T["L2. 첫 상한가 + 당일 거래량 7배 미만"]

HTML = f"""<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>상한가 전략 다듬기: 지수·진입 타이밍·검증</title>{style}</head>
<body><div class="viz-root"><main>
<h1>상한가 전략 다듬기: 지수 · 진입 타이밍 · 검증</h1>
<p class="sub">개발 구간 {d['split']['train'][0]} ~ 2025-10-31 · 검증 구간 {d['split']['test'][0]} ~ {d['split']['test'][1]} · 손절 -10%, 최대 10거래일 보유, 왕복 비용 0.25% 반영</p>

<h2>결론부터</h2>
<div class="card"><ul class="k">
<li><b>지수 방향은 상한가 발생과 거의 무관합니다.</b> 코스닥이 20일선 위든 아래든 하루 상한가 수는 같았습니다({reg['true']:.1f}개 vs {reg['false']:.1f}개). 여기까지는 생각하신 게 맞습니다.</li>
<li><b>하지만 지수의 '변동성'은 관련 있습니다.</b> 코스닥이 하루 +3% 이상 급등한 날은 상한가가 평소의 2배, -3% 이상 급락한 날도 1.3배였습니다. 지수와 상한가 수의 상관은 방향(0.19)보다 등락폭 크기(0.30)와 더 컸습니다.</li>
<li><b>진입 후 성과는 지수 영향을 받습니다.</b> 거래량 돌파 신호(A)는 코스닥이 20일선 위일 때 개발·검증 두 구간 모두 더 좋았습니다(검증 {pct(A['_regime']['above']['test']['mean'],2,True)} vs {pct(A['_regime']['below']['test']['mean'],2,True)}). <b>지수 필터는 '상한가가 나올지'가 아니라 '들어가서 돈이 되는지'에 쓰는 겁니다.</b></li>
<li><b>매도는 상한가 다음 날 시가(X2)가 모든 신호·진입 방법에서 더 나았습니다.</b> 상한가 당일 종가 매도보다 1회 평균 0.2~2.9%p 개선됐고, 두 구간 모두에서 일관됐습니다.</li>
<li><b>진입 타이밍:</b> 돌파 신호(A)는 X2 매도 기준으로 거의 모든 진입 방법이 두 구간 모두 플러스였고, 신호일 종가·다음 날 확인 후 종가·-3% 눌림 지정가가 안정적이었습니다(1회 +0.5~1.2%). 반면 <b>상한가 종목을 다음 날 사는 건 시가·눌림 매수 모두 손실</b>이었습니다(-1~-5%). 유일한 예외는 '다음 날 종가가 상한가 가격 이상으로 버틸 때만 종가 매수'인데, 거래량 적은 상한가(L2)에서 두 구간 모두 소폭 플러스(+0.4%, +1.2%)였습니다. 다만 표본이 작습니다(200~340건).</li>
<li><b>가장 강한 결과는 '거래량 적은 첫 상한가를 상한가 종가에 매수'</b>(검증 {pct(L2['상한가 종가 (체결 가정)']['X2']['test']['mean'],1,True)})였지만, 바로 그 종목들이 매수 주문이 쌓여 체결이 안 되는 상한가입니다. 현실적으로 따라 하기 어려운 숫자로 봐야 합니다.</li>
</ul></div>

<h2>1. 지수가 상한가와 관련 있나</h2>
<div class="card scroll"><h3>코스닥 당일 등락별 상한가 발생률 (종목·일당)</h3>
<table style="max-width:520px"><tr><th>코스닥 당일</th><th class=n>거래일</th><th class=n>상한가 발생률</th></tr>{kq_rows}</table>
<p class="note">U자 모양입니다. 지수가 크게 움직이는 날(위든 아래든) 상한가가 많습니다. 급락일 상한가는 대형주에서 빠진 돈이 소형 테마주로 몰리는 '역주행'(2026년 7월 7일·28일 사례)이고, 급등일 상한가는 반도체 등 주도 테마의 동반 상승입니다.</p></div>
<div class="card scroll"><h3>코스닥 20일 수익률 구간별 하루 평균 상한가 수</h3>
<table style="max-width:520px"><tr><th>코스닥 직전 20일</th><th class=n>거래일</th><th class=n>하루 평균 상한가</th></tr>{r20_rows}</table>
<p class="note">시장이 한 달 새 ±10% 넘게 움직인 극단적인 국면에서 상한가가 약 1.6배 많았습니다. 방향보다 '얼마나 요동치는가'가 중요합니다.</p></div>
<div class="card scroll"><h3>첫 상한가 이후 흐름: 지수 국면별</h3>
<table><tr><th>상한가 당일 코스닥</th><th class=n>건수</th><th class=n>다음 날 또 상한가</th><th class=n>5일 후</th><th class=n>10일 후</th></tr>{fr_rows}</table>
<table style="margin-top:12px"><tr><th>상한가 당일 코스닥 등락</th><th class=n>건수</th><th class=n>다음 날 또 상한가</th><th class=n>5일 후 (중앙값)</th></tr>{fk_rows}</table>
<p class="note">지수 급락일에 나온 상한가는 다음 날 연속 상한가 확률이 16%로 높지만, 5일 뒤에는 -7.7%로 가장 많이 빠졌습니다. 폭락장의 역주행 상한가는 짧고 강하게 끝납니다. 지수가 오르는 날 나온 상한가는 5일 뒤 하락폭이 거의 없었습니다(-0.1~-0.2%).</p></div>
<div class="card scroll"><h3>신호별 성과: 코스닥 20일선 위 vs 아래</h3>
<table><tr><th>신호</th><th class=n>위 (개발)</th><th class=n>아래 (개발)</th><th class=n>위 (검증)</th><th class=n>아래 (검증)</th></tr>{regime_table()}</table>
<p class="note">A·B는 신호일 종가 진입, L·L2는 다음 날 시가 진입이고, 모두 X2 매도 기준입니다. 돌파 신호(A·B)는 두 구간 모두 '20일선 위'가 우세했습니다.</p></div>

<h2>2. 진입 타이밍 비교</h2>
{timing_table("A. 거래량 3배↑+5~15% 상승+고가권 마감", "대상은 시가총액 3천억 미만 보통주입니다.")}
{timing_table("B. A + 52주 고점 대비 -40% 이하", "개발 구간에서는 A보다 좋았지만 검증 구간에서 대부분 약해졌습니다. 낙폭 과대 조건은 과거에만 맞았을 가능성이 있어 채택하지 않는 게 안전합니다.")}
{timing_table("L. 첫 상한가")}
{timing_table("L2. 첫 상한가 + 당일 거래량 7배 미만", "'상한가 종가' 행은 체결된다고 가정한 숫자입니다. 거래량 적은 상한가는 매수 잔량이 쌓여 대부분 체결되지 않으므로 실전 수익은 훨씬 낮습니다.")}

<div class="callout"><b>다듬어진 전략 후보</b><br>
· <b>진입:</b> 시가총액 3천억 미만, 거래량 20일 평균 3배 이상, +5~15% 상승, 고가권 마감 → 신호일 종가 또는 다음 날 -3% 눌림 지정가(3일 대기)<br>
· <b>필터:</b> 코스닥 20일선 위일 때만<br>
· <b>청산:</b> 상한가 오면 다음 날 시가 매도, -10% 손절, 10거래일 시간 청산<br>
· <b>기대값:</b> 1회 평균 약 +0.8~1.0%(비용 차감 후, 신호일 종가 진입·20일선 위 기준), 승률 약 40%. 즉 10번 중 6번은 손실이고, 가끔 오는 큰 수익으로 만회하는 구조입니다.<br>
· 이 숫자도 생존 편향(상장폐지 종목 제외) 때문에 실제보다 낙관적입니다. 실전 투입 전 모의매매로 앞으로의 데이터를 확인해야 합니다.</div>

<h2>3. 매수 주체별 분석 (데이터 확보 필요)</h2>
<div class="card"><ul class="k">
<li>개인·외국인·기관 일별 순매수 데이터는 한국거래소(KRX) 정보데이터시스템에서만 받을 수 있고, 현재 로그인이 필요합니다. 클라우드 환경에서는 계정 비밀번호를 안전하게 넘겨받을 방법이 없어 분석하지 못했습니다.</li>
<li>저장소의 <code>scripts/fetch_investor_local.py</code>를 KRX 계정으로 로컬 PC에서 실행하면 상한가 종목의 D-10~D+5 투자자별 순매수가 <code>data/investor_flows.csv</code>로 저장됩니다. 이 파일을 올려 주시면 다음을 분석합니다.
<ol><li>상한가 전 외국인·기관 선취매(D-5~D-1 순매수)가 있었는지, 있었으면 성공률이 다른지</li>
<li>상한가 당일 매수 주체(개인 주도 vs 기관·외국인 동반)에 따른 다음 날·20일 후 성과</li>
<li>상한가 다음 날 누가 파는지(기관 차익 실현 vs 개인 투매)</li>
<li>위 돌파 전략에 '외국인·기관 순매수 동반' 필터를 붙였을 때 개발·검증 성과</li></ol></li>
</ul></div>

<h2>방법과 한계</h2>
<div class="card note"><ul>
<li>개발 구간에서 정한 조건을 검증 구간(최근 약 1년)에 그대로 적용했습니다. 검증 구간 결과를 본 뒤 조건을 다시 바꾸면 그때부터는 검증의 의미가 없어집니다.</li>
<li>눌림 지정가는 장중 저가가 지정가 이하면 체결된 것으로 봤습니다(시가가 이미 더 낮으면 시가 체결). 장중 진입일에는 진입일 종가로 손절·상한가 여부를 판단했습니다.</li>
<li>Yahoo 일봉 기준이고 상장폐지 종목은 빠져 있습니다. 과거 통계이고 투자 권유가 아닙니다.</li>
</ul></div>
</main></div></body></html>"""
with open(os.path.join(ROOT, "report", "refine.html"), "w", encoding="utf-8") as f:
    f.write(HTML)
print("ok")
