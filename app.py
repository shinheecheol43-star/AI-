"""광고 말고 진짜 - 화장품 광고 판별 봇 (Streamlit, 무료).

실행: streamlit run app.py
"""

import pandas as pd
import streamlit as st

import analyzer as az
import fetcher
from sample_data import SAMPLES

st.set_page_config(page_title="광고 말고 진짜", page_icon="🔍", layout="wide")

# ---------------------------------------------------------------------------
# 사이드바: 내 기본 정보
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("👤 내 피부 정보")
    skin_type = st.selectbox("피부 타입", az.SKIN_TYPES)
    concerns = st.multiselect("피부 고민", az.CONCERNS, default=["건조/보습"])
    avoid = st.multiselect("피하고 싶은 성분", az.AVOID_OPTIONS)

profile = {"skin_type": skin_type, "concerns": concerns, "avoid": avoid}

# ---------------------------------------------------------------------------
# 입력
# ---------------------------------------------------------------------------
st.title("🔍 광고 말고 진짜")
st.caption("광고에서 본 제품의 **링크만 넣으면** 내 피부 기준으로 성분, 광고 문구, 실사용 리뷰를 한눈에 분석해 드려요.")

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
u1.text_input("🔗 제품 페이지 링크", key="url", placeholder="https://...")
u2.button("링크로 분석", on_click=load_link, type="primary", width="stretch")

for note in st.session_state["notes"]:
    st.warning(note)

with st.expander("링크가 없거나 잘 안 될 때: 예시로 해보기 / 직접 붙여넣기", expanded=not st.session_state["auto_run"]):
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

# ---------------------------------------------------------------------------
# 분석
# ---------------------------------------------------------------------------
ingredients = az.analyze_ingredients(ing_text, profile)
ad = az.analyze_ad(ad_text)
reviews = az.analyze_reviews(rev_text, skin_type)
claims = az.compare_claims(ad_text, reviews)
fit, trust = az.scores(ingredients, ad, reviews, claims)

st.divider()
st.header(f"📊 분석 결과{' - ' + st.session_state['title'] if st.session_state['title'] else ''}")

m1, m2, m3 = st.columns(3)
m1.metric("나와의 적합도", f"{fit}점")
m1.progress(fit / 100)
m2.metric("광고 신뢰도", f"{trust}점")
m2.progress(trust / 100)
if reviews["count"]:
    m3.metric("리뷰 만족도", f"{round(reviews['positive'] / reviews['count'] * 100)}%",
              help=f"협찬 제외 리뷰 {reviews['count']}개 중 긍정 {reviews['positive']}개, "
                   f"부정 {reviews['negative']}개, 혼합 {reviews['mixed']}개")
st.info(f"**결론:** {az.verdict_text(fit, trust)}")

# ---------------------------------------------------------------------------
# 리뷰 한눈에 요약
# ---------------------------------------------------------------------------
if reviews["count"] or reviews["sponsored"]:
    st.subheader("📝 리뷰 한눈에 요약")
    summary = az.summarize_reviews(reviews, skin_type)
    with st.container(border=True):
        st.markdown(summary["text"])
    g, b = st.columns(2)
    with g:
        st.markdown("**👍 좋은 점 TOP 3**")
        for aspect, cnt, quote in summary["good"]:
            st.success(f"**{aspect}** ({cnt}명)\n\n“{quote}”")
        if not summary["good"]:
            st.caption("눈에 띄는 칭찬 항목이 없어요.")
    with b:
        st.markdown("**👎 아쉬운 점 TOP 3**")
        for aspect, cnt, quote in summary["bad"]:
            st.error(f"**{aspect}** ({cnt}명)\n\n“{quote}”")
        if not summary["bad"]:
            st.caption("눈에 띄는 불만 항목이 없어요.")
    if reviews["by_skin"]:
        with st.expander("피부 타입별 반응 보기"):
            st.dataframe(pd.DataFrame(reviews["by_skin"]).T, width="stretch")

left, right = st.columns(2)

with left:
    st.subheader("🧪 성분 분석")
    if ingredients:
        st.dataframe(pd.DataFrame(ingredients), hide_index=True, width="stretch")
    else:
        st.write("분석할 수 있는 성분이 없어요.")

    st.subheader("📢 광고 문구 체크")
    if ad["exaggeration"]:
        st.warning("과장 표현: " + ", ".join(f"'{w}'" for w in ad["exaggeration"]))
    if ad["medical"]:
        st.error("의약품으로 오해할 수 있는 표현: " + ", ".join(f"'{w}'" for w in ad["medical"])
                 + "\n\n화장품은 '치료', '재생' 같은 의약품 효능을 광고할 수 없어요.")
    if not (ad["exaggeration"] or ad["medical"]):
        st.success("눈에 띄는 과장 표현이 없어요.")
    st.write("광고 표기(#광고, #협찬 등):", "✅ 있음" if ad["disclosed"] else "❌ 없음 (뒷광고 가능성 확인 필요)")

with right:
    st.subheader("🔎 광고 vs 실제 리뷰")
    if claims:
        st.dataframe(pd.DataFrame(claims), hide_index=True, width="stretch")
    else:
        st.write("비교할 광고 주장이 없어요.")

    st.subheader("💬 리뷰 항목별 반응")
    aspect_df = pd.DataFrame(reviews["aspects"]).T
    aspect_df = aspect_df[aspect_df.sum(axis=1) > 0]
    if not aspect_df.empty:
        st.bar_chart(aspect_df, color=["#2E9E6B", "#E0663B"], horizontal=True)

st.caption("※ 이 분석은 참고용이에요. 피부 반응은 개인차가 있으니 패치 테스트를 권장해요.")
