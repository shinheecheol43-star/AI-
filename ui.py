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
@media (max-width: 640px) {
  .block-container { padding-top: 2.6rem; }
  .hero { padding: 24px 20px; border-radius: 20px; }
  .card.score { display: flex; align-items: center; gap: 16px; text-align: left; padding: 14px 16px; }
  .ring { width: 84px; height: 84px; margin: 0; flex-shrink: 0; }
  .ring-inner { width: 64px; height: 64px; }
  .ring-num { font-size: 1.4rem; }
  .bar-label { width: 70px; }
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
              ("➖ 보통", "특별한 영향이 없는 성분", "#6B5E68", "#F3EEF0")]
    for key, title, color, bg in groups:
        items = [r for r in rows if r["나에게"] == key]
        if not items:
            continue
        chips = "".join(
            f'<span class="chip" style="background:{bg}; color:{color};" title="{esc(r["이유"])}">'
            f'{esc(r["성분"])}<small>{esc(r["역할"])}</small></span>' for r in items)
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
