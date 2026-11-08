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
    return real or hits


def build(ad_text, reviews, review_text, ing_rows=None, title=""):
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
    numbers = [s for s in sentences if re.search(r"\d+(\.\d+)?\s*(%|배|시간|주|일)", s) and not re.search(r"원|ml|g\b|개입|\+", s)
               and not re.fullmatch(r"[^\d]*100\s*%[^\d]*", s)]  # '100%'만 있는 문장은 과장 표현에서 이미 셈
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

    # 6) 성분이 광고 효과를 뒷받침하는지
    support = az.claim_support(ad_text, ing_rows or [])

    # 7) 신뢰도 점수: 100점에서 항목별로 깎는다 (한 항목이 점수를 다 깎지 않도록 항목마다 최대치가 있음)
    breakdown = [("기본 점수", 100, "")]

    def add(group, items, cap):
        total = 0
        for label, d in items:
            if d < 0 and total <= cap:
                label, d = label + " (이 항목은 최대 감점에 도달)", 0
            elif d < 0:
                d = max(d, cap - total)
            total += d
            breakdown.append((label, d, group))

    add("① 광고 표현", [(f"의약품으로 오해할 표현 '{m['word']}'", -15) for m in medical]
        + [(f"과장 표현 '{e['word']}'", -8) for e in exaggerations], -40)

    big = [n for n in numbers if any(float(x) > 100 for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", n))]
    evid = []
    if not has_condition:
        evid += [(f"숫자 효과 “{n}”의 시험 조건(인원·기간·기관)이 글에 없음", -6) for n in numbers]
        evid += [(f"‘{t['label']}’ 문구에 시험 내용(인원·기간)이 없음", -3) for t in tests]
    if big:
        evid.append((f"100%가 넘는 숫자 “{big[0]}” → 실제 체감보다 크게 느껴질 수 있음", -4))
    add("② 근거 제시", evid, -20)

    rv = []
    for card in claim_cards:
        n = card["good"] + card["bad"]
        if n >= 5:
            d = -round((100 - card["rate"]) / 100 * 25)
            rv.append((f"‘{card['aspect']}’ 주장에 리뷰 {n}개 중 {card['rate']}% 동의", d))
        elif n and card["bad"] > card["good"]:
            rv.append((f"‘{card['aspect']}’ 주장을 언급한 리뷰 {n}개 중 {card['bad']}개가 반대 경험", -10))
        elif n:
            rv.append((f"‘{card['aspect']}’ 주장을 언급한 리뷰가 {n}개뿐이라 근거 부족", -4))
        else:
            rv.append((f"‘{card['aspect']}’ 주장은 리뷰로 확인할 수 없음", -6))
    if reviews["count"] < 10:  # 리뷰를 거의 못 읽었으면 '확인 불가'로 브랜드를 깎지 않음 (앱의 한계라서)
        rv = [(f"리뷰를 {reviews['count']}개밖에 읽지 못해 이 기준은 판단 보류 (리뷰를 붙여넣으면 계산돼요)", 0)]
    sat, _ = az.satisfaction(reviews)
    if sat is not None and sat < 60 and reviews["count"] >= 10:
        rv.append((f"전체 리뷰 만족도가 {sat}%로 낮음", -10))
    add("③ 실제 리뷰와 비교", rv, -35)

    ing = []
    for sp in support:
        if not sp["ok"]:
            ing.append((f"‘{sp['keyword']}’ 효과를 뒷받침하는 대표 성분이 전성분에 없음", -5))
        elif all(f[2] in ("1% 이하", "최대 1%") for f in sp["found"]):
            ing.append((f"‘{sp['keyword']}’ 효과 성분이 1% 이하로만 들어 있음", -3))
        elif len(sp["found"]) == 1:
            ing.append((f"‘{sp['keyword']}’ 효과의 근거 성분이 {sp['found'][0][0]} 1개뿐", -2))
    for t in az.title_check(title, ing_rows or []):
        if t["level"] == "missing":
            ing.append((f"제품 이름의 ‘{t['key']}’ 성분을 전성분에서 찾을 수 없음", -6))
        elif t["level"] == "tiny":
            ing.append((f"제품 이름에 내세운 ‘{t['key']}’ 성분이 극소량 ({t['text'].split('· ')[-1].split('로')[0]})", -4))
    add("④ 성분 근거", ing, -15)

    disappointed = sum(1 for r in az.split_reviews(review_text)
                       if re.search(r"광고|홍보|인스타|유튜브|상세\s*페이지", r) and rm._tone(r) < 0)
    add("⑤ 광고를 보고 산 사람들", [(f"‘광고에 속았다/광고와 다르다’는 리뷰 {disappointed}개", -3 * disappointed)]
        if disappointed else [], -12)

    trust = max(0, min(100, sum(d for _, d, _ in breakdown)))
    unchecked = [c["aspect"] for c in claim_cards if c["good"] + c["bad"] == 0]
    return {"claims": claim_cards, "numbers": numbers, "has_condition": has_condition, "tests": tests,
            "exaggerations": exaggerations, "medical": medical, "ad_mentions": ad_mentions[:6],
            "breakdown": breakdown, "unchecked": unchecked, "disclosed": ad["disclosed"],
            "n_reviews": reviews["count"], "trust": trust, "support": support}
