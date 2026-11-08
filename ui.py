"""화면 디자인: CSS와 HTML 조각을 만드는 함수들.

사이트에서 가져온 글(리뷰, 제품명 등)은 모두 html.escape로 안전하게 바꾼 뒤 넣습니다.
"""

import html
import re

import streamlit as st

GOOD, GOOD_BG = "#1F9D6B", "#E8F7EF"
BAD, BAD_BG = "#D64545", "#FDECEC"
WARN, WARN_BG = "#B7791F", "#FFF5DC"
ROSE = "#E5537A"

CSS = """
<style>
:root, html, body { color-scheme: only light !important; }
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');
html, body, [class*="css"], .stApp, .stMarkdown, button, input, textarea, select {
  font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', sans-serif !important;
}
.block-container { padding-top: 3.2rem; max-width: 1100px; }
h1, h2, h3 { letter-spacing: -0.02em; }

.hero {
  background: linear-gradient(135deg, #FF8FA3 0%, #FFB199 55%, #FFD6A5 100%);
  border-radius: 24px; padding: 34px 32px; color: #fff; margin-bottom: 22px;
  box-shadow: 0 10px 30px rgba(229, 83, 122, 0.25);
}
.hero h1 { color: #fff; font-size: clamp(1.7rem, 5vw, 2.3rem); font-weight: 800; margin: 0 0 6px 0; padding: 0; }
.hero p { color: #fff; opacity: .95; font-size: 1.05rem; margin: 0 0 14px 0; }
.pill { display: inline-block; background: rgba(255,255,255,.25); border: 1px solid rgba(255,255,255,.5);
  border-radius: 999px; padding: 4px 12px; margin: 0 6px 6px 0; font-size: .85rem; font-weight: 600; }

.card { background: #fff; border: 1px solid #F3E1E5; border-radius: 18px; padding: 18px 20px;
  box-shadow: 0 4px 14px rgba(45, 27, 46, 0.05); margin-bottom: 14px; }
.section-title { font-size: 1.25rem; font-weight: 800; margin: 18px 0 10px 0; }
.muted { color: #8A7A84; font-size: .9rem; }

.product { font-size: 1.35rem; font-weight: 800; margin: 6px 0 14px 0; line-height: 1.4; }
.product small { display: block; font-size: .8rem; font-weight: 600; color: #E5537A; letter-spacing: .04em; }

.score { text-align: center; }
.ring { width: 118px; height: 118px; border-radius: 50%; margin: 4px auto 10px auto;
  display: flex; align-items: center; justify-content: center; }
.ring-inner { width: 92px; height: 92px; border-radius: 50%; background: #fff;
  display: flex; flex-direction: column; align-items: center; justify-content: center; }
.ring-num { font-size: 1.8rem; font-weight: 800; line-height: 1; }
.ring-unit { font-size: .75rem; color: #8A7A84; margin-top: 2px; }
.score-label { font-weight: 700; }
.score-desc { font-size: .82rem; color: #8A7A84; margin-top: 2px; }

.verdict { border-radius: 18px; padding: 18px 22px; font-size: 1.08rem; font-weight: 700;
  margin: 4px 0 16px 0; }
.comment { line-height: 1.85; font-size: 1.02rem; }
.comment b { color: #C2335C; }

.quote { border-radius: 14px; padding: 14px 16px; margin-bottom: 10px; }
.quote .head { font-weight: 800; margin-bottom: 6px; }
.quote .head span { font-weight: 600; font-size: .85rem; opacity: .8; margin-left: 4px; }
.quote .body { font-size: .93rem; color: #4A3B47; }

.chip { display: inline-block; border-radius: 999px; padding: 6px 12px; margin: 0 6px 8px 0;
  font-size: .88rem; font-weight: 600; }
.chip small { font-weight: 500; opacity: .8; margin-left: 4px; }

.bar-row { display: flex; align-items: center; margin: 8px 0; }
.bar-label { width: 86px; font-weight: 600; font-size: .9rem; flex-shrink: 0; }
.bar-track { flex: 1; display: flex; height: 14px; border-radius: 999px; overflow: hidden; background: #F5EDEF; }
.bar-num { width: 64px; text-align: right; font-size: .82rem; color: #8A7A84; flex-shrink: 0; }

.claim { display: flex; justify-content: space-between; align-items: center; gap: 10px;
  border-bottom: 1px dashed #F0DDE2; padding: 10px 2px; }
.claim:last-child { border-bottom: none; }
.badge { border-radius: 999px; padding: 4px 10px; font-size: .82rem; font-weight: 700; white-space: nowrap; }

button[data-baseweb="tab"] p { font-size: 1.05rem !important; font-weight: 700; }
button[data-baseweb="tab"] { padding: 10px 14px; }
section[data-testid="stSidebar"] h2 { font-weight: 800; }
.stButton > button { border-radius: 12px; font-weight: 700; }
.stTextInput input { border-radius: 12px; }
footer { visibility: hidden; }
.ing-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 10px; }
.ing-box { background: #FFF8F6; border: 1px solid #F3E1E5; border-radius: 14px; padding: 12px 14px; }
.ing-box-title { font-weight: 800; font-size: .9rem; margin-bottom: 8px; }
.ing-row { display: flex; align-items: center; gap: 12px; padding: 12px 2px; border-bottom: 1px dashed #F0DDE2; }
.ing-row:last-child { border-bottom: none; }
.ing-num { width: 28px; height: 28px; border-radius: 50%; background: #FFE8EE; color: #E5537A; font-weight: 800;
  font-size: .85rem; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.ing-main { flex: 1; min-width: 0; }
.ing-desc { font-size: .88rem; color: #6B5E68; margin-top: 3px; }
.ad-quote { background: #FFF5F7; border: 1px dashed #F2B8C6; border-radius: 12px; padding: 10px 12px; margin: 10px 0; font-weight: 600; }
.mini-quote { border-left: 4px solid; background: #FFFBFA; border-radius: 8px; padding: 8px 12px; margin-top: 6px; font-size: .9rem; color: #4A3B47; }
.one-pct { text-align: center; color: #B7791F; background: #FFF5DC; border-radius: 10px; padding: 6px; margin: 8px 0; font-size: .85rem; }
.mini { display: inline-block; border-radius: 6px; padding: 1px 7px; font-size: .72rem; font-weight: 700; margin-left: 4px; }
@media (max-width: 640px) {
  .block-container { padding-top: 2.6rem; }
  .hero { padding: 24px 20px; border-radius: 20px; }
  .card.score { display: flex; align-items: center; gap: 16px; text-align: left; padding: 14px 16px; }
  .ring { width: 84px; height: 84px; margin: 0; flex-shrink: 0; }
  .ring-inner { width: 64px; height: 64px; }
  .ring-num { font-size: 1.4rem; }
  .bar-label { width: 70px; }
  .ing-row { flex-wrap: wrap; }
  .ing-row .badge { margin-left: 40px; }
}
</style>
"""


def esc(text):
    return html.escape(str(text))


def md_bold(text):
    """**굵게** 표시를 HTML로 바꾼다 (먼저 escape)."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc(text))


def show(markup):
    st.markdown(markup, unsafe_allow_html=True)


def inject_css():
    show(CSS)


def hero():
    show('<div class="hero"><h1>🔍 광고 말고 진짜</h1>'
         '<p>광고에서 본 화장품, 링크만 넣으면 <b>내 피부 기준</b>으로 성분·광고·실사용 리뷰를 한눈에 분석해 드려요.</p>'
         '<span class="pill">💸 완전 무료</span><span class="pill">👤 내 피부 맞춤</span>'
         '<span class="pill">🔎 광고 vs 실제 리뷰</span></div>')


def section(title, desc=""):
    extra = f'<div class="muted">{esc(desc)}</div>' if desc else ""
    show(f'<div class="section-title">{esc(title)}</div>{extra}')


def product_title(title):
    if title:
        show(f'<div class="product"><small>ANALYSIS REPORT</small>{esc(title)}</div>')


def _tone(value):
    if value >= 70:
        return GOOD
    if value >= 45:
        return WARN
    return BAD


def score_card(label, value, unit, desc):
    color = _tone(value)
    show(f'<div class="card score"><div class="ring" style="background: conic-gradient({color} {value * 3.6}deg, #F5EDEF 0deg);">'
         f'<div class="ring-inner"><div class="ring-num" style="color:{color}">{value}</div>'
         f'<div class="ring-unit">{esc(unit)}</div></div></div>'
         f'<div><div class="score-label">{esc(label)}</div><div class="score-desc">{esc(desc)}</div></div></div>')


def verdict(text, fit, trust):
    if fit >= 70 and trust >= 60:
        color, bg = GOOD, GOOD_BG
    elif fit >= 45:
        color, bg = WARN, WARN_BG
    else:
        color, bg = BAD, BAD_BG
    show(f'<div class="verdict" style="background:{bg}; color:{color}; border:1px solid {color}33;">{esc(text)}</div>')


def comment_card(text):
    show(f'<div class="card comment">{md_bold(text)}</div>')


def quote_cards(items, good=True):
    color, bg, icon = (GOOD, GOOD_BG, "👍") if good else (BAD, BAD_BG, "👎")
    if not items:
        show(f'<div class="muted">{"눈에 띄는 칭찬 항목이 없어요." if good else "눈에 띄는 불만 항목이 없어요."}</div>')
        return
    for aspect, cnt, quote in items:
        show(f'<div class="quote" style="background:{bg}; border-left: 5px solid {color};">'
             f'<div class="head" style="color:{color}">{icon} {esc(aspect)}<span>{cnt}명</span></div>'
             f'<div class="body">“{esc(quote)}”</div></div>')


def ingredient_chips(rows):
    groups = [("⚠️ 주의", "주의가 필요한 성분", BAD, BAD_BG), ("✅ 잘 맞음", "나에게 잘 맞는 성분", GOOD, GOOD_BG),
              ("➖ 보통", "특별한 영향이 없는 성분", "#6B5E68", "#F3EEF0"),
              ("❔ 사전에 없음", "아직 사전에 없는 성분 (판단 보류)", "#8A7A84", "#FFFFFF")]
    for key, title, color, bg in groups:
        items = [r for r in rows if r["나에게"] == key]
        if not items:
            continue
        chips = "".join(
            f'<span class="chip" style="background:{bg}; color:{color};" title="{esc(r["이유"])}">'
            f'{esc(r["성분"])}<small>{esc(r["역할"]) if r["역할"] != "정보 없음" else ""}</small></span>' for r in items)
        show(f'<div class="card"><div style="font-weight:800; margin-bottom:10px; color:{color}">'
             f'{key.split()[0]} {title} ({len(items)})</div>{chips}</div>')


def aspect_bars(aspects):
    rows = [(a, v["좋음"], v["아쉬움"]) for a, v in aspects.items() if v["좋음"] + v["아쉬움"]]
    if not rows:
        show('<div class="muted">항목별로 나눌 수 있는 리뷰가 없어요.</div>')
        return
    top = max(g + b for _, g, b in rows)
    bars = ""
    for a, g, b in sorted(rows, key=lambda r: -(r[1] + r[2])):
        bars += (f'<div class="bar-row"><div class="bar-label">{esc(a)}</div><div class="bar-track">'
                 f'<div style="width:{g / top * 100}%; background:{GOOD}"></div>'
                 f'<div style="width:{b / top * 100}%; background:{BAD}"></div></div>'
                 f'<div class="bar-num">👍{g} 👎{b}</div></div>')
    show(f'<div class="card">{bars}</div>')


def claim_rows(claims):
    if not claims:
        show('<div class="card muted">광고에서 비교할 만한 효과 주장을 찾지 못했어요.</div>')
        return
    styles = {"✅": (GOOD, GOOD_BG), "❌": (BAD, BAD_BG), "🔶": (WARN, WARN_BG), "❔": ("#6B5E68", "#F3EEF0")}
    rows = ""
    for c in claims:
        color, bg = styles.get(c["판정"][0], styles["❔"])
        rows += (f'<div class="claim"><div><b>{esc(c["항목"])}</b>'
                 f'<div class="muted">광고: “{esc(c["광고 표현"])}” · 리뷰 👍/👎 {esc(c["리뷰 (좋음/아쉬움)"])}</div></div>'
                 f'<span class="badge" style="background:{bg}; color:{color}">{esc(c["판정"])}</span></div>')
    show(f'<div class="card">{rows}</div>')


def ad_check(ad):
    parts = []
    if ad["exaggeration"]:
        words = "".join(f'<span class="chip" style="background:{WARN_BG}; color:{WARN}">{esc(w)}</span>'
                        for w in ad["exaggeration"])
        parts.append(f'<div style="font-weight:800; color:{WARN}; margin-bottom:8px">😮 과장 표현</div>{words}')
    if ad["medical"]:
        words = "".join(f'<span class="chip" style="background:{BAD_BG}; color:{BAD}">{esc(w)}</span>'
                        for w in ad["medical"])
        parts.append(f'<div style="font-weight:800; color:{BAD}; margin:6px 0 8px 0">🚫 의약품으로 오해할 수 있는 표현</div>'
                     f'{words}<div class="muted">화장품은 ‘치료’, ‘재생’ 같은 의약품 효능을 광고할 수 없어요.</div>')
    if not parts:
        parts.append(f'<div style="font-weight:800; color:{GOOD}">👌 눈에 띄는 과장 표현이 없어요.</div>')
    disclosed = (f'<span class="badge" style="background:{GOOD_BG}; color:{GOOD}">✅ 광고 표기 있음</span>'
                 if ad["disclosed"] else
                 f'<span class="badge" style="background:{BAD_BG}; color:{BAD}">❌ 광고 표기 없음</span>'
                 '<div class="muted" style="margin-top:6px">인플루언서 게시물이라면 뒷광고인지 확인해 보세요. '
                 '(브랜드 공식몰은 표기가 없어도 괜찮아요)</div>')
    show(f'<div class="card">{"".join(parts)}<div style="margin-top:14px">{disclosed}</div></div>')


def topic_cards(items):
    if not items:
        show('<div class="card muted">여러 리뷰에서 반복된 이야기가 아직 없어요. 리뷰가 많을수록 잘 찾아요.</div>')
        return
    html_parts = ""
    for t in items:
        color, bg, mood = ((GOOD, GOOD_BG, "주로 좋은 반응") if t["tone"] > 0 else
                           (BAD, BAD_BG, "주로 아쉬운 반응") if t["tone"] < 0 else ("#6B5E68", "#F3EEF0", "반응 섞임/중립"))
        others = "".join(f'<div class="muted" style="margin-top:3px">· {esc(o)}</div>' for o in t["others"])
        html_parts += (f'<div class="quote" style="background:{bg}; border-left:5px solid {color};">'
                       f'<div class="head" style="color:{color}">“{esc(t["word"])}”<span>{t["count"]}명이 언급 · {mood}</span></div>'
                       f'<div class="body">“{esc(t["quote"])}”</div>{others}</div>')
    show(html_parts)


def ingredient_summary(sm):
    def box(icon, title, body, color="#2D1B2E"):
        return (f'<div class="ing-box"><div class="ing-box-title">{icon} {esc(title)}</div>'
                f'<div style="color:{color}">{body}</div></div>')
    none = '<span class="muted">없음</span>'
    chips = lambda items, color, bg: "".join(
        f'<span class="chip" style="background:{bg}; color:{color}">{esc(x)}</span>' for x in items) or none
    boxes = [
        box("🌟", "주요 성분 (가장 많이 든 5개)", chips(sm["main"], "#2D1B2E", "#F3EEF0")),
        box("🏅", "식약처 기능성 원료", chips([f"{n} · {k}" for n, k in sm["functional"]], ROSE, "#FFE8EE")),
        box("👍", "내 피부에 잘 맞는 성분", chips(sm["good"], GOOD, GOOD_BG)),
        box("⚠️", "내 피부에 주의할 성분", chips([f"{n} ({r})" for n, r in sm["caution"]], BAD, BAD_BG)),
        box("🌸", "향료 · 알레르기 유발 향 성분", chips(sm["fragrance"] + sm["allergens"], WARN, WARN_BG)),
        box("🧴", "방부제", chips(sm["preservatives"], "#6B5E68", "#F3EEF0")),
    ]
    show(f'<div class="card"><div style="font-weight:800; font-size:1.05rem; margin-bottom:12px">'
         f'전성분 {sm["total"]}개 한눈에 보기</div><div class="ing-grid">{"".join(boxes)}</div>'
         f'<div class="muted" style="margin-top:10px">💡 전성분은 <b>많이 들어간 순서</b>로 적어요. '
         f'(1% 이하로 들어간 성분은 순서가 자유로워요)</div></div>')


def ingredient_list(rows):
    styles = {"⚠️ 주의": (BAD, BAD_BG), "✅ 잘 맞음": (GOOD, GOOD_BG), "➖ 보통": ("#6B5E68", "#F3EEF0"),
              "❔ 사전에 없음": ("#8A7A84", "#FFFFFF")}
    items, divided = "", False
    amount_style = {"가장 많음": ("#2D1B2E", "#F3EEF0"), "많은 편": ("#2D1B2E", "#F7F1F3"), "1% 이상": ("#6B5E68", "#F7F1F3"),
                    "앞쪽보다 적음": ("#8A7A84", "#FFFFFF"), "최대 1%": (WARN, WARN_BG), "1% 이하": ("#8A7A84", "#FFFFFF")}
    for r in rows:
        if r.get("함량") == "1% 이하" and not divided:
            items += ('<div class="one-pct">── 여기부터는 <b>1% 이하</b>로 들어 있어요 '
                      '(바로 위 방부제가 법적으로 최대 1%까지만 넣을 수 있어서) ──</div>')
            divided = True
        color, bg = styles[r["나에게"]]
        badges = ""
        if r["주요"]:
            badges += '<span class="mini" style="background:#2D1B2E; color:#fff">주요</span>'
        if r["기능성"]:
            badges += f'<span class="mini" style="background:#FFE8EE; color:{ROSE}">{esc(r["기능성"])}</span>'
        if r["알레르기"]:
            badges += f'<span class="mini" style="background:{WARN_BG}; color:{WARN}">알레르기 유발 향</span>'
        if r["방부제"]:
            badges += '<span class="mini" style="background:#F3EEF0; color:#6B5E68">방부제</span>'
        if r["추정"]:
            badges += '<span class="mini" style="background:#fff; color:#8A7A84; border:1px solid #E5D8DC">이름으로 추정</span>'
        if r.get("함량"):
            ac, ab = amount_style.get(r["함량"], ("#6B5E68", "#F3EEF0"))
            badges += f'<span class="mini" style="background:{ab}; color:{ac}; border:1px solid #E5D8DC">양: {esc(r["함량"])}</span>'
        memo = (f'<div class="ing-desc" style="color:{ROSE}">💡 {esc(r["농도 메모"])}</div>' if r.get("농도 메모") else "")
        verdict = "판단 보류" if r["나에게"] == "❔ 사전에 없음" else r["나에게"]
        reason = f' · {esc(r["이유"])}' if r["이유"] else ""
        items += (f'<div class="ing-row"><div class="ing-num">{r["순서"]}</div><div class="ing-main">'
                  f'<div><b>{esc(r["성분"])}</b> <span class="muted">{esc(r["분류"])}</span> {badges}</div>'
                  f'<div class="ing-desc">{esc(r["설명"])}</div>{memo}</div>'
                  f'<span class="badge" style="background:{bg}; color:{color}; border:1px solid {color}33">'
                  f'{esc(verdict)}{reason}</span></div>')
    show(f'<div class="card">{items}</div>')


def trust_breakdown(score, items):
    """items: [(설명, 점수 변화, 그룹)]. 그룹별로 묶어서 보여준다."""
    color = _tone(score)
    level = ("광고 내용을 비교적 믿을 만해요" if score >= 80 else
             "광고에 근거가 부족한 부분이 있어요. 아래 항목을 확인해 보세요" if score >= 55 else
             "광고를 그대로 믿기 어려워요. 실제 리뷰를 먼저 보세요")
    rows, last_group = "", None
    for label, delta, group in items:
        if group and group != last_group:
            sub = sum(d for _, d, g in items if g == group)
            rows += (f'<div style="display:flex; justify-content:space-between; margin-top:12px; font-weight:800">'
                     f'<span>{esc(group)}</span><span style="color:{BAD if sub else GOOD}">{sub if sub else "감점 없음"}</span></div>')
            last_group = group
        if not group:
            rows += f'<div class="claim"><div>{esc(label)}</div><b>+{delta}</b></div>'
            continue
        shown = f'<b style="color:{BAD}">{delta}</b>' if delta else '<b style="color:#8A7A84">0</b>'
        rows += f'<div class="claim" style="padding-left:12px"><div class="ing-desc">{esc(label)}</div>{shown}</div>'
    groups = ["① 광고 표현", "② 근거 제시", "③ 실제 리뷰와 비교", "④ 성분 근거", "⑤ 광고를 보고 산 사람들"]
    clean = [g for g in groups if not any(gr == g for _, _, gr in items)]
    if clean:
        rows += f'<div class="muted" style="margin-top:12px">✅ 문제 없음: {esc(", ".join(clean))}</div>'
    show(f'<div class="card"><div style="display:flex; align-items:baseline; gap:10px; margin-bottom:4px; flex-wrap:wrap">'
         f'<span style="font-size:2rem; font-weight:800; color:{color}">{score}점</span>'
         f'<span style="font-weight:700; color:{color}">{esc(level)}</span></div>'
         f'<div class="muted">💡 광고 신뢰도는 <b>제품이 좋은지</b>가 아니라 <b>광고가 말한 내용을 근거로 잘 보여주는지</b>예요. '
         f'제품 만족도는 ‘리뷰 만족도’를 보세요.<br>100점에서 시작해 5가지 기준으로 깎았어요. '
         f'기준마다 최대로 깎을 수 있는 점수가 정해져 있어요.</div>'
         f'{rows}</div>')


def claim_cards(cards, n_reviews):
    styles = {"✅": (GOOD, GOOD_BG), "❌": (BAD, BAD_BG), "🔶": (WARN, WARN_BG), "❔": ("#6B5E68", "#F3EEF0")}
    for c in cards:
        color, bg = styles.get(c["verdict"][0], styles["❔"])
        total = c["good"] + c["bad"]
        bar = ""
        if total:
            bar = (f'<div class="bar-row"><div class="bar-track" style="height:16px">'
                   f'<div style="width:{c["good"] / total * 100}%; background:{GOOD}"></div>'
                   f'<div style="width:{c["bad"] / total * 100}%; background:{BAD}"></div></div>'
                   f'<div class="bar-num" style="width:110px">👍{c["good"]} 👎{c["bad"]}</div></div>'
                   f'<div class="muted">전체 리뷰 {n_reviews}개 중 이 내용을 언급한 리뷰는 {total}개예요.</div>')
        quotes = ""
        for q in c["good_quotes"]:
            quotes += f'<div class="mini-quote" style="border-color:{GOOD}">👍 “{esc(q)}”</div>'
        for q in c["bad_quotes"]:
            quotes += f'<div class="mini-quote" style="border-color:{BAD}">👎 “{esc(q)}”</div>'
        show(f'<div class="card"><div style="display:flex; justify-content:space-between; align-items:center; gap:10px">'
             f'<div style="font-weight:800; font-size:1.08rem">{esc(c["aspect"])}</div>'
             f'<span class="badge" style="background:{bg}; color:{color}">{esc(c["verdict"])}</span></div>'
             f'<div class="ad-quote">📢 광고: “{esc(c["ad_sentence"])}”</div>{bar}'
             f'<div style="margin:10px 0 6px 0; font-weight:700; color:{color}">→ {esc(c["why"])}</div>{quotes}</div>')


def number_and_tests(numbers, has_condition, tests):
    parts = ""
    if numbers:
        chips = "".join(f'<span class="chip" style="background:#FFE8EE; color:{ROSE}">{esc(n)}</span>' for n in numbers)
        cond = ("광고 글에 시험 조건(인원·기간 등)도 적혀 있어요. 함께 확인해 보세요." if has_condition else
                "⚠️ 광고 글에서는 <b>몇 명이, 얼마 동안</b> 시험했는지 찾지 못했어요. 상세페이지 이미지 아래쪽의 작은 글씨를 확인해 보세요.")
        parts += (f'<div style="font-weight:800; margin-bottom:8px">🔢 숫자로 말한 효과</div>{chips}'
                  f'<div class="muted" style="margin:4px 0 6px 0">숫자는 보통 ‘시험 전과 비교해 평균적으로 얼마나 변했는지’예요. '
                  f'모든 사람이 그만큼 좋아진다는 뜻은 아니에요.</div><div class="muted">{cond}</div>')
    for t in tests:
        parts += (f'<div class="claim" style="display:block"><div><b>🧪 {esc(t["label"])}</b> '
                  f'<span class="muted">· 광고: “{esc(t["sentence"])}”</span></div>'
                  f'<div class="ing-desc">{esc(t["meaning"])}</div></div>')
    if not parts:
        parts = '<div class="muted">숫자나 시험·인증을 내세운 광고 문구는 없었어요.</div>'
    show(f'<div class="card">{parts}</div>')


def flagged_words(exaggerations, medical, disclosed):
    items = ""
    for e in exaggerations:
        items += (f'<div class="claim" style="display:block"><span class="chip" style="background:{WARN_BG}; color:{WARN}">😮 {esc(e["word"])}</span>'
                  f'<span class="muted">“{esc(e["sentence"])}”</span><div class="ing-desc">{esc(e["reason"])}</div></div>')
    for m in medical:
        items += (f'<div class="claim" style="display:block"><span class="chip" style="background:{BAD_BG}; color:{BAD}">🚫 {esc(m["word"])}</span>'
                  f'<span class="muted">“{esc(m["sentence"])}”</span><div class="ing-desc">{esc(m["reason"])}</div></div>')
    if not items:
        items = f'<div style="font-weight:800; color:{GOOD}">👌 과장 표현이나 의약품처럼 보이게 하는 표현은 없었어요.</div>'
    disclosed_html = (f'<span class="badge" style="background:{GOOD_BG}; color:{GOOD}">✅ 광고 표기 있음</span>'
                      if disclosed else
                      f'<span class="badge" style="background:{BAD_BG}; color:{BAD}">❌ 광고 표기 없음</span>'
                      '<span class="muted"> 인플루언서 게시물이라면 뒷광고인지 확인해 보세요. (브랜드 공식몰은 표기가 없어도 괜찮아요)</span>')
    show(f'<div class="card">{items}<div style="margin-top:12px">{disclosed_html}</div></div>')


def ad_mentions(items):
    if not items:
        show('<div class="card muted">리뷰 중에 광고를 언급한 글은 없었어요.</div>')
        return
    rows = ""
    for text, tone in items:
        color, icon = (GOOD, "👍") if tone > 0 else (BAD, "👎") if tone < 0 else ("#6B5E68", "🤔")
        rows += f'<div class="mini-quote" style="border-color:{color}">{icon} “{esc(text)}”</div>'
    show(f'<div class="card">{rows}</div>')


def trend_bars(trend):
    rows = ""
    for year, sat, n in trend:
        color = _tone(sat)
        rows += (f'<div class="bar-row"><div class="bar-label">{esc(year)}년</div><div class="bar-track" style="height:16px">'
                 f'<div style="width:{sat}%; background:{color}"></div></div>'
                 f'<div class="bar-num" style="width:120px"><b style="color:{color}">{sat}%</b> · 리뷰 {n}개</div></div>')
    show(f'<div class="card">{rows}</div>')


def pending_quotes(items):
    rows = "".join(f'<div class="mini-quote" style="border-color:#C9B8C0">⏳ “{esc(q)}”</div>' for q in items)
    show(f'<div class="card">{rows}</div>')


def ingredient_groups(groups, total):
    from ingredients_info import GROUPS
    rows = ""
    for g in GROUPS:
        names = groups.get(g, [])
        if not names:
            continue
        rows += (f'<div class="bar-row" style="align-items:flex-start"><div class="bar-label" style="width:150px">{esc(g)}</div>'
                 f'<div style="flex:1"><div class="bar-track" style="height:12px">'
                 f'<div style="width:{len(names) / total * 100}%; background:{ROSE}"></div></div>'
                 f'<div class="ing-desc">{esc(", ".join(names))}</div></div>'
                 f'<div class="bar-num">{len(names)}개</div></div>')
    show(f'<div class="card">{rows}</div>')


def ingredient_alerts(summary):
    parts = ""
    if summary.get("marker"):
        name, idx, why = summary["marker"]
        parts += (f'<div class="mini-quote" style="border-color:{WARN}">📏 <b>{esc(name)}</b>({idx}번째)은 {esc(why)}예요. '
                  f'그래서 <b>{idx + 1}번째 성분부터는 모두 1% 이하</b>로 들어 있어요.</div>')
    else:
        parts += ('<div class="mini-quote" style="border-color:#C9B8C0">📏 함량의 기준이 되는 성분(최대 1%로 정해진 방부제)이 없어서, '
                  '순서로만 양을 짐작했어요.</div>')
    if summary.get("total", 99) < 10:
        parts += (f'<div class="mini-quote" style="border-color:#C9B8C0">📝 페이지에 글자로 적힌 전성분이 '
                  f'{summary["total"]}개뿐이에요. 실제 전성분이 더 길 수 있으니 제품 용기나 상세 이미지도 확인해 보세요.</div>')
    for msg in summary.get("combos", []):
        parts += f'<div class="mini-quote" style="border-color:{BAD}">⚠️ {esc(msg)}</div>'
    show(f'<div class="card">{parts}</div>')


def claim_support(items):
    if not items:
        show('<div class="card muted">광고에서 피지·보습·진정·미백·주름 같은 효과를 말하지 않았거나, 전성분이 없어요.</div>')
        return
    rows = ""
    for it in items:
        if it["ok"]:
            found = ", ".join(f"{n}({i}번째 · {amt})" for n, i, amt in it["found"])
            rows += (f'<div class="claim"><div><b>‘{esc(it["keyword"])}’</b><div class="ing-desc">근거 성분: {esc(found)}</div></div>'
                     f'<span class="badge" style="background:{GOOD_BG}; color:{GOOD}">✅ 성분 근거 있음</span></div>')
        else:
            rows += (f'<div class="claim"><div><b>‘{esc(it["keyword"])}’</b><div class="ing-desc">이 효과를 내는 대표 성분이 '
                     f'전성분에서 보이지 않아요.</div></div>'
                     f'<span class="badge" style="background:{BAD_BG}; color:{BAD}">❌ 성분 근거 없음</span></div>')
    show(f'<div class="card">{rows}</div>')
