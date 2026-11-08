"""광고 vs 실제: 광고가 한 말을 하나씩 꺼내서, 리뷰가 그 말을 뒷받침하는지 근거와 함께 정리한다."""

import re

import analyzer as az

# 과장 표현이 왜 문제인지
EXAG_REASON = {
    "100%": "모든 사람에게 똑같은 효과는 있을 수 없어요. 근거가 없는 숫자일 수 있어요.",
    "완벽": "피부 반응은 사람마다 달라서 '완벽'을 보장할 수 없어요.",
    "즉각": "바로 느껴지는 건 대부분 일시적인 사용감이에요. 꾸준한 효과와는 달라요.",
    "즉시": "바로 느껴지는 건 대부분 일시적인 사용감이에요. 꾸준한 효과와는 달라요.",
    "단 하루": "하루 만에 피부가 바뀌는 효과는 근거를 확인해야 해요.",
    "하루만에": "하루 만에 피부가 바뀌는 효과는 근거를 확인해야 해요.",
    "기적": "감정에 호소하는 표현이에요. 구체적인 근거가 없어요.",
    "영구": "화장품 효과는 쓰는 동안에만 유지되는 경우가 대부분이에요.",
    "부작용 없": "모든 사람에게 부작용이 없다고 보장할 수 없어요.",
    "모든 피부": "피부 타입마다 반응이 달라요. 실제 리뷰에서 내 피부 타입 반응을 확인하세요.",
    "누구나": "피부 타입마다 반응이 달라요. 실제 리뷰에서 내 피부 타입 반응을 확인하세요.",
    "1위": "어떤 기관이, 언제, 어떤 기준으로 정한 1위인지 확인해야 해요.",
    "품절대란": "인기를 강조하는 표현이에요. 효과에 대한 근거는 아니에요.",
    "인생템": "개인 경험을 강조하는 표현이에요. 효과에 대한 근거는 아니에요.",
    "역대급": "근거 없이 크게 말하는 표현이에요.",
    "무조건": "피부 반응은 사람마다 달라서 '무조건'은 보장할 수 없어요.",
}
MEDICAL_REASON = ("화장품법은 화장품을 의약품처럼 오해하게 하는 광고(치료·재생·염증 완화 등)를 금지해요. "
                  "실제 효능이 아니라 광고 문구일 가능성이 높아요.")

# 시험·인증 문구가 실제로 뜻하는 것
TEST_CLAIMS = [
    (r"인체\s*(적용)?\s*시험|임상", "인체적용시험",
     "사람에게 발라서 효과를 측정한 시험이에요. 몇 명이, 몇 주 동안, 어떤 기관에서 시험했는지에 따라 결과가 크게 달라요. "
     "상세페이지 아래쪽의 작은 글씨(시험 조건)를 꼭 확인하세요."),
    (r"저자극|자극\s*테스트|피부\s*자극", "저자극 테스트",
     "적은 수의 사람에게 붙여 자극이 적었다는 뜻이에요. 모든 사람에게 자극이 없다는 보장은 아니에요."),
    (r"여드름성\s*피부\s*사용\s*적합|논코메도|코메도", "여드름성 피부 사용 적합",
     "여드름을 '만들' 가능성이 낮은지 확인한 시험이에요. 여드름을 '치료'한다는 뜻은 아니에요."),
    (r"피부과\s*(전문의)?\s*(테스트|시험)", "피부과 테스트",
     "피부과 전문의가 확인한 시험이라는 뜻이에요. 대상 인원과 기간을 함께 확인하세요."),
    (r"비건|vegan", "비건 인증", "동물성 원료를 쓰지 않았다는 뜻이에요. 피부 효과와는 관계가 없어요."),
    (r"EWG|그린\s*등급", "EWG 등급",
     "미국 비영리단체의 성분 안전 정보예요. 공식 인증이 아니며, 자료가 부족해도 좋은 등급이 나올 수 있어요."),
]


def _sentences(text):
    parts = re.split(r"\n|(?<=[.!?])\s+", text)
    return [p.strip(" -•·") for p in parts if len(p.strip(" -•·")) >= 3]


def _where(words, sentences):
    for s in sentences:
        if any(w.lower() in s.lower() for w in words):
            return s
    return ""


def _where_all(words, sentences):
    hits = [s for s in sentences if any(w.lower() in s.lower() for w in words)]
    real = [s for s in hits if not re.fullmatch(r"(#\S+\s*)+", s)]  # 해시태그만 있는 줄은 뒤로
    return real + [s for s in hits if s not in real]


def build(ad_text, reviews, review_text):
    sentences = _sentences(ad_text)
    ad = az.analyze_ad(ad_text)
    claims = az.compare_claims(ad_text, reviews)

    # 1) 효과 주장 하나씩: 광고 문장 + 리뷰 근거
    claim_cards = []
    for c in claims:
        a = c["항목"]
        words = az.ASPECTS[a][0]
        good, bad = reviews["aspects"][a]["좋음"], reviews["aspects"][a]["아쉬움"]
        total = good + bad
        rate = round(good / total * 100) if total else None
        if total == 0:
            why = "리뷰에서 이 내용을 언급한 사람이 없어서 확인할 수 없어요. 광고만 믿기보다는 샘플로 직접 써보세요."
        elif c["판정"].startswith("✅"):
            why = f"이 내용을 언급한 리뷰 {total}개 중 {good}개({rate}%)가 광고와 같은 경험을 했어요."
        elif c["판정"].startswith("❌"):
            why = f"이 내용을 언급한 리뷰 {total}개 중 {bad}개({100 - rate}%)가 광고와 다른 경험을 했어요."
        else:
            why = f"리뷰 {total}개 중 좋다는 의견 {good}개, 아쉽다는 의견 {bad}개로 의견이 갈려요."
        claim_cards.append({
            "aspect": a, "verdict": c["판정"], "ad_sentence": " / ".join(_where_all(words, sentences)[:2]) or c["광고 표현"],
            "good": good, "bad": bad, "rate": rate, "why": why,
            "good_quotes": reviews["quotes"][a]["좋음"][:2], "bad_quotes": reviews["quotes"][a]["아쉬움"][:2],
        })

    # 2) 숫자로 말한 주장 (예: 속피지 개선 41.12%)
    numbers = [s for s in sentences if re.search(r"\d+(\.\d+)?\s*(%|배|시간|주|일)", s) and not re.search(r"원|ml|g\b|개입|\+", s)]
    has_condition = bool(re.search(r"\d+\s*명|시험\s*기관|대상|\d+\s*주\s*(간|사용)", ad_text))

    # 3) 시험·인증 문구
    tests = []
    for pattern, label, meaning in TEST_CLAIMS:
        s = next((x for x in sentences if re.search(pattern, x, re.I)), "")
        if s:
            tests.append({"label": label, "sentence": s, "meaning": meaning})

    # 4) 과장·의약품 오인 표현: 어느 문장에서 나왔는지와 이유
    exaggerations = [{"word": w, "sentence": _where([w], sentences), "reason": EXAG_REASON.get(w, "")}
                     for w in ad["exaggeration"]]
    medical = [{"word": w, "sentence": _where([w], sentences), "reason": MEDICAL_REASON} for w in ad["medical"]]

    # 5) 광고를 언급한 리뷰
    import review_mining as rm
    ad_mentions = []
    for r in az.split_reviews(review_text):
        if re.search(r"광고|상세\s*페이지|홍보|후기 보고|인스타|유튜브", r) and not any(s in r for s in az.SPONSORED):
            ad_mentions.append((r if len(r) <= 120 else r[:120] + "…", rm._tone(r)))

    # 6) 신뢰도 점수가 어떻게 나왔는지
    breakdown = [("기본 점수", 100)]
    for e in exaggerations:
        breakdown.append((f"과장 표현 '{e['word']}'", -10))
    for m in medical:
        breakdown.append((f"의약품 오인 표현 '{m['word']}'", -15))
    for card in claim_cards:
        if card["verdict"].startswith("❌"):
            breakdown.append((f"'{card['aspect']}' 주장이 리뷰와 다름", -15))
        elif card["verdict"].startswith("🔶"):
            breakdown.append((f"'{card['aspect']}' 주장에 대한 의견이 갈림", -5))

    if numbers and not has_condition:
        breakdown.append(("숫자 효과의 시험 조건(인원·기간)을 글에서 확인 못 함 · 직접 확인 필요", 0))
    unchecked = [c["aspect"] for c in claim_cards if c["good"] + c["bad"] == 0]
    for a in unchecked:
        breakdown.append((f"'{a}' 주장은 리뷰로 확인 못 함 · 직접 확인 필요", 0))
    return {"claims": claim_cards, "numbers": numbers, "has_condition": has_condition, "tests": tests,
            "exaggerations": exaggerations, "medical": medical, "ad_mentions": ad_mentions[:6],
            "breakdown": breakdown, "unchecked": unchecked, "disclosed": ad["disclosed"],
            "n_reviews": reviews["count"]}
