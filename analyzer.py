"""광고 말고 진짜 - 분석 로직 (API 키 없이도 동작하는 규칙 기반 분석)."""

import re

# ---------------------------------------------------------------------------
# 1. 성분 사전: 이름(별칭) / 역할 / 잘 맞는 고민·피부 / 주의할 피부·민감 항목
# ---------------------------------------------------------------------------
INGREDIENTS = {
    "나이아신아마이드": {"alias": ["나이아신아마이드", "niacinamide"], "role": "미백·피지 조절",
                  "good": ["미백/잡티", "모공", "여드름/트러블"], "caution": []},
    "히알루론산": {"alias": ["히알루론산", "소듐하이알루로네이트", "하이알루로닉애씨드", "hyaluronic"], "role": "수분 공급",
               "good": ["건조/보습", "건성"], "caution": []},
    "세라마이드": {"alias": ["세라마이드", "ceramide"], "role": "피부 장벽 강화",
              "good": ["건조/보습", "건성", "민감성", "진정/홍조"], "caution": []},
    "판테놀": {"alias": ["판테놀", "panthenol"], "role": "진정·보습",
            "good": ["진정/홍조", "민감성", "건조/보습"], "caution": []},
    "병풀추출물": {"alias": ["병풀추출물", "센텔라", "시카", "centella"], "role": "진정",
              "good": ["진정/홍조", "민감성", "여드름/트러블"], "caution": []},
    "마데카소사이드": {"alias": ["마데카소사이드", "madecassoside"], "role": "진정·재생 보조",
                "good": ["진정/홍조", "민감성"], "caution": []},
    "살리실릭애씨드(BHA)": {"alias": ["살리실릭애씨드", "살리실산", "bha", "salicylic"], "role": "각질·피지 제거",
                       "good": ["지성", "여드름/트러블", "모공"], "caution": ["건성", "민감성"]},
    "글라이콜릭애씨드(AHA)": {"alias": ["글라이콜릭애씨드", "aha", "glycolic"], "role": "각질 제거",
                         "good": ["미백/잡티", "모공"], "caution": ["민감성"]},
    "레티놀": {"alias": ["레티놀", "레티날", "retinol"], "role": "주름 개선",
            "good": ["주름/탄력"], "caution": ["민감성"]},
    "티트리": {"alias": ["티트리", "tea tree"], "role": "트러블 진정",
            "good": ["여드름/트러블", "지성"], "caution": ["민감성", "에센셜오일"]},
    "비타민C": {"alias": ["아스코빅애씨드", "비타민c", "ascorbic"], "role": "미백·항산화",
             "good": ["미백/잡티"], "caution": ["민감성"]},
    "아데노신": {"alias": ["아데노신", "adenosine"], "role": "주름 개선(기능성)",
             "good": ["주름/탄력"], "caution": []},
    "알부틴": {"alias": ["알부틴", "arbutin"], "role": "미백(기능성)",
            "good": ["미백/잡티"], "caution": []},
    "스쿠알란": {"alias": ["스쿠알란", "squalane"], "role": "보습 오일",
             "good": ["건조/보습", "건성"], "caution": []},
    "시어버터": {"alias": ["시어버터", "shea"], "role": "고보습",
             "good": ["건성", "건조/보습"], "caution": ["지성", "여드름/트러블"]},
    "코코넛오일": {"alias": ["코코넛오일", "코코스야자오일", "coconut"], "role": "보습 오일",
              "good": ["건성"], "caution": ["지성", "여드름/트러블"]},
    "미네랄오일": {"alias": ["미네랄오일", "mineral oil"], "role": "보습막 형성",
              "good": ["건성"], "caution": ["지성", "여드름/트러블"]},
    "이소프로필미리스테이트": {"alias": ["이소프로필미리스테이트"], "role": "사용감 개선",
                     "good": [], "caution": ["지성", "여드름/트러블"]},
    "에탄올(알코올)": {"alias": ["에탄올", "변성알코올", "alcohol denat"], "role": "산뜻한 사용감",
                  "good": ["지성"], "caution": ["건성", "민감성", "알코올"]},
    "향료": {"alias": ["향료", "fragrance", "parfum"], "role": "향",
           "good": [], "caution": ["민감성", "향료"]},
    "리모넨": {"alias": ["리모넨", "limonene"], "role": "향 성분(알레르기 유발 표시 성분)",
            "good": [], "caution": ["민감성", "향료"]},
    "리날룰": {"alias": ["리날룰", "linalool"], "role": "향 성분(알레르기 유발 표시 성분)",
            "good": [], "caution": ["민감성", "향료"]},
    "파라벤": {"alias": ["파라벤", "paraben"], "role": "방부제",
            "good": [], "caution": ["파라벤"]},
    "징크옥사이드": {"alias": ["징크옥사이드", "zinc oxide"], "role": "무기자차 성분",
               "good": ["민감성"], "caution": []},
    "에칠헥실메톡시신나메이트": {"alias": ["에칠헥실메톡시신나메이트"], "role": "유기자차 성분",
                      "good": [], "caution": ["민감성"]},
}

SKIN_TYPES = ["건성", "지성", "복합성", "중성", "민감성"]
CONCERNS = ["여드름/트러블", "건조/보습", "미백/잡티", "주름/탄력", "모공", "진정/홍조"]
AVOID_OPTIONS = ["향료", "알코올", "파라벤", "에센셜오일"]


def analyze_ingredients(text, profile):
    """성분표 텍스트에서 아는 성분을 찾아 내 프로필 기준으로 좋음/주의로 분류."""
    # 쉼표·줄바꿈으로 나눈 성분 이름의 '앞부분'으로 비교 (페녹시에탄올이 에탄올로 잡히지 않도록)
    tokens = [t.strip().lower() for t in re.split(r"[,\n/·]", text) if t.strip()]
    mine = {profile["skin_type"], *profile["concerns"], *profile["avoid"]}
    rows = []
    for name, info in INGREDIENTS.items():
        if not any(t.startswith(a.lower()) for t in tokens for a in info["alias"]):
            continue
        good = [g for g in info["good"] if g in mine]
        bad = [c for c in info["caution"] if c in mine]
        if bad:
            verdict = "⚠️ 주의"
        elif good:
            verdict = "✅ 잘 맞음"
        else:
            verdict = "➖ 보통"
        reason = ", ".join(bad or good) or "-"
        rows.append({"성분": name, "역할": info["role"], "나에게": verdict, "이유": reason})
    order = {"⚠️ 주의": 0, "✅ 잘 맞음": 1, "➖ 보통": 2}
    rows.sort(key=lambda r: order[r["나에게"]])
    return rows


# ---------------------------------------------------------------------------
# 2. 광고 문구 분석: 과장 표현 / 의약품 오인 표현 / 광고 표기 여부
# ---------------------------------------------------------------------------
EXAGGERATION = ["100%", "완벽", "즉각", "즉시", "단 하루", "하루만에", "기적", "영구", "부작용 없",
                "모든 피부", "누구나", "1위", "품절대란", "인생템", "역대급", "무조건"]
MEDICAL = ["치료", "재생", "아토피", "여드름 개선", "흉터", "염증", "세포", "처방", "의학적"]
AD_DISCLOSURE = ["#광고", "#협찬", "유료광고", "유료 광고", "제공받", "협찬", "#ad", "paid partnership"]


def _find(words, text):
    low = text.lower()
    return [w for w in words if w.lower() in low]


def analyze_ad(text):
    return {
        "exaggeration": _find(EXAGGERATION, text),
        "medical": _find(MEDICAL, text),
        "disclosed": bool(_find(AD_DISCLOSURE, text)),
    }


# ---------------------------------------------------------------------------
# 3. 리뷰 분석 + 광고 주장 vs 실제 리뷰 비교
#    각 항목: (광고에서 주장할 때 쓰는 말, 리뷰 긍정 표현, 리뷰 부정 표현)
# ---------------------------------------------------------------------------
ASPECTS = {
    "보습": (["보습", "수분", "촉촉"], ["촉촉", "보습", "수분감", "건조하지 않"], ["건조", "당김", "당겨"]),
    "진정/순함": (["진정", "순한", "자극 없", "민감"], ["진정", "순하", "자극 없", "편안"], ["따가", "자극", "붉어", "가려"]),
    "산뜻함": (["산뜻", "가벼운", "끈적임 없", "보송"], ["산뜻", "가볍", "보송", "끈적임 없", "흡수 빠", "흡수가 빠"], ["끈적", "무거", "번들", "기름"]),
    "트러블": (["트러블", "여드름", "피지", "모공"], ["트러블 없", "트러블이 줄", "트러블 안", "좁쌀이 들어"], ["트러블", "뾰루지", "올라왔", "좁쌀"]),
    "미백/톤업": (["미백", "톤업", "브라이트닝", "잡티", "광채"], ["톤업", "밝아", "환해", "화사"], ["효과 없", "변화 없", "모르겠"]),
    "백탁": (["백탁"], ["백탁 없", "백탁이 없"], ["백탁", "회색", "하얗게 떠"]),
    "향": (["향"], ["향 좋", "향이 좋", "은은"], ["향이 강", "향이 너무", "냄새", "향 별로"]),
}
POSITIVE = ["좋", "추천", "재구매", "만족", "최고", "인생템", "괜찮"]
NEGATIVE = ["별로", "비추", "실망", "안 맞", "안맞", "환불", "최악", "다시는", "아쉽"]
SPONSORED = ["제공받", "협찬", "체험단", "서포터즈"]


def _aspect_hit(review, pos, neg):
    """리뷰 하나에서 항목의 긍정(1)/부정(-1)/언급 없음(0)."""
    if any(p in review for p in pos):
        return 1
    stripped = review
    for p in pos:
        stripped = stripped.replace(p, "")
    if any(n in stripped for n in neg):
        return -1
    return 0


def analyze_reviews(text, skin_type):
    reviews = [r.strip() for r in re.split(r"\n+", text) if len(r.strip()) > 3]
    result = {"count": len(reviews), "positive": 0, "negative": 0, "sponsored": 0,
              "same_skin": 0, "same_skin_positive": 0,
              "aspects": {a: {"좋음": 0, "아쉬움": 0} for a in ASPECTS}}
    for r in reviews:
        if any(s in r for s in SPONSORED):
            result["sponsored"] += 1
        neg = any(n in r for n in NEGATIVE)
        pos = any(p in r for p in POSITIVE) and not neg
        result["positive"] += pos
        result["negative"] += neg
        if skin_type in r:
            result["same_skin"] += 1
            result["same_skin_positive"] += pos
        for a, (_, p_words, n_words) in ASPECTS.items():
            hit = _aspect_hit(r, p_words, n_words)
            if hit == 1:
                result["aspects"][a]["좋음"] += 1
            elif hit == -1:
                result["aspects"][a]["아쉬움"] += 1
    return result


def compare_claims(ad_text, reviews):
    """광고가 주장한 항목을 실제 리뷰와 비교."""
    rows = []
    for a, (claim_words, _, _) in ASPECTS.items():
        claimed = _find(claim_words, ad_text)
        if not claimed:
            continue
        good, bad = reviews["aspects"][a]["좋음"], reviews["aspects"][a]["아쉬움"]
        if good + bad == 0:
            verdict = "❔ 리뷰에서 확인 불가"
        elif good >= bad * 2:
            verdict = "✅ 광고와 일치"
        elif bad > good:
            verdict = "❌ 광고와 다름"
        else:
            verdict = "🔶 의견 갈림"
        rows.append({"항목": a, "광고 표현": ", ".join(claimed),
                     "리뷰 (좋음/아쉬움)": f"{good} / {bad}", "판정": verdict})
    return rows


# ---------------------------------------------------------------------------
# 4. 종합 점수
# ---------------------------------------------------------------------------
def scores(ingredients, ad, reviews, claims):
    good = sum(r["나에게"] == "✅ 잘 맞음" for r in ingredients)
    bad = sum(r["나에게"] == "⚠️ 주의" for r in ingredients)
    fit = 60 + good * 8 - bad * 12
    if reviews["same_skin"]:
        rate = reviews["same_skin_positive"] / reviews["same_skin"]
        fit += round((rate - 0.5) * 30)
    fit = max(0, min(100, fit))

    trust = 100 - len(ad["exaggeration"]) * 10 - len(ad["medical"]) * 15
    trust -= sum(c["판정"] == "❌ 광고와 다름" for c in claims) * 15
    trust -= sum(c["판정"] == "🔶 의견 갈림" for c in claims) * 5
    trust = max(0, min(100, trust))
    return fit, trust


def verdict_text(fit, trust):
    if fit >= 70 and trust >= 60:
        return "👍 나에게 잘 맞을 가능성이 높아요. 구매를 고려해 보세요."
    if fit >= 70:
        return "🤔 성분은 잘 맞지만 광고가 과장됐을 수 있어요. 샘플로 먼저 써보세요."
    if fit >= 45:
        return "🤔 보통이에요. 주의 성분과 리뷰의 아쉬운 점을 확인해 보세요."
    return "✋ 나에게는 맞지 않을 가능성이 높아요. 다른 제품을 추천해요."
