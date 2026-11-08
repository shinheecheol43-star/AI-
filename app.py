"""광고 말고 진짜 - 화장품 광고 판별 봇 (Streamlit, 무료).

실행: streamlit run app.py
"""

import pandas as pd
import streamlit as st

import analyzer as az
import ad_report
import fetcher
import review_mining as rm
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
st.session_state.setdefault("found", "")
st.session_state.setdefault("review_total", 0)


@st.cache_data(ttl=3600, show_spinner=False)
def read_link_cached(url, limit):
    return fetcher.read_link(url, limit)


def load_link():
    url = st.session_state["url"].strip()
    if not url:
        st.session_state["notes"] = ["링크를 입력해 주세요."]
        st.session_state["auto_run"] = False
        return
    try:
        with st.spinner(f"페이지와 리뷰를 읽는 중이에요… (리뷰 {st.session_state['review_limit']}개 기준 약 "
                        f"{max(5, st.session_state['review_limit'] // 4)}초)"):
            result = read_link_cached(url, st.session_state["review_limit"])
    except fetcher.FetchError as e:
        st.session_state.update(notes=[str(e) + " 아래 칸에 직접 붙여넣어 주세요."], auto_run=False, found="")
        return
    st.session_state.update(title=result["title"], ad=result["ad"], ingredients=result["ingredients"],
                            reviews=result["reviews"], notes=result["notes"], auto_run=True,
                            found=_found_summary(result), review_total=result.get("review_total", 0))


def _found_summary(result):
    n_rev = len(result["reviews"].split("\n")) if result["reviews"] else 0
    n_ing = len([x for x in result["ingredients"].split(",") if x.strip()]) if result["ingredients"] else 0
    where = f" ({', '.join(result['sources'])}에서)" if result.get("sources") else ""
    if result.get("review_total", 0) > n_rev:
        where += f" · 전체 {result['review_total']:,}개 중 최근 리뷰"
    mark = lambda ok: "✅" if ok else "❌"
    return (f"링크에서 가져온 정보 · 광고 문구 {mark(result['ad'])} · 전성분 {mark(n_ing)} {n_ing}개 · "
            f"리뷰 {mark(n_rev)} {n_rev}개{where}")


def load_sample(name):
    st.session_state.update(SAMPLES[name], title=name, notes=[], auto_run=False, found="", review_total=0)


u1, u3, u2 = st.columns([4, 1.3, 1], vertical_alignment="bottom")
u1.text_input("🔗 제품 페이지 링크", key="url", placeholder="광고에서 본 제품 페이지 주소를 붙여넣어 주세요 (https://...)")
u3.selectbox("읽을 리뷰 수", [30, 100, 200], index=1, key="review_limit",
             help="많이 읽을수록 정확하지만 오래 걸려요. (100개 약 25초) 같은 링크는 1시간 동안 바로 다시 볼 수 있어요.")
u2.button("분석하기 ✨", on_click=load_link, type="primary", width="stretch")

if st.session_state["found"]:
    st.info(st.session_state["found"])
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
        total = st.session_state.get("review_total", 0)
        base = f"전체 {total:,}개 중 최근 {reviews['count']}개" if total > reviews["count"] else f"리뷰 {reviews['count']}개"
        ui.score_card("리뷰 만족도", sat, "%", f"{base} 기준 (협찬 제외)")
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
        ui.section("🔁 리뷰에서 많이 나온 이야기", "여러 사람이 반복해서 쓴 단어를 찾아 비슷한 문장끼리 묶었어요.")
        ui.topic_cards(rm.mine(rev_text)["topics"])
        ui.section("💬 항목별 반응", "초록은 좋다는 의견, 빨강은 아쉽다는 의견이에요.")
        ui.aspect_bars(reviews["aspects"])
        with st.expander("숫자로 자세히 보기"):
            st.markdown(summary["text"])
            if reviews["by_skin"]:
                st.dataframe(pd.DataFrame(reviews["by_skin"]).T, width="stretch")
    else:
        ui.show('<div class="card"><b>😢 이 페이지에서 리뷰를 가져오지 못했어요.</b>'
                '<div class="muted" style="margin-top:6px">많은 쇼핑몰은 리뷰를 페이지가 열린 뒤 따로 불러와서, '
                '링크만으로는 리뷰 글이 보이지 않아요.<br>쇼핑몰 리뷰 화면에서 리뷰 글을 길게 눌러 <b>복사</b>한 뒤, '
                '위의 <b>‘직접 붙여넣기’ → 실사용 리뷰</b> 칸에 붙여넣고 분석하기를 누르면 요약해 드려요.</div></div>')

with tab_ing:
    ui.section("🧪 내 피부 기준 성분 분석", f"{skin_type} 피부 · 고민: {', '.join(concerns) or '없음'}"
               f" · 피하는 성분: {', '.join(avoid) or '없음'}")
    ing_rows, ing_summary = az.ingredient_report(ing_text, profile)
    if ing_rows:
        ui.ingredient_summary(ing_summary)
        ui.section("📋 성분 하나씩 보기", "적힌 순서대로예요. 번호가 작을수록 많이 들어 있어요.")
        ui.ingredient_list(ing_rows)
        if ing_summary["guessed"]:
            st.caption(f"‘이름으로 추정’ 표시된 {ing_summary['guessed']}개는 사전에 없어서 성분 이름 모양으로 분류했어요.")
    else:
        ui.show('<div class="card muted">분석할 수 있는 성분이 없어요. 전성분을 붙여넣어 주세요.</div>')

with tab_ad:
    rep = ad_report.build(ad_text, reviews, rev_text)
    ui.section(f"📊 광고 신뢰도 {trust}점은 이렇게 나왔어요", "100점에서 시작해 문제가 있을 때마다 깎았어요.")
    ui.trust_breakdown(trust, rep["breakdown"])

    ui.section("🔎 광고에서 말한 효과, 리뷰로 확인해 봤어요",
               "광고 문장 → 그 내용을 언급한 리뷰 → 실제 리뷰 순서로 보여드려요.")
    if not ad_text:
        ui.show('<div class="card muted">광고 문구가 없어서 비교할 수 없어요.</div>')
    elif not reviews["count"]:
        ui.show('<div class="card muted">리뷰가 없어서 광고 내용과 비교할 수 없어요. '
                '리뷰를 붙여넣으면 광고가 진짜인지 비교해 드려요.</div>')
    elif rep["claims"]:
        ui.claim_cards(rep["claims"], rep["n_reviews"])
        if rep["unchecked"]:
            st.caption(f"리뷰로 확인하지 못한 주장: {', '.join(rep['unchecked'])} → 샘플로 직접 확인해 보는 게 좋아요.")
    else:
        ui.show('<div class="card muted">광고에서 보습·진정·트러블 같은 효과 주장을 찾지 못했어요.</div>')

    ui.section("🔢 숫자·시험 결과 광고, 이렇게 읽으세요")
    ui.number_and_tests(rep["numbers"], rep["has_condition"], rep["tests"])

    ui.section("😮 조심해서 볼 광고 표현")
    ui.flagged_words(rep["exaggerations"], rep["medical"], rep["disclosed"])

    ui.section("🗣️ 광고를 언급한 실제 리뷰", "‘광고’, ‘인스타’, ‘상세페이지’ 등을 언급한 리뷰예요.")
    ui.ad_mentions(rep["ad_mentions"])

st.caption("※ 이 분석은 참고용이에요. 피부 반응은 개인차가 있으니 패치 테스트를 권장해요.")
