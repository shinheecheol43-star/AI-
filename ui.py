"""화면 디자인: CSS와 HTML 조각을 만드는 함수들.

사이트에서 가져온 글(리뷰, 제품명 등)은 모두 html.escape로 안전하게 바꾼 뒤 넣습니다.
"""

import html
import re

import streamlit as st

# 매거진 스타일: 종이색 배경 + 검정 글씨 + 포인트 색 하나(테라코타). 좋음/나쁨/주의는 채도를 낮춘 색
INK, PAPER, LINE, GRAY = "#2B2522", "#FCF5EF", "#EADFD4", "#7A6F66"
GOOD, GOOD_BG = "#2E6B4F", "#EEF3EE"
BAD, BAD_BG = "#A8322D", "#F7ECE9"
WARN, WARN_BG = "#8C6A1C", "#F5F0E2"
ROSE = "#F47A1F"   # 포인트 주황

CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@300;400;600&family=Cormorant+Garamond:ital,wght@0,400;0,500;1,400;1,500&display=swap');
:root, html, body { color-scheme: only light !important; }
html, body, [class*="css"], .stApp, .stMarkdown, button, input, textarea, select {
  font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', sans-serif !important;
}
.stApp { background: #FCF5EF; color: #2B2522; }
.block-container { padding-top: 2.2rem; max-width: 1060px; counter-reset: sec; }
.serif, .hero h1, .section-title, .product, .big-num, .ing-num, .band h2, .foot h2 { font-family: 'Noto Serif KR', serif !important; }
.en { font-family: 'Cormorant Garamond', serif !important; font-style: italic; }

/* 첫 화면 */
.hero { display: grid; grid-template-columns: 1.15fr .85fr; gap: 24px; align-items: center; margin: 4px 0 30px 0; }
.hero .kicker { font-size: .7rem; letter-spacing: .24em; font-weight: 700; color: #F47A1F; }
.hero h1 { font-size: clamp(2.4rem, 7vw, 4rem); font-weight: 300; letter-spacing: -0.04em; line-height: 1.12; margin: 14px 0 14px 0; padding: 0; color: #2B2522; }
.hero h1 em { font-style: italic; color: #F47A1F; font-weight: 400; }
.hero .lead { color: #F47A1F; font-size: 1.15rem; font-weight: 500; margin: 0 0 12px 0; }
.hero p { color: #5B524B; font-size: .98rem; line-height: 1.75; margin: 0; max-width: 520px; }
.hero svg { width: 100%; height: auto; }

/* 주황 띠 (전체 폭) */
.band, .foot { margin: 34px calc(50% - 50vw); padding: 56px calc(50vw - 50%); background: #F47A1F; color: #fff; }
.band-in, .foot-in { max-width: 1060px; margin: 0 auto; padding: 0 1rem; }
.band-title { font-family: 'Noto Serif KR', serif; font-weight: 300; font-size: clamp(1.7rem, 4vw, 2.4rem); text-align: center; margin: 0 0 30px 0; color: #fff; letter-spacing: -0.02em; }
.band-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; text-align: center; }
.arch-icon { width: 92px; height: 132px; margin: 0 auto 12px auto; border: 1.5px solid #fff; border-radius: 46px 46px 46px 46px;
  display: flex; align-items: center; justify-content: center; }
.band-grid b { display: block; font-size: 1rem; margin-bottom: 4px; }
.band-grid span { font-size: .86rem; opacity: .92; line-height: 1.6; }
.foot { margin-bottom: -6rem; padding-bottom: 80px; margin-top: 12px; }
.foot-in { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; align-items: center; }
.foot-title { font-family: 'Noto Serif KR', serif; font-weight: 300; font-size: clamp(2rem, 5vw, 2.8rem); color: #fff; margin: 0; }
.foot-card { border: 1.5px solid rgba(255,255,255,.9); border-radius: 22px; padding: 20px 22px; font-size: .88rem; line-height: 1.9; }
.foot-card small { display: block; opacity: .85; letter-spacing: .06em; }

/* 기본 요소 */
.card { background: #FFFFFF; border: 1px solid #EADFD4; border-radius: 22px; padding: 20px 22px; margin-bottom: 14px; }
.section-title { font-size: 1.85rem; font-weight: 300; margin: 40px 0 6px 0; letter-spacing: -0.03em; color: #2B2522; line-height: 1.3; }
.section-title::before { counter-increment: sec; content: counter(sec, decimal-leading-zero) " —"; display: block;
  font-family: 'Pretendard', sans-serif; font-size: .7rem; letter-spacing: .2em; color: #F47A1F; font-weight: 700; margin-bottom: 8px; }
.muted { color: #7A6F66; font-size: .88rem; line-height: 1.65; }
.product { font-size: clamp(1.6rem, 4vw, 2.3rem); font-weight: 300; margin: 6px 0 20px 0; line-height: 1.3; letter-spacing: -0.03em; }
.product small { display: block; font-family: 'Pretendard', sans-serif; font-size: .7rem; font-weight: 700; color: #F47A1F; letter-spacing: .24em; margin-bottom: 8px; }

/* 점수 */
.score { border-radius: 28px 28px 22px 22px; padding: 20px 22px 16px 22px; }
.score-label { font-size: .78rem; font-weight: 700; color: #7A6F66; }
.big-num { font-size: 3.4rem; font-weight: 300; line-height: 1; margin: 10px 0 6px 0; letter-spacing: -0.04em; }
.big-num small { font-size: 1.05rem; font-weight: 400; margin-left: 3px; }
.thin-bar { height: 4px; background: #F3E7DC; margin: 10px 0 10px 0; border-radius: 99px; overflow: hidden; }
.thin-bar div { height: 4px; border-radius: 99px; }
.score-desc { font-size: .8rem; color: #7A6F66; line-height: 1.55; }

.verdict { padding: 18px 24px; font-size: 1.12rem; font-weight: 500; margin: 6px 0 12px 0; border-radius: 22px;
  background: #FFEBDA; border: none !important; color: #2B2522 !important; line-height: 1.6; }
.verdict::before { content: "결론"; display: block; font-size: .7rem; letter-spacing: .2em; font-weight: 700; color: #F47A1F; margin-bottom: 4px; }
.comment { line-height: 1.95; font-size: 1.03rem; }
.comment b { color: #2B2522; background: linear-gradient(transparent 60%, #FFD9B8 60%); font-weight: 600; }

/* 후기 카드 (사용자 후기 스타일) */
.quote { padding: 4px 0 14px 0; margin-bottom: 10px; border: none !important; background: transparent !important; }
.quote .head { font-weight: 700; margin-top: 6px; font-size: .86rem; order: 2; }
.quote .head span { font-weight: 500; font-size: .78rem; color: #7A6F66; margin-left: 6px; }
.quote .body { font-size: .95rem; color: #2B2522; line-height: 1.7; }
.quote { display: flex; flex-direction: column-reverse; }

.chip { display: inline-block; border-radius: 999px; padding: 4px 12px; margin: 0 6px 8px 0; font-size: .84rem; font-weight: 600;
  border: 1px solid currentColor; background: transparent !important; }
.chip small { font-weight: 500; opacity: .8; margin-left: 4px; }

.bar-row { display: flex; align-items: center; margin: 10px 0; gap: 10px; }
.bar-label { width: 90px; font-weight: 600; font-size: .88rem; flex-shrink: 0; }
.bar-track { flex: 1; display: flex; height: 8px; border-radius: 99px; overflow: hidden; background: #F3E7DC; }
.bar-num { width: 70px; text-align: right; font-size: .8rem; color: #7A6F66; flex-shrink: 0; }

.claim { display: flex; justify-content: space-between; align-items: center; gap: 12px; border-bottom: 1px solid #F1E6DB; padding: 12px 0; }
.claim:last-child { border-bottom: none; }
.badge { border-radius: 999px; padding: 3px 10px; font-size: .76rem; font-weight: 700; white-space: nowrap; border: 1px solid currentColor; background: transparent !important; }

/* 탭·버튼·입력 */
button[data-baseweb="tab"] p { font-size: 1rem !important; font-weight: 600; }
button[data-baseweb="tab"] { padding: 10px 18px 10px 0; }
div[data-baseweb="tab-highlight"] { background-color: #F47A1F !important; height: 2px !important; }
.stButton > button { border-radius: 999px; font-weight: 600; border: 1px solid #2B2522; background: transparent; color: #2B2522; }
.stButton > button[kind="primary"] { background: #F47A1F; border-color: #F47A1F; color: #fff; }
.stButton > button[kind="primary"]:hover { background: #2B2522; border-color: #2B2522; color: #fff; }
.stTextInput input, .stTextArea textarea { border-radius: 14px !important; }
div[data-baseweb="select"] > div { border-radius: 14px !important; }
div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 24px !important; background: #FFFFFF; }
div[data-testid="stExpander"] details { border-radius: 18px !important; background: #FFFFFF; }
footer { visibility: hidden; }
div[data-testid="stAlert"] { border-radius: 18px !important; background: #FFF6EE !important; border: 1px solid #F6DCC4 !important; }
div[data-testid="stAlert"] p, div[data-testid="stAlert"] div { color: #3B332D !important; font-size: .92rem; }
div[data-testid="stAlert"] svg { display: none; }
div[data-testid="stAlert"] > div, div[data-testid="stAlert"] [role="alert"], div[data-testid="stAlert"] [data-baseweb="notification"],
div[data-testid="stAlertContainer"], div[data-testid^="stAlertContent"] { background: #FFF6EE !important; border-radius: 18px !important; }

/* 성분 */
.ing-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }
.ing-box { background: #FCF5EF; border-radius: 18px; padding: 14px 16px; }
.ing-box-title { font-weight: 700; font-size: .8rem; color: #7A6F66; margin-bottom: 10px; }
.ing-row { display: flex; align-items: center; gap: 14px; padding: 13px 0; border-bottom: 1px solid #F1E6DB; }
.ing-row:last-child { border-bottom: none; }
.ing-num { width: 30px; font-size: 1.2rem; font-weight: 300; color: #F47A1F; flex-shrink: 0; text-align: right; }
.ing-main { flex: 1; min-width: 0; }
.ing-desc { font-size: .86rem; color: #5B524B; margin-top: 3px; line-height: 1.55; }
.ad-quote { background: #FFF3E8; border-radius: 16px; padding: 10px 14px; margin: 10px 0; font-weight: 500; }
.mini-quote { border-left: 2px solid; padding: 6px 0 6px 12px; margin-top: 8px; font-size: .9rem; color: #2B2522; line-height: 1.65; }
.one-pct { text-align: center; color: #B4621A; background: #FFF3E8; border-radius: 99px; padding: 6px; margin: 10px 0; font-size: .82rem; }
.mini { display: inline-block; border-radius: 99px; padding: 0 8px; font-size: .7rem; font-weight: 700; margin-left: 4px; }
a { color: #F47A1F !important; }

@media (max-width: 720px) {
  .hero { grid-template-columns: 1fr; }
  .hero svg { max-width: 320px; margin: 0 auto; display: block; }
  .band-grid { grid-template-columns: 1fr; gap: 26px; }
  .foot-in { grid-template-columns: 1fr; }
  .big-num { font-size: 2.8rem; }
  .bar-label { width: 72px; }
  .ing-row { flex-wrap: wrap; }
  .ing-row .badge { margin-left: 44px; }
}
</style>
"""


def esc(text):
    return html.escape(str(text))


def md_bold(text):
    """**굵게** 표시를 HTML로 바꾼다 (먼저 escape)."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc(text))


EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]+\\s?")


def plain(text):
    """이모지를 뺀 글자 (매거진 스타일에서는 화면에 이모지를 쓰지 않음)"""
    return EMOJI.sub("", str(text))


def show(markup):
    st.markdown(plain(markup), unsafe_allow_html=True)


def inject_css():
    show(CSS)


HERO_ART = """
<svg viewBox="0 0 360 310" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="화장품 병과 돋보기 그림">
  <defs>
    <linearGradient id="peach" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFD8B4"/><stop offset="1" stop-color="#FFAE6E"/></linearGradient>
  </defs>
  <path d="M30,105 A80,80 0 0 1 190,105 V290 H30 Z" fill="url(#peach)"/>
  <rect x="82" y="168" width="56" height="92" rx="12" fill="#FFF6EE" stroke="#2B2522" stroke-width="2"/>
  <rect x="96" y="146" width="28" height="24" rx="4" fill="#FFF6EE" stroke="#2B2522" stroke-width="2"/>
  <ellipse cx="110" cy="128" rx="13" ry="18" fill="#F47A1F" stroke="#2B2522" stroke-width="2"/>
  <line x1="92" y1="200" x2="128" y2="200" stroke="#2B2522" stroke-width="1.5"/>
  <line x1="92" y1="210" x2="118" y2="210" stroke="#2B2522" stroke-width="1.5"/>
  <path d="M182,170 A62,62 0 0 1 306,170 V296 H182 Z" fill="#FFF3E8" stroke="#F47A1F" stroke-width="1.6"/>
  <rect x="204" y="236" width="72" height="44" rx="9" fill="#FFFFFF" stroke="#2B2522" stroke-width="2"/>
  <rect x="198" y="222" width="84" height="16" rx="7" fill="#F47A1F" stroke="#2B2522" stroke-width="2"/>
  <circle cx="262" cy="200" r="25" fill="#FFFFFF" fill-opacity=".7" stroke="#2B2522" stroke-width="3"/>
  <line x1="280" y1="218" x2="302" y2="240" stroke="#2B2522" stroke-width="6" stroke-linecap="round"/>
  <path d="M252,196 l7,7 l12,-14" fill="none" stroke="#F47A1F" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
  <g stroke="#F47A1F" stroke-width="2" stroke-linecap="round">
    <line x1="214" y1="70" x2="214" y2="92"/><line x1="203" y1="81" x2="225" y2="81"/>
    <line x1="320" y1="120" x2="320" y2="134"/><line x1="313" y1="127" x2="327" y2="127"/>
  </g>
</svg>
"""

ICONS = {
    "성분": '<svg width="40" height="40" viewBox="0 0 40 40" fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M15 5h10M17 5v10L8 32a3 3 0 0 0 3 4h18a3 3 0 0 0 3-4L23 15V5"/><path d="M12 26h16"/></svg>',
    "광고": '<svg width="40" height="40" viewBox="0 0 40 40" fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M6 17v6h5l12 7V10l-12 7H6z"/><path d="M28 15c2 1.5 2 8.5 0 10M32 12c4 3 4 13 0 16"/></svg>',
    "리뷰": '<svg width="40" height="40" viewBox="0 0 40 40" fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M6 8h28v18H17l-7 6v-6H6z"/><path d="M12 15h16M12 20h10"/></svg>',
}


def hero():
    show('<div class="hero"><div><div class="kicker">CONSUMER COSMETIC REPORT</div>'
         '<h1>광고 말고,<br><em>진짜.</em></h1>'
         '<div class="lead">광고에서 본 그 화장품, 정말 나한테 맞을까?</div>'
         '<p>제품 링크 하나로 성분과 광고 문구, 실제 사용자 리뷰를 모아 내 피부 기준의 리포트로 정리해요.</p></div>'
         f'<div>{HERO_ART}</div></div>')


def intro_band():
    items = [("성분", "성분", "전성분을 하나씩 풀어서<br>내 피부와 맞는지 확인"),
             ("광고", "광고", "광고 문구의 과장과<br>근거를 점수로 확인"),
             ("리뷰", "실제 리뷰", "쇼핑몰·블로그·카페 후기로<br>광고가 진짜인지 확인")]
    cells = "".join(f'<div><div class="arch-icon">{ICONS[k]}</div><b>{t}</b><span>{d}</span></div>' for k, t, d in items)
    show(f'<div class="band"><div class="band-in"><div class="band-title">이 리포트가 확인하는 <span class="en">three things</span></div>'
         f'<div class="band-grid">{cells}</div></div></div>')


def footer():
    show('<div class="foot"><div class="foot-in"><div class="foot-title">광고 말고, <span class="en">real.</span></div>'
         '<div class="foot-card"><small>PROJECT</small>2026-2 AI 교과 연계 프로젝트 공모전 출품작<br>'
         '<small style="margin-top:8px">DATA</small>쇼핑몰 공개 리뷰 · 블로그·카페 검색 · 상세 이미지 글자 인식<br>'
         '<small style="margin-top:8px">NOTE</small>분석은 참고용이에요. 피부 반응은 개인차가 있으니 패치 테스트를 권장해요.</div></div></div>')


def section(title, desc=""):
    extra = f'<div class="muted">{esc(desc)}</div>' if desc else ""
    show(f'<div class="section-title">{esc(title)}</div>{extra}')


def product_title(title):
    if title:
        show(f'<div class="product"><small>THE REPORT</small>{esc(title)}</div>')


def _tone(value):
    if value >= 70:
        return GOOD
    if value >= 45:
        return WARN
    return BAD


def score_card(label, value, unit, desc):
    color = _tone(value)
    show(f'<div class="card score"><div class="score-label">{esc(label)}</div>'
         f'<div class="big-num" style="color:{color}">{value}<small>{esc(unit)}</small></div>'
         f'<div class="thin-bar"><div style="width:{value}%; background:{color}"></div></div>'
         f'<div class="score-desc">{esc(desc)}</div></div>')


def verdict(text, fit, trust):
    if fit >= 70 and trust >= 60:
        color, bg = GOOD, GOOD_BG
    elif fit >= 45:
        color, bg = WARN, WARN_BG
    else:
        color, bg = BAD, BAD_BG
    show(f'<div class="verdict">{esc(text)}</div>')


def comment_card(text):
    show(f'<div class="card comment">{md_bold(text)}</div>')


def quote_cards(items, good=True):
    color, bg, icon = (GOOD, GOOD_BG, "👍") if good else (BAD, BAD_BG, "👎")
    if not items:
        show(f'<div class="muted">{"눈에 띄는 칭찬 항목이 없어요." if good else "눈에 띄는 불만 항목이 없어요."}</div>')
        return
    for aspect, cnt, quote in items:
        show(f'<div class="quote card">'
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
                 f'<div class="bar-num" style="width:110px">좋음 {g} · 아쉬움 {b}</div></div>')
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
                 f'<div class="muted">광고: “{esc(c["광고 표현"])}” · 리뷰 좋음/아쉬움 {esc(c["리뷰 (좋음/아쉬움)"])}</div></div>'
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
    amount_style = {"가장 많음": ("#2D1B2E", "#F3EEF0"), "많은 편": ("#2D1B2E", "#F7F1F3"), "중간": ("#6B5E68", "#F7F1F3"),
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
                   f'<div class="bar-num" style="width:130px">좋음 {c["good"]} · 아쉬움 {c["bad"]}</div></div>'
                   f'<div class="muted">전체 리뷰 {n_reviews}개 중 이 내용을 언급한 리뷰는 {total}개예요.</div>')
        quotes = ""
        for q in c["good_quotes"]:
            quotes += f'<div class="mini-quote" style="border-color:{GOOD}"><b style="color:{GOOD}">같은 경험</b> “{esc(q)}”</div>'
        for q in c["bad_quotes"]:
            quotes += f'<div class="mini-quote" style="border-color:{BAD}"><b style="color:{BAD}">다른 경험</b> “{esc(q)}”</div>'
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


def match_breakdown(score, items, skin_type, concerns, avoid):
    color = _tone(score)
    level = ("내 피부에 잘 맞는 성분 구성이에요" if score >= 75 else
             "보통이에요. 주의 성분이 나에게 중요한지 확인해 보세요" if score >= 50 else
             "내 피부와 잘 맞지 않는 성분이 많아요")
    rows = ""
    for label, d in items:
        if label == "기본 점수":
            rows += f'<div class="claim"><div>{esc(label)}</div><b>{d}</b></div>'
            continue
        c = GOOD if d > 0 else BAD if d < 0 else "#8A7A84"
        rows += f'<div class="claim"><div class="ing-desc">{esc(label)}</div><b style="color:{c}">{"+" if d > 0 else ""}{d}</b></div>'
    who = f"{skin_type} 피부 · 고민: {', '.join(concerns) or '없음'} · 피하는 성분: {', '.join(avoid) or '없음'}"
    show(f'<div class="card"><div style="display:flex; align-items:baseline; gap:10px; flex-wrap:wrap">'
         f'<span style="font-size:2rem; font-weight:800; color:{color}">{score}점</span>'
         f'<span style="font-weight:700; color:{color}">{esc(level)}</span></div>'
         f'<div class="muted" style="margin-bottom:6px">{esc(who)} 기준이에요. 위쪽 ‘내 피부 정보’를 바꾸면 점수도 바뀌어요.</div>{rows}</div>')


def title_check(items, title):
    if not items:
        return
    styles = {"high": (GOOD, GOOD_BG, "✅ 많이 들어 있음"), "mid": ("#6B5E68", "#F3EEF0", "➖ 중간"),
              "low": (WARN, WARN_BG, "⚠️ 1% 이하"), "tiny": (BAD, BAD_BG, "⚠️ 아주 적은 양"),
              "missing": (BAD, BAD_BG, "❌ 전성분에 없음")}
    rows = ""
    for it in items:
        color, bg, badge = styles[it["level"]]
        found = f' <span class="muted">→ {esc(it["found"])}</span>' if it["found"] else ""
        rows += (f'<div class="claim"><div><b>‘{esc(it["key"])}’</b>{found}<div class="ing-desc">{esc(it["text"])}</div></div>'
                 f'<span class="badge" style="background:{bg}; color:{color}">{badge}</span></div>')
    tip = ""
    if any(it["level"] in ("tiny", "low") for it in items):
        tip = ('<div class="muted" style="margin-top:8px">💡 이름에 내세운 성분이 아주 조금만 들어 있어도 이름에 쓸 수 있어요. '
               '이름보다 앞쪽에 있는 성분이 실제 사용감을 좌우해요.</div>')
    show(f'<div class="card">{rows}{tip}</div>')


def site_summary(lines):
    rows = "".join(f'<div class="mini-quote" style="border-color:#C9B8C0">🏪 {esc(l)}</div>' for l in lines)
    show(f'<div class="card"><div class="muted">쇼핑몰이 직접 만든 리뷰 요약이에요. 판매자가 만든 글이라 분석 점수에는 넣지 않았어요.</div>{rows}</div>')


def source_compare(rows):
    """출처별 만족도 비교: [(이름, 만족 %, 평가 리뷰 수)]"""
    html = ""
    for label, sat, n in rows:
        if sat is None or n < 3:
            html += (f'<div class="bar-row"><div class="bar-label" style="width:190px">{esc(label)}</div>'
                     f'<div class="muted" style="flex:1">{"평가가 담긴 글이 " + str(n) + "개라 비교 어려움" if n else "글 없음"}</div></div>')
            continue
        color = _tone(sat)
        html += (f'<div class="bar-row"><div class="bar-label" style="width:190px">{esc(label)}</div>'
                 f'<div class="bar-track" style="height:14px"><div style="width:{sat}%; background:{color}"></div></div>'
                 f'<div class="bar-num" style="width:110px"><b style="color:{color}">{sat}%</b> · {n}개</div></div>')
    sponsored = rows[-1]
    plain = [r for r in rows[:-1] if r[1] is not None and r[2] >= 3]
    tip = ""
    if sponsored[1] is not None and sponsored[2] >= 3 and plain:
        avg = sum(r[1] for r in plain) / len(plain)
        if sponsored[1] - avg >= 10:
            tip = (f'<div class="mini-quote" style="border-color:{WARN}">💡 협찬 표시가 있는 글의 만족도({sponsored[1]}%)가 '
                   f'다른 후기 평균({avg:.0f}%)보다 높아요. 협찬 후기는 걸러서 보는 게 좋아요.</div>')
    show(f'<div class="card"><div style="font-weight:800; margin-bottom:8px">출처별 만족도 비교</div>{html}{tip}'
         f'<div class="muted" style="margin-top:8px">‘협찬 표시’는 요약 글에 협찬·체험단·제공받음 등이 보이는 경우예요. '
         f'본문 끝에만 적혀 있으면 놓칠 수 있어요.</div></div>')


def web_quotes(items, skin_type):
    import analyzer as az
    good, bad, seen = [], [], set()
    for it in items:
        if it["text"] in seen:
            continue
        seen.add(it["text"])
        r = az.analyze_reviews(it["text"], skin_type)
        if r["positive"] and len(good) < 3:
            good.append(it)
        elif (r["negative"] or r["mixed"]) and len(bad) < 3:
            bad.append(it)
    def card(it, color, icon):
        meta = f'{it["source"]}{" · " + it["date"] if it["date"] else ""}'
        link = (f' · <a href="{esc(it["link"])}" target="_blank" rel="noopener">원문 보기</a>'
                if str(it.get("link", "")).startswith(("http://", "https://")) else "")
        return (f'<div class="mini-quote" style="border-color:{color}">{icon} “{esc(it["text"][:120])}”'
                f'<div class="muted" style="margin-top:4px">{esc(meta)}{link}</div></div>')
    html = "".join(card(i, GOOD, "👍") for i in good) + "".join(card(i, BAD, "👎") for i in bad)
    if html:
        show(f'<div class="card"><div style="font-weight:800; margin-bottom:6px">인터넷 후기 예시 (협찬 표시 없는 글)</div>{html}</div>')
