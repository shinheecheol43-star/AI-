"""광고 말고 진짜 - AI 화장품 판별 봇 (Streamlit).

실행: streamlit run app.py
"""

import base64
import os

import pandas as pd
import streamlit as st

import analyzer as az
from sample_data import SAMPLES

MODEL = "claude-opus-5-5"

st.set_page_config(page_title="광고 말고 진짜", page_icon="🔍", layout="wide")


# ---------------------------------------------------------------------------
# Claude API (선택 기능: 키가 있을 때만 사용)
# ---------------------------------------------------------------------------
def get_client(api_key):
    if not api_key:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def ask_claude(client, content, max_tokens=2000):
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": content}],
    )
    if response.stop_reason == "refusal":
        return "AI가 이 요청에 답하지 않았어요. 입력 내용을 확인해 주세요."
    return "".join(b.text for b in response.content if b.type == "text")


def read_ad_image(client, file):
    """광고 캡처 이미지에서 광고 문구와 성분표를 글자로 뽑아낸다."""
    data = base64.standard_b64encode(file.getvalue()).decode()
    text = ask_claude(client, [
        {"type": "image", "source": {"type": "base64", "media_type": file.type, "data": data}},
        {"type": "text", "text": (
            "이 화장품 광고 이미지에 있는 글자를 그대로 옮겨 적어 주세요. "
            "다음 형식으로만 답하세요.\n[광고]\n(광고 문구, 해시태그 포함)\n[성분]\n(성분표가 보이면 성분, 없으면 비워두기)"
        )},
    ])
    ad, _, ing = text.partition("[성분]")
    return ad.replace("[광고]", "").strip(), ing.strip()


# ---------------------------------------------------------------------------
# 사이드바: 내 기본 정보
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("👤 내 피부 정보")
    skin_type = st.selectbox("피부 타입", az.SKIN_TYPES)
    concerns = st.multiselect("피부 고민", az.CONCERNS, default=["건조/보습"])
    avoid = st.multiselect("피하고 싶은 성분", az.AVOID_OPTIONS)
    st.divider()
    st.subheader("🤖 AI 기능 (선택)")
    api_key = st.text_input("Anthropic API 키", type="password",
                            value=os.environ.get("ANTHROPIC_API_KEY", ""),
                            help="없어도 기본 분석은 됩니다. 키가 있으면 광고 캡처 읽기와 AI 종합 코멘트를 쓸 수 있어요.")

profile = {"skin_type": skin_type, "concerns": concerns, "avoid": avoid}
client = get_client(api_key)

# ---------------------------------------------------------------------------
# 입력
# ---------------------------------------------------------------------------
st.title("🔍 광고 말고 진짜")
st.caption("인스타 광고, 인플루언서 추천 제품을 넣으면 **내 피부 기준으로** 성분, 광고 문구, 실사용 리뷰를 한눈에 분석해 드려요.")

for key in ("ad", "ingredients", "reviews"):
    st.session_state.setdefault(key, "")


def load_sample(name):
    st.session_state.update(SAMPLES[name])


cols = st.columns(len(SAMPLES))
for col, name in zip(cols, SAMPLES):
    col.button(name, on_click=load_sample, args=(name,), width="stretch")

if client:
    image = st.file_uploader("📸 광고 캡처 올리기 (AI가 글자를 읽어 아래 칸에 채워요)", type=["png", "jpg", "jpeg", "webp"])
    if image and st.button("캡처에서 글자 읽기"):
        with st.spinner("AI가 이미지를 읽는 중..."):
            ad_text, ing_text = read_ad_image(client, image)
        st.session_state["ad"] = ad_text
        if ing_text:
            st.session_state["ingredients"] = ing_text
        st.rerun()

c1, c2, c3 = st.columns(3)
c1.text_area("📢 광고 문구 (인스타 캡션 등)", key="ad", height=200)
c2.text_area("🧪 전성분", key="ingredients", height=200, placeholder="정제수, 글리세린, ...")
c3.text_area("💬 실사용 리뷰 (한 줄에 하나씩)", key="reviews", height=200)

if not st.button("🔍 분석하기", type="primary", width="stretch"):
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
st.header("📊 분석 결과")

m1, m2, m3 = st.columns(3)
m1.metric("나와의 적합도", f"{fit}점")
m1.progress(fit / 100)
m2.metric("광고 신뢰도", f"{trust}점")
m2.progress(trust / 100)
if reviews["count"]:
    m3.metric("리뷰 만족도", f"{round(reviews['positive'] / reviews['count'] * 100)}%",
              help=f"리뷰 {reviews['count']}개 중 긍정 {reviews['positive']}개, 부정 {reviews['negative']}개")
st.info(f"**결론:** {az.verdict_text(fit, trust)}")

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
    notes = []
    if reviews["same_skin"]:
        notes.append(f"나와 같은 **{skin_type}** 피부 리뷰 {reviews['same_skin']}개 중 "
                     f"{reviews['same_skin_positive']}개가 긍정적이에요.")
    if reviews["sponsored"]:
        notes.append(f"협찬·체험단 리뷰 {reviews['sponsored']}개는 걸러서 보세요.")
    for n in notes:
        st.write("• " + n)

# ---------------------------------------------------------------------------
# AI 종합 코멘트 (선택)
# ---------------------------------------------------------------------------
if client:
    st.divider()
    st.subheader("🤖 AI 종합 코멘트")
    with st.spinner("AI가 정리하는 중..."):
        comment = ask_claude(client, (
            "당신은 화장품을 고민하는 소비자를 돕는 친절한 상담가입니다. 광고를 그대로 믿지 말고, "
            "아래 분석 결과를 근거로 이 소비자에게 맞는지 한국어로 5줄 이내로 정리해 주세요. "
            "마지막 줄에는 구매 전 확인할 점 하나를 적어 주세요.\n\n"
            f"[내 정보] 피부: {skin_type}, 고민: {', '.join(concerns) or '없음'}, 피하는 성분: {', '.join(avoid) or '없음'}\n"
            f"[광고 문구]\n{ad_text}\n[전성분]\n{ing_text}\n[리뷰]\n{rev_text}\n"
            f"[규칙 기반 분석] 적합도 {fit}점, 광고 신뢰도 {trust}점, 성분 {ingredients}, 광고 비교 {claims}"
        ))
    st.write(comment)

st.caption("※ 이 분석은 참고용이에요. 피부 반응은 개인차가 있으니 패치 테스트를 권장해요.")
