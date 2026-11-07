"""광고 말고 진짜 - 화장품 광고 판별 봇 (Streamlit, 무료).

실행: streamlit run app.py
"""

import pandas as pd
import streamlit as st

import analyzer as az
import fetcher
import ui
from sample_data import SAMPLES

st.set_page_config(page_title="광고 말고 진짜", page_icon="🔍", layout="wide")
ui.inject_css()

# ---------------------------------------------------------------------------
# 사이드바: 내 기본 정보
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 입력
# ---------------------------------------------------------------------------
ui.hero()

with st.container(border=True):
    ui.show('<div style="font-weight:800; font-size:1.1rem; margin-bottom:4px">👤 내 피부 정보</div>'
            '<div class="muted" style="margin-bottom:6px">한 번만 고르면 모든 분석이 내 피부 기준으로 바뀌어요.</div>')
    p1, p2, p3 = st.columns(3)
    skin_type = p1.selectbox("피부 타입", az.SKIN_TYPES)
    concerns = p2.multiselect("피부 고민", az.CONCERNS, default=["건조/보습"])
    avoid = p3.multiselect("피하고 싶은 성분", az.AVOID_OPTIONS, placeholder="없음")

for key in ("ad", "ingredients", "reviews", "title"):
    st.session_state.setdefault(key, "")
st.session_state.setdefault("notes", [])
st.session_state.setdefault("auto_run", False)


def load_link():
    url = st.session_state["url"].strip()
    if not url:
        st.session_state["notes"] = ["링크를 입력해 주세요."]
        st.session_state["auto_run"] = False
        return
    try:
        result = fetcher.read_link(url)
    except fetcher.FetchError as e:
        st.session_state.update(notes=[str(e) + " 아래 칸에 직접 붙여넣어 주세요."], auto_run=False)
        return
    st.session_state.update(title=result["title"], ad=result["ad"], ingredients=result["ingredients"],
                            reviews=result["reviews"], notes=result["notes"], auto_run=True)


def load_sample(name):
    st.session_state.update(SAMPLES[name], title=name, notes=[], auto_run=False)


u1, u2 = st.columns([5, 1], vertical_alignment="bottom")
u1.text_input("🔗 제품 페이지 링크", key="url", placeholder="광고에서 본 제품 페이지 주소를 붙여넣어 주세요 (https://...)")
u2.button("분석하기 ✨", on_click=load_link, type="primary", width="stretch")

for note in st.session_state["notes"]:
    st.warning(note)

with st.expander("🧴 링크가 없거나 잘 안 될 때: 예시로 해보기 / 직접 붙여넣기", expanded=not st.session_state["auto_run"]):
    cols = st.columns(len(SAMPLES))
    for col, name in zip(cols, SAMPLES):
        col.button(name, on_click=load_sample, args=(name,), width="stretch")
    c1, c2, c3 = st.columns(3)
    c1.text_area("📢 광고 문구 (인스타 캡션, 상세페이지 문구 등)", key="ad", height=200)
    c2.text_area("🧪 전성분", key="ingredients", height=200, placeholder="정제수, 글리세린, ...")
    c3.text_area("💬 실사용 리뷰 (한 줄에 하나씩)", key="reviews", height=200)
    clicked = st.button("🔍 분석하기", width="stretch")

if not (clicked or st.session_state["auto_run"]):
    st.stop()

ad_text, ing_text, rev_text = st.session_state["ad"], st.session_state["ingredients"], st.session_state["reviews"]
if not (ad_text or ing_text or rev_text):
    st.warning("광고 문구, 성분, 리뷰 중 하나 이상 입력해 주세요.")
    st.stop()

profile = {"skin_type": skin_type, "concerns": concerns, "avoid": avoid}

# ---------------------------------------------------------------------------
# 분석
# ---------------------------------------------------------------------------
ingredients = az.analyze_ingredients(ing_text, profile)
ad = az.analyze_ad(ad_text)
reviews = az.analyze_reviews(rev_text, skin_type)
claims = az.compare_claims(ad_text, reviews)
fit, trust = az.scores(ingredients, ad, reviews, claims)

st.divider()
ui.product_title(st.session_state["title"])

m1, m2, m3 = st.columns(3)
with m1:
    ui.score_card("나와의 적합도", fit, "점", "성분 + 같은 피부 리뷰 기준")
with m2:
    ui.score_card("광고 신뢰도", trust, "점", "과장 표현 + 광고와 실제의 차이")
with m3:
    if reviews["count"]:
        sat = round(reviews["positive"] / reviews["count"] * 100)
        ui.score_card("리뷰 만족도", sat, "%", f"협찬 제외 리뷰 {reviews['count']}개 기준")
    else:
        ui.show('<div class="card score muted" style="padding:52px 20px">리뷰가 없어서<br>만족도를 계산하지 못했어요.</div>')
ui.verdict(az.verdict_text(fit, trust), fit, trust)

tab_review, tab_ing, tab_ad = st.tabs(["📝 리뷰 요약", "🧪 성분 분석", "📢 광고 vs 실제"])

with tab_review:
    if reviews["count"] or reviews["sponsored"]:
        summary = az.summarize_reviews(reviews, skin_type)
        ui.section("🗣️ 총평")
        ui.comment_card(az.overall_comment(reviews, claims, skin_type, fit))
        g, b = st.columns(2)
        with g:
            ui.section("좋은 점 TOP 3")
            ui.quote_cards(summary["good"], good=True)
        with b:
            ui.section("아쉬운 점 TOP 3")
            ui.quote_cards(summary["bad"], good=False)
        ui.section("💬 항목별 반응", "초록은 좋다는 의견, 빨강은 아쉽다는 의견이에요.")
        ui.aspect_bars(reviews["aspects"])
        with st.expander("숫자로 자세히 보기"):
            st.markdown(summary["text"])
            if reviews["by_skin"]:
                st.dataframe(pd.DataFrame(reviews["by_skin"]).T, width="stretch")
    else:
        ui.show('<div class="card muted">리뷰가 없어요. 리뷰를 붙여넣으면 요약해 드려요.</div>')

with tab_ing:
    ui.section("🧪 내 피부 기준 성분 분석", f"{skin_type} 피부 · 고민: {', '.join(concerns) or '없음'}"
               f" · 피하는 성분: {', '.join(avoid) or '없음'}")
    if ingredients:
        ui.ingredient_chips(ingredients)
        st.caption("성분 칩에 마우스를 올리면 판단 이유가 보여요.")
        with st.expander("표로 보기"):
            st.dataframe(pd.DataFrame(ingredients), hide_index=True, width="stretch")
    else:
        ui.show('<div class="card muted">분석할 수 있는 성분이 없어요. 전성분을 붙여넣어 주세요.</div>')

with tab_ad:
    ui.section("🔎 광고에서 말한 효과, 진짜일까?", "광고의 주장과 실제 리뷰 반응을 비교했어요.")
    ui.claim_rows(claims)
    ui.section("📢 광고 문구 체크")
    ui.ad_check(ad)

st.caption("※ 이 분석은 참고용이에요. 피부 반응은 개인차가 있으니 패치 테스트를 권장해요.")
