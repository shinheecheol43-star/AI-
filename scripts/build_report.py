"""data/summary.json -> report/index.html (단일 HTML, 인라인 SVG 차트)"""
import json
import os

ROOT = os.path.join(os.path.dirname(__file__), "..")
d = json.load(open(os.path.join(ROOT, "data", "summary.json"), encoding="utf-8"))

SEC_KO = {"Technology": "IT·반도체·전자", "Industrials": "산업재·건설·기계",
          "Healthcare": "헬스케어·바이오", "Consumer Cyclical": "경기소비재",
          "Basic Materials": "소재·화학", "Communication Services": "통신·미디어·게임",
          "Consumer Defensive": "필수소비재", "Financial Services": "금융",
          "Utilities": "유틸리티", "Real Estate": "부동산", "Energy": "에너지",
          "Unknown": "미분류"}

m = d["meta"]
fw = d["forward"]
pf = d["pre_features"]


def pct(x, digits=1, sign=False):
    if x is None:
        return "-"
    s = f"{x*100:+.{digits}f}%" if sign else f"{x*100:.{digits}f}%"
    return s


months = [{"k": k, "KOSDAQ": v.get("KOSDAQ", 0), "KOSPI": v.get("KOSPI", 0)}
          for k, v in sorted(d["by_month"].items())]
sectors = [{"name": SEC_KO.get(k, k), "events": v["events"], "stocks": v["stocks"],
            "universe": v["universe"], "hit": v["stock_hit_rate"],
            "per100": v["events_per_100"], "kq": v["kosdaq_share"],
            "next": v["next_ret_mean"], "f20": v["fwd_20d_median"],
            "y": d["sector_by_period"].get(k, {})}
           for k, v in d["by_sector"].items() if k != "Unknown"]
caps = [{"k": k, "ev": v["event_share"], "all": v["day_share"], "lift": v["lift"],
         "n": v["events"]} for k, v in d["by_cap"].items()]
dds = [{"k": k, "ev": v["limitup"], "all": v["all"]} for k, v in d["dd_bucket"].items()]
streak = d["streak_len"]
streak_total = sum(streak.values())
top = d["top_repeat_common"]
periods = d["by_period_market"]
stocks_p = d["stocks_by_period"]

DATA = json.dumps({"months": months, "sectors": sectors, "caps": caps, "dds": dds},
                  ensure_ascii=False)

period_rows = "".join(
    f"<tr><td>{p}</td><td class=n>{v.get('KOSPI',0):,}</td><td class=n>{v.get('KOSDAQ',0):,}</td>"
    f"<td class=n><b>{v.get('KOSPI',0)+v.get('KOSDAQ',0):,}</b></td><td class=n>{stocks_p[p]:,}</td></tr>"
    for p, v in periods.items())
sector_rows = "".join(
    f"<tr><td>{s['name']}</td><td class=n>{s['events']:,}</td><td class=n>{s['stocks']}/{s['universe']}</td>"
    f"<td class=n>{pct(s['hit'],0)}</td><td class=n>{s['per100']:.0f}</td><td class=n>{pct(s['kq'],0)}</td>"
    f"<td class=n>{s['y'].get('1년차 (23.11~24.11)',0)} → {s['y'].get('2년차 (24.11~25.11)',0)} → {s['y'].get('3년차 (25.11~26.11)',0)}</td>"
    f"<td class=n>{pct(s['next'],1,True)}</td><td class=n>{pct(s['f20'],1,True)}</td></tr>"
    for s in sectors)
top_rows = "".join(
    f"<tr><td class=n>{i+1}</td><td>{r['name']}<span class=code>{r['symbol'][:6]}</span></td>"
    f"<td>{r['market']}</td><td>{SEC_KO.get(r['sector'], r['sector'])}</td><td class=n><b>{r['count']}</b></td>"
    f"<td class=n>{r['mcap_median']/1e8:,.0f}억</td><td class=n>{r['first']}</td><td class=n>{r['last']}</td></tr>"
    for i, r in enumerate(top))
streak_rows = "".join(
    f"<tr><td>{k}연상</td><td class=n>{v:,}</td><td class=n>{pct(v/streak_total,1)}</td></tr>"
    for k, v in streak.items())
fwd_rows = "".join(
    f"<tr><td>{lab}</td><td class=n>{pct(fw[k]['p50'],1,True)}</td><td class=n>{pct(fw[k]['mean'],1,True)}</td>"
    f"<td class=n>{pct(fw[k]['win_rate'],0)}</td><td class=n>{pct(fw[k]['p10'],0,True)} ~ {pct(fw[k]['p90'],0,True)}</td></tr>"
    for lab, k in [("다음날 시가 (갭)", "next_open_gap"), ("다음날 종가", "next_ret"),
                   ("5거래일 후", "fwd_5d"), ("20거래일 후", "fwd_20d")])
busiest = ", ".join(f"{k} ({v}건)" for k, v in list(d["busiest_days"].items())[:5])
kq_share = d["by_market_total"]["KOSDAQ"] / m["limit_up_events"]
pref = d["by_class"].get("우선주", 0)

HTML = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>최근 3년 상한가 종목 분석</title>
<style>
.viz-root{{color-scheme:light;--surface-1:#fcfcfb;--page:#f9f9f7;--text-primary:#0b0b0b;--text-secondary:#52514e;
--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);--series-1:#2a78d6;--series-2:#eb6834;
--good:#006300;--bad:#d03b3b}}
@media (prefers-color-scheme:dark){{:root:where(:not([data-theme="light"])) .viz-root{{color-scheme:dark;--surface-1:#1a1a19;
--page:#0d0d0d;--text-primary:#f0efec;--text-secondary:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);
--series-1:#3987e5;--series-2:#d95926;--good:#0ca30c;--bad:#e66767}}}}
:root[data-theme="dark"] .viz-root{{color-scheme:dark;--surface-1:#1a1a19;--page:#0d0d0d;--text-primary:#f0efec;
--text-secondary:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--series-1:#3987e5;--series-2:#d95926;
--good:#0ca30c;--bad:#e66767}}
*{{box-sizing:border-box}}
body{{margin:0}}
.viz-root{{background:var(--page);color:var(--text-primary);font:15px/1.6 system-ui,-apple-system,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif;min-height:100vh}}
main{{max-width:1040px;margin:0 auto;padding:32px 20px 64px}}
h1{{font-size:28px;margin:0 0 4px}} h2{{font-size:20px;margin:40px 0 8px}} h3{{font-size:16px;margin:20px 0 6px}}
.sub{{color:var(--text-secondary);margin:0 0 20px}}
.card{{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:18px 20px;margin:14px 0}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}
.tile{{background:var(--surface-1);border:1px solid var(--border);border-radius:12px;padding:14px 16px}}
.tile .v{{font-size:28px;font-weight:650}} .tile .l{{color:var(--text-secondary);font-size:13px}}
table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{padding:7px 8px;border-bottom:1px solid var(--grid);text-align:left;vertical-align:top}}
th{{color:var(--text-secondary);font-weight:600;font-size:13px}}
td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
.code{{color:var(--muted);font-size:12px;margin-left:6px}}
.scroll{{overflow-x:auto}}
.legend{{display:flex;gap:16px;font-size:13px;color:var(--text-secondary);margin:4px 0 8px}}
.legend i{{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px}}
.note{{color:var(--text-secondary);font-size:13px}}
ul.k li{{margin:6px 0}}
.tip{{position:fixed;pointer-events:none;background:var(--surface-1);color:var(--text-primary);border:1px solid var(--border);
border-radius:8px;padding:8px 10px;font-size:13px;box-shadow:0 4px 16px rgba(0,0,0,.12);display:none;z-index:9;white-space:nowrap}}
svg text{{fill:var(--muted);font-size:11px;font-family:inherit}}
svg .lab{{fill:var(--text-secondary);font-size:12px}}
.callout{{border-left:3px solid var(--series-1);padding:4px 0 4px 14px;margin:12px 0}}
</style></head>
<body><div class="viz-root"><main>
<h1>최근 3년 상한가 종목 분석</h1>
<p class="sub">{m['start']} ~ {m['end']} · 코스피·코스닥 현재 상장 {m['universe']:,}개 종목 · 거래일 {m['trading_days']}일</p>

<div class="tiles">
 <div class="tile"><div class="v">{m['limit_up_events']:,}건</div><div class="l">상한가 마감 횟수 (3년)</div></div>
 <div class="tile"><div class="v">{m['limit_up_stocks']:,}개</div><div class="l">한 번 이상 상한가 간 종목 (전체의 {pct(m['limit_up_stocks']/m['universe'],0)})</div></div>
 <div class="tile"><div class="v">{d['daily_count']['50%']:.0f}개</div><div class="l">하루 평균(중앙값) 상한가 종목 수</div></div>
 <div class="tile"><div class="v">{pct(kq_share,0)}</div><div class="l">코스닥 비중</div></div>
 <div class="tile"><div class="v">{pct(fw['fwd_20d']['win_rate'],0)}</div><div class="l">20거래일 뒤 상한가 종가보다 높은 비율</div></div>
</div>

<h2>핵심 요약</h2>
<div class="card"><ul class="k">
<li><b>상한가는 점점 흔해졌습니다.</b> 1년차 996건 → 2년차 1,291건 → 3년차 2,318건. 2026년 들어 월 200건 이상이 일상이 됐습니다.</li>
<li><b>작고 싼 종목의 일입니다.</b> 시가총액 500억 미만 종목은 평소 거래일 비중보다 상한가가 {d['by_cap']['500억 미만']['lift']:.1f}배 많고, 5조 이상은 {d['by_cap']['5조 이상']['lift']:.2f}배에 그칩니다. 상한가 종목의 주가 중앙값은 {pf['price_limitup']['p50']:,.0f}원으로 시장 전체({pf['price_all']['p50']:,.0f}원)보다 낮습니다.</li>
<li><b>많이 빠진 종목에서 터집니다.</b> 상한가 직전 52주 고점 대비 하락률 중앙값은 {pct(pf['dd_from_high_limitup']['p50'],0,True)}로 시장 평균({pct(pf['dd_from_high_all']['p50'],0,True)})보다 깊습니다. 고점 대비 -70% 이하 종목의 비중이 평소의 약 3.4배입니다.</li>
<li><b>거래량이 먼저 터집니다.</b> 상한가 당일 거래량은 직전 20일 평균의 중앙값 {pf['vol_ratio_limitup']['p50']:.1f}배입니다.</li>
<li><b>섹터는 IT·반도체가 1위</b>({sectors[0]['events']:,}건)지만, 종목 수로 나눈 빈도는 섹터 간 차이가 생각보다 작습니다. 상한가는 특정 업종보다 <b>테마와 개별 재료</b>의 문제입니다.</li>
<li><b>상한가 다음 날은 대체로 갭 상승으로 시작</b>(시가 상승 확률 {pct(fw['next_open_gap']['win_rate'],0)})하지만, <b>20거래일 뒤에는 {pct(1-fw['fwd_20d']['win_rate'],0)}가 상한가 종가보다 낮습니다</b> (중앙값 {pct(fw['fwd_20d']['p50'],1,True)}). 다음 날 또 상한가를 갈 확률은 {pct(fw['next_limitup_rate'],0)}입니다.</li>
</ul></div>

<h2>1. 얼마나 많았나</h2>
<div class="card">
<h3>월별 상한가 마감 횟수</h3>
<div class="legend"><span><i style="background:var(--series-1)"></i>코스닥</span><span><i style="background:var(--series-2)"></i>코스피</span></div>
<div id="c-month"></div>
<p class="note">가장 많았던 날: {busiest}. 2024년 12월(계엄 직후 급반등), 2025년 4월, 2026년 상반기에 몰렸습니다.</p>
</div>
<div class="card scroll"><table>
<tr><th>기간</th><th class=n>코스피</th><th class=n>코스닥</th><th class=n>합계</th><th class=n>종목 수</th></tr>
{period_rows}
</table>
<p class="note">우선주 상한가 {pref:,}건 포함 (전체의 {pct(pref/m['limit_up_events'],0)}). 종가가 아닌 장중에 상한가를 터치한 경우는 {m['touch_events']:,}건이고, 그중 {pct(m['touch_close_ratio'],0)}만 상한가로 마감했습니다.</p>
</div>

<h2>2. 섹터별 분류</h2>
<div class="card">
<h3>섹터별 상한가 횟수</h3>
<div id="c-sector"></div>
<p class="note">막대 오른쪽 숫자는 상한가 횟수이고, 마우스를 올리면 종목 100개당 빈도와 비율이 나옵니다.</p>
</div>
<div class="card scroll"><table>
<tr><th>섹터</th><th class=n>상한가</th><th class=n>종목 (상한가/전체)</th><th class=n>경험 비율</th><th class=n>100종목당</th><th class=n>코스닥 비중</th><th class=n>연차별 추이</th><th class=n>다음날 평균</th><th class=n>20일 후 중앙값</th></tr>
{sector_rows}
</table>
<p class="note">섹터는 Yahoo Finance 분류(GICS 유사) 기준입니다. 국내 테마 분류(2차전지, 원전, 방산 등)와는 다릅니다.</p>
</div>
<div class="card"><ul class="k">
<li><b>IT·반도체·전자</b>: 3년차에 784건으로 2배 넘게 늘었습니다. AI·반도체·광통신·로봇 테마가 이끌었고, 90%가 코스닥입니다.</li>
<li><b>산업재·건설·기계</b>: 3년차 460건으로 가장 가파르게 늘었습니다(2년차 대비 2.1배). 전선·전력기기, 원전, 방산, 건설(정책 메가프로젝트), 운송이 포함됩니다. 금호건설이 여기에 속합니다.</li>
<li><b>헬스케어·바이오</b>: 매년 꾸준히 170~260건입니다. 기술이전, 임상 결과처럼 개별 재료로 움직입니다.</li>
<li><b>금융·부동산</b>: 종목 대비 빈도가 가장 낮습니다. 금융은 증권주 테마(지배구조, M&A)가 대부분입니다.</li>
</ul></div>

<h2>3. 상한가 종목의 공통 특징</h2>
<div class="card">
<h3>시가총액: 작을수록 상한가가 잦다</h3>
<div class="legend"><span><i style="background:var(--series-1)"></i>상한가 이벤트 비중</span><span><i style="background:var(--series-2)"></i>전체 거래일 비중 (기준선)</span></div>
<div id="c-cap"></div>
<p class="note">시가총액은 상한가 전날 종가 × 현재 발행주식수로 계산한 근사치입니다.</p>
</div>
<div class="card">
<h3>직전 주가 위치: 52주 고점 대비 얼마나 빠져 있었나</h3>
<div class="legend"><span><i style="background:var(--series-1)"></i>상한가 이벤트 비중</span><span><i style="background:var(--series-2)"></i>전체 거래일 비중 (기준선)</span></div>
<div id="c-dd"></div>
<p class="note">흥미로운 점: 고점 대비 -50% 이하 '바닥권'과 -10% 이내 '신고가 근처' 양쪽 끝에서 모두 평소보다 상한가가 많습니다. 낙폭 과대 반등형과 추세 돌파형, 두 유형이 있다는 뜻입니다.</p>
</div>
<div class="card scroll"><table>
<tr><th>특징</th><th class=n>상한가 종목 (중앙값)</th><th class=n>시장 전체 (중앙값)</th></tr>
<tr><td>52주 고점 대비 위치</td><td class=n>{pct(pf['dd_from_high_limitup']['p50'],0,True)}</td><td class=n>{pct(pf['dd_from_high_all']['p50'],0,True)}</td></tr>
<tr><td>직전 20일 수익률</td><td class=n>{pct(pf['ret_20d_before_limitup']['p50'],1,True)} (상위 25%는 {pct(pf['ret_20d_before_limitup']['p75'],0,True)} 이상)</td><td class=n>{pct(pf['ret_20d_before_all']['p50'],1,True)}</td></tr>
<tr><td>당일 거래량 / 20일 평균</td><td class=n>{pf['vol_ratio_limitup']['p50']:.1f}배</td><td class=n>약 1배</td></tr>
<tr><td>주가</td><td class=n>{pf['price_limitup']['p50']:,.0f}원</td><td class=n>{pf['price_all']['p50']:,.0f}원</td></tr>
</table>
<p class="note">직전 20일 수익률의 평균은 {pct(pf['ret_20d_before_limitup']['mean'],0,True)}로 중앙값보다 훨씬 높습니다. 이미 달리던 테마주가 한 번 더 상한가를 가는 경우가 평균을 끌어올립니다.</p>
</div>

<h2>4. 상한가 이후 주가는?</h2>
<div class="card scroll"><table>
<tr><th>상한가 종가 기준</th><th class=n>중앙값</th><th class=n>평균</th><th class=n>상승 확률</th><th class=n>하위 10% ~ 상위 10%</th></tr>
{fwd_rows}
</table>
<p class="note">평균이 중앙값보다 크게 높은 건 소수 종목의 대박(연상) 때문입니다. 전형적인 종목은 시간이 지날수록 빠집니다.</p>
</div>
<div class="card">
<div class="tiles">
 <div class="tile"><div class="v">{pct(fw['next_limitup_rate'],0)}</div><div class="l">다음 날도 상한가 마감</div></div>
 <div class="tile"><div class="v">{pct(fw['next_touch_rate'],0)}</div><div class="l">다음 날 장중 상한가 터치</div></div>
 <div class="tile"><div class="v">{pct(fw['second_after_streak_rate'],0)}</div><div class="l">2연상 종목이 3연상 갈 확률</div></div>
 <div class="tile"><div class="v">{pct(fw['next_hi_ret_median'],0,True)}</div><div class="l">다음 날 장중 고가 (중앙값)</div></div>
</div>
<h3>연속 상한가 길이</h3>
<table style="max-width:380px"><tr><th>연속</th><th class=n>횟수</th><th class=n>비중</th></tr>{streak_rows}</table>
</div>
<div class="callout"><b>시사점:</b> 상한가 다음 날 아침에는 대부분 갭 상승으로 시작하고, 장중 고가 중앙값도 +18% 수준입니다. 그런데 종가 기준으로는 승률이 반반이고, 한 달 뒤에는 3분의 2 이상이 빠져 있습니다. <b>상한가를 따라 사는 것보다, 상한가 다음 날을 매도 기회로 보는 게 통계적으로 유리합니다.</b></div>

<h2>5. 상한가 단골 종목 (보통주)</h2>
<div class="card scroll"><table>
<tr><th class=n>#</th><th>종목</th><th>시장</th><th>섹터</th><th class=n>상한가</th><th class=n>시총 중앙값</th><th class=n>처음</th><th class=n>최근</th></tr>
{top_rows}
</table>
<p class="note">종목명은 Yahoo Finance 영문명입니다. 우선주까지 포함하면 1위는 금호건설우(002995, 29회)이고, 태영건설우·한화갤러리아우 같은 우선주가 상위권에 많습니다. 금호건설 보통주는 3년간 10회(2026년 6~8월에 9회, 오늘 11/13이 10번째)입니다.</p>
</div>
<div class="card"><ul class="k">
<li>상한가를 1번만 간 종목은 {d['repeat_dist']['1회']}개, 5번 이상 간 종목은 {d['repeat_dist']['5회 이상']}개입니다. <b>한 번 간 종목이 또 갑니다.</b></li>
<li>단골 종목은 대부분 시가총액 1,000억 원 안팎의 소형주입니다. 우선주는 유통 주식이 적어 테마가 붙으면 쉽게 연속 상한가를 갑니다.</li>
</ul></div>

<h2>6. 분석 방법과 한계</h2>
<div class="card note">
<ul>
<li><b>데이터:</b> Yahoo Finance 일봉(종가·고가·거래량)으로 현재 코스피·코스닥 상장 {m['universe']:,}개 종목(우선주 포함, ETF 제외)을 봤습니다.</li>
<li><b>상한가 정의:</b> 종가가 전일 종가 대비 +29.5% 이상(호가 단위 반올림 감안). +32%를 넘는 {m['abnormal_excluded']}건(상장 첫날, 감자 후 재상장 등 기준가가 바뀐 날이나 데이터 오류)은 제외했습니다.</li>
<li><b>생존 편향:</b> 이 기간에 상장폐지된 종목은 빠져 있습니다. 그래서 실제 상한가 수보다 조금 적고(공개 기사의 월별 수치보다 약 3~5% 적음), 이후 수익률은 실제보다 좋게 나왔을 가능성이 있습니다.</li>
<li><b>시가총액:</b> 현재 발행주식수 기준 근사치라서 유상증자나 감자가 많았던 종목은 오차가 있습니다.</li>
<li>이 자료는 과거 통계이고 투자 권유가 아닙니다.</li>
</ul></div>
</main>
<div class="tip" id="tip"></div>
</div>
<script>
const D={DATA};
const css=n=>getComputedStyle(document.querySelector('.viz-root')).getPropertyValue(n).trim();
const tip=document.getElementById('tip');
function showTip(e,h){{tip.innerHTML=h;tip.style.display='block';const x=Math.min(e.clientX+14,innerWidth-tip.offsetWidth-8);tip.style.left=x+'px';tip.style.top=(e.clientY+14)+'px'}}
function hideTip(){{tip.style.display='none'}}
const NS='http://www.w3.org/2000/svg';
function el(t,a,p){{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);if(p)p.appendChild(e);return e}}
const pct=(v,d=1)=>(v*100).toFixed(d)+'%';
function bar(x,y,w,h,fill,p,r=4){{ // rounded top only
  if(h<=0)return;r=Math.min(r,w/2,h);
  return el('path',{{d:`M${{x}},${{y+h}}V${{y+r}}Q${{x}},${{y}} ${{x+r}},${{y}}H${{x+w-r}}Q${{x+w}},${{y}} ${{x+w}},${{y+r}}V${{y+h}}Z`,fill}},p)}}
function hbar(x,y,w,h,fill,p,r=4){{if(w<=0)return;r=Math.min(r,h/2,w);
  return el('path',{{d:`M${{x}},${{y}}H${{x+w-r}}Q${{x+w}},${{y}} ${{x+w}},${{y+r}}V${{y+h-r}}Q${{x+w}},${{y+h}} ${{x+w-r}},${{y+h}}H${{x}}Z`,fill}},p)}}

function monthChart(){{
  const box=document.getElementById('c-month');box.innerHTML='';
  const W=box.clientWidth,H=260,m={{l:36,r:8,t:10,b:28}};
  const s=el('svg',{{width:W,height:H}},box);
  const data=D.months,max=Math.ceil(Math.max(...data.map(d=>d.KOSDAQ+d.KOSPI))/50)*50;
  const iw=W-m.l-m.r,ih=H-m.t-m.b,bw=iw/data.length,y=v=>m.t+ih-v/max*ih;
  for(let v=0;v<=max;v+=50){{el('line',{{x1:m.l,x2:W-m.r,y1:y(v),y2:y(v),stroke:css(v?'--grid':'--axis')}},s);
    el('text',{{x:m.l-6,y:y(v)+4,'text-anchor':'end'}},s).textContent=v}}
  data.forEach((d,i)=>{{const x=m.l+i*bw+1,w=Math.max(bw-2,2);
    const hK=d.KOSDAQ/max*ih,hP=d.KOSPI/max*ih,base=m.t+ih;
    // KOSDAQ bottom (square), KOSPI top (rounded), 2px gap
    el('rect',{{x,y:base-hK,width:w,height:hK,fill:css('--series-1')}},s);
    if(hP>2)bar(x,base-hK-hP,w,hP-2,css('--series-2'),s);
    if(d.k.endsWith('-01')||i===0)el('text',{{x:x+w/2,y:H-8,'text-anchor':'middle'}},s).textContent=d.k.slice(2).replace('-','.');
    const hit=el('rect',{{x:m.l+i*bw,y:m.t,width:bw,height:ih,fill:'transparent'}},s);
    hit.addEventListener('mousemove',e=>showTip(e,`<b>${{d.k}}</b><br>코스닥 ${{d.KOSDAQ}}건<br>코스피 ${{d.KOSPI}}건<br>합계 <b>${{d.KOSDAQ+d.KOSPI}}건</b>`));
    hit.addEventListener('mouseleave',hideTip)}});
}}
function sectorChart(){{
  const box=document.getElementById('c-sector');box.innerHTML='';
  const data=D.sectors,W=box.clientWidth,row=28,m={{l:130,r:56,t:4,b:4}},H=m.t+m.b+row*data.length;
  const s=el('svg',{{width:W,height:H}},box),max=Math.max(...data.map(d=>d.events)),iw=W-m.l-m.r;
  data.forEach((d,i)=>{{const y0=m.t+i*row;
    el('text',{{x:m.l-8,y:y0+row/2+4,'text-anchor':'end',class:'lab'}},s).textContent=d.name;
    hbar(m.l,y0+6,d.events/max*iw,row-12,css('--series-1'),s);
    el('text',{{x:m.l+d.events/max*iw+6,y:y0+row/2+4,class:'lab'}},s).textContent=d.events.toLocaleString();
    const hit=el('rect',{{x:0,y:y0,width:W,height:row,fill:'transparent'}},s);
    hit.addEventListener('mousemove',e=>showTip(e,`<b>${{d.name}}</b><br>상한가 ${{d.events.toLocaleString()}}건<br>경험 종목 ${{d.stocks}}/${{d.universe}} (${{pct(d.hit,0)}})<br>100종목당 ${{d.per100.toFixed(0)}}건 · 코스닥 ${{pct(d.kq,0)}}`));
    hit.addEventListener('mouseleave',hideTip)}});
}}
function pairChart(id,data){{
  const box=document.getElementById(id);box.innerHTML='';
  const W=box.clientWidth,H=240,m={{l:36,r:8,t:10,b:40}},s=el('svg',{{width:W,height:H}},box);
  const max=Math.ceil(Math.max(...data.flatMap(d=>[d.ev,d.all]))*10)/10,iw=W-m.l-m.r,ih=H-m.t-m.b,y=v=>m.t+ih-v/max*ih;
  for(let v=0;v<=max+1e-9;v+=0.1){{el('line',{{x1:m.l,x2:W-m.r,y1:y(v),y2:y(v),stroke:css(v?'--grid':'--axis')}},s);
    el('text',{{x:m.l-6,y:y(v)+4,'text-anchor':'end'}},s).textContent=Math.round(v*100)+'%'}}
  const gw=iw/data.length,bw=Math.min(36,(gw-16)/2);
  data.forEach((d,i)=>{{const cx=m.l+gw*i+gw/2;
    bar(cx-bw-1,y(d.ev),bw,m.t+ih-y(d.ev),css('--series-1'),s);
    bar(cx+1,y(d.all),bw,m.t+ih-y(d.all),css('--series-2'),s);
    el('text',{{x:cx,y:H-22,'text-anchor':'middle',class:'lab'}},s).textContent=d.k;
    el('text',{{x:cx,y:H-6,'text-anchor':'middle'}},s).textContent=(d.ev/d.all).toFixed(2)+'배';
    const hit=el('rect',{{x:m.l+gw*i,y:m.t,width:gw,height:ih,fill:'transparent'}},s);
    hit.addEventListener('mousemove',e=>showTip(e,`<b>${{d.k}}</b><br>상한가 비중 ${{pct(d.ev)}}<br>전체 거래일 비중 ${{pct(d.all)}}<br>배율 <b>${{(d.ev/d.all).toFixed(2)}}배</b>`));
    hit.addEventListener('mouseleave',hideTip)}});
}}
function draw(){{monthChart();sectorChart();pairChart('c-cap',D.caps);pairChart('c-dd',D.dds)}}
draw();addEventListener('resize',draw);
matchMedia('(prefers-color-scheme: dark)').addEventListener('change',draw);
</script></body></html>"""

os.makedirs(os.path.join(ROOT, "report"), exist_ok=True)
with open(os.path.join(ROOT, "report", "index.html"), "w", encoding="utf-8") as f:
    f.write(HTML)
print("ok")
