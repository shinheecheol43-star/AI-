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
    "알부틴": {"alias": ["알부틴", "알파-알부틴", "알파-아르부틴", "아르부틴", "arbutin"], "role": "미백(기능성)",
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
    "정제수": {"alias": ["정제수", "water", "aqua"], "role": "기본 베이스(물)", "good": [], "caution": []},
    "글리세린": {"alias": ["글리세린", "glycerin"], "role": "기본 보습", "good": ["건조/보습"], "caution": []},
    "부틸렌글라이콜": {"alias": ["부틸렌글라이콜", "butylene glycol"], "role": "보습·용매", "good": [], "caution": []},
    "프로판다이올": {"alias": ["프로판다이올", "propanediol"], "role": "보습·용매", "good": [], "caution": []},
    "1,2-헥산다이올": {"alias": ["1,2-헥산다이올", "헥산다이올", "hexanediol"], "role": "보습·보존 보조", "good": [], "caution": []},
    "베타인": {"alias": ["베타인", "betaine"], "role": "보습", "good": ["건조/보습", "민감성"], "caution": []},
    "알란토인": {"alias": ["알란토인", "allantoin"], "role": "진정", "good": ["진정/홍조", "민감성"], "caution": []},
    "토코페롤": {"alias": ["토코페롤", "tocopherol"], "role": "항산화(비타민E)", "good": [], "caution": []},
    "스쿠알렌/트라이글리세라이드": {"alias": ["카프릴릭/카프릭트라이글리세라이드", "카프릴릭"], "role": "보습 오일", "good": ["건성"], "caution": ["지성"]},
    "다이메티콘": {"alias": ["다이메티콘", "dimethicone"], "role": "실리콘(매끄러운 사용감)", "good": [], "caution": ["여드름/트러블"]},
    "카보머": {"alias": ["카보머", "carbomer"], "role": "점도 조절", "good": [], "caution": []},
    "잔탄검": {"alias": ["잔탄검", "xanthan"], "role": "점도 조절", "good": [], "caution": []},
    "페녹시에탄올": {"alias": ["페녹시에탄올", "phenoxyethanol"], "role": "방부제", "good": [], "caution": []},
    "다이소듐이디티에이": {"alias": ["다이소듐이디티에이", "disodium edta"], "role": "안정제", "good": [], "caution": []},
    "트로메타민": {"alias": ["트로메타민", "tromethamine"], "role": "pH 조절", "good": [], "caution": []},
    "아줄렌": {"alias": ["아줄렌", "구아이아줄렌", "azulene"], "role": "진정", "good": ["진정/홍조", "민감성"], "caution": []},
    "녹차추출물": {"alias": ["녹차추출물", "녹차잎추출물", "green tea"], "role": "진정·피지 조절", "good": ["지성", "여드름/트러블"], "caution": []},
    "어성초추출물": {"alias": ["어성초추출물", "약모밀추출물"], "role": "트러블 진정", "good": ["여드름/트러블", "지성"], "caution": []},
    "쑥추출물": {"alias": ["쑥추출물", "쑥잎추출물", "artemisia"], "role": "진정", "good": ["진정/홍조", "민감성"], "caution": []},
    "프로폴리스": {"alias": ["프로폴리스", "propolis"], "role": "영양·진정", "good": ["건조/보습"], "caution": ["민감성"]},
    "펩타이드": {"alias": ["펩타이드", "peptide"], "role": "탄력", "good": ["주름/탄력"], "caution": []},
    "콜라겐": {"alias": ["콜라겐", "하이드롤라이즈드콜라겐", "collagen"], "role": "보습·탄력", "good": ["주름/탄력", "건조/보습"], "caution": []},
    "징크피씨에이": {"alias": ["징크피씨에이", "징크pca", "zinc pca"], "role": "피지 조절", "good": ["지성", "모공", "여드름/트러블"], "caution": []},
    "위치하젤": {"alias": ["위치하젤", "witch hazel"], "role": "수렴·피지 조절", "good": ["지성", "모공"], "caution": ["건성", "민감성"]},
    "멘톨": {"alias": ["멘톨", "menthol"], "role": "청량감", "good": [], "caution": ["민감성"]},
    "에센셜오일": {"alias": ["라벤더오일", "오렌지껍질오일", "레몬껍질오일", "로즈마리잎오일", "유칼립투스잎오일"], "role": "향 오일", "good": [], "caution": ["민감성", "에센셜오일", "향료"]},
    "판토텐산/비타민": {"alias": ["바이오틴", "biotin"], "role": "영양", "good": [], "caution": []},
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
    # 사전에 없는 성분도 빠뜨리지 않고 보여준다
    aliases = [a.lower() for info in INGREDIENTS.values() for a in info["alias"]]
    for t in tokens:
        name = re.sub(r"\(.*?\)|[\[\]*]", "", t).strip()
        if 2 <= len(name) <= 30 and not any(name.startswith(a) for a in aliases):
            rows.append({"성분": name, "역할": "정보 없음", "나에게": "❔ 사전에 없음", "이유": "-"})
    order = {"⚠️ 주의": 0, "✅ 잘 맞음": 1, "➖ 보통": 2, "❔ 사전에 없음": 3}
    rows = list({r["성분"]: r for r in rows}.values())
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
    "보습": (["보습", "수분", "촉촉"], ["촉촉", "보습력 좋", "보습이 잘", "수분감", "건조하지 않", "안 당기", "속건조 해결"],
           ["건조", "당김", "당겨", "보습이 부족", "보습력이 약"]),
    "진정/순함": (["진정", "순한", "자극 없", "민감"], ["진정", "순하", "순해", "자극 없", "자극이 없", "편안", "붉은기가 가라"],
              ["따가", "따끔", "자극", "붉어", "가려", "화끈"]),
    "산뜻함": (["산뜻", "가벼운", "끈적임 없", "보송"], ["산뜻", "가볍", "보송", "끈적임 없", "끈적이지 않", "안 끈적"],
            ["끈적", "무거", "번들", "기름", "답답"]),
    "흡수": (["흡수"], ["흡수 빠", "흡수가 빠", "흡수가 잘", "스며"], ["흡수가 안", "흡수가 느", "겉돌", "밀려", "밀림"]),
    "트러블": (["트러블", "여드름", "피지", "모공"], ["트러블 없", "트러블이 없", "트러블이 줄", "트러블 안", "좁쌀이 들어", "여드름이 줄", "진정됐", "진정되", "진정이 잘", "가라앉", "사라졌", "들어갔", "들어가", "덜남", "덜 나", "트러블 덜", "트러블이 덜", "줄어", "없어졌", "안 나", "안나"],
            ["트러블", "뾰루지", "올라왔", "좁쌀", "여드름이 났", "여드름 났"]),
    "미백/톤업": (["미백", "톤업", "브라이트닝", "잡티", "광채"], ["톤업", "밝아", "환해", "화사", "잡티가 옅"],
              ["변화 없", "변화가 없", "톤업이 안", "어두워"]),
    "효과": (["효과", "개선", "인체 시험", "임상"], ["효과가 좋", "효과 좋", "효과가 눈에", "효과 있", "효과가 있", "효과를 봤", "효과 봤", "효과가 바로"],
           ["효과 없", "효과가 없", "효과를 못", "효과는 잘", "모르겠", "그대로"]),
    "백탁": (["백탁"], ["백탁 없", "백탁이 없"], ["백탁", "회색", "하얗게 떠"]),
    "지속력": (["하루종일", "지속", "오래", "24시간"], ["하루종일 촉촉", "유지력 좋", "지속력 좋", "오래 유지"], ["금방", "오후에", "무너져", "무너지", "무너짐", "날아가"]),
    "향": (["향"], ["향 좋", "향이 좋", "은은", "향이 없어", "무향"], ["향이 강", "향이 너무", "냄새", "향 별로", "향이 별로"]),
    "가격": (["가성비", "합리적", "착한 가격"], ["가성비 좋", "가성비 최고", "가성비가 좋", "저렴", "싸게", "가격도 착"],
           ["비싸", "가격이 부담", "가성비 별로", "가격 대비"]),
}
POSITIVE = ["좋", "추천", "재구매", "만족", "최고", "인생템", "괜찮", "강추", "대박", "짱", "잘 맞", "또 살"]
NEGATIVE = ["별로", "비추", "실망", "안 맞", "안맞", "환불", "최악", "다시는", "아쉽", "아쉬", "안 좋", "좋지 않",
            "좋진 않", "좋지는 않", "그닥", "글쎄", "버렸", "안 살"]
SPONSORED = ["제공받", "협찬", "체험단", "서포터즈", "무상으로", "원고료"]
# 리뷰 속 피부 타입 표현 → 앱의 피부 타입
SKIN_WORDS = {"건성": ["건성", "건조한 피부", "악건성"], "지성": ["지성", "기름진 피부"],
              "복합성": ["복합성", "수부지"], "중성": ["중성"], "민감성": ["민감성", "민감한 피부", "예민한 피부"]}
# 사이트에서 복사할 때 섞여 들어오는 잡음 줄
NOISE = ["도움이 돼요", "도움돼요", "신고", "더보기", "답글", "판매자", "구매확정", "옵션:", "작성일"]
CLAUSE_SPLIT = re.compile(r"은데|는데|지만|근데|그런데|하지만|그러나|다만|[.!?~,\n]")


def _clauses(review):
    return [c.strip() for c in CLAUSE_SPLIT.split(review) if c.strip()]


def _polarity(text):
    """문장 조각의 긍정(1)/부정(-1)/중립(0). '안 좋', '좋지 않'처럼 부정이 붙으면 부정."""
    if any(n in text for n in NEGATIVE):
        return -1
    if any(p in text for p in POSITIVE):
        return 1
    return 0


def _aspect_hit(clause, pos, neg, topic=()):
    """문장 조각 하나에서 항목의 긍정(1)/부정(-1)/언급 없음(0)."""
    if any(p in clause for p in pos):
        return 1
    stripped = clause
    for p in pos:
        stripped = stripped.replace(p, "")
    if any(n in stripped for n in neg):
        return -1
    if topic and any(t in clause for t in topic):
        return _polarity(clause)  # "보습은 좋아요"처럼 항목 이름 + 좋다/별로
    return 0


def _skin_types(review):
    return [s for s, words in SKIN_WORDS.items() if any(w in review for w in words)]


def _short(text, n=60):
    return text if len(text) <= n else text[:n] + "…"


def split_reviews(text):
    out = []
    for r in re.split(r"\n+", text):
        r = re.sub(r"\s+", " ", r).strip()
        if len(r) < 6 or any(w in r for w in NOISE) or re.fullmatch(r"[\d.\-/: ★☆점]+", r):
            continue
        out.append(r)
    return list(dict.fromkeys(out))


def analyze_reviews(text, skin_type):
    """협찬 리뷰는 따로 세고, 나머지 리뷰만으로 통계를 낸다."""
    all_reviews = split_reviews(text)
    sponsored = [r for r in all_reviews if any(s in r for s in SPONSORED)]
    reviews = [r for r in all_reviews if r not in sponsored]
    result = {"count": len(reviews), "positive": 0, "negative": 0, "mixed": 0,
              "sponsored": len(sponsored), "same_skin": 0, "same_skin_positive": 0,
              "aspects": {a: {"좋음": 0, "아쉬움": 0} for a in ASPECTS},
              "quotes": {a: {"좋음": [], "아쉬움": []} for a in ASPECTS},
              "by_skin": {}}
    for r in reviews:
        hits = {}
        for clause in _clauses(r):
            for a, (topic, p_words, n_words) in ASPECTS.items():
                hit = _aspect_hit(clause, p_words, n_words, topic)
                if hit:
                    hits[a] = hit  # 같은 리뷰에서 뒤에 나온 의견을 우선
        for a, hit in hits.items():
            key = "좋음" if hit == 1 else "아쉬움"
            result["aspects"][a][key] += 1
            result["quotes"][a][key].append(_short(r))

        # 리뷰 전체의 느낌: 조각별 긍정/부정 + 항목별 평가를 합쳐서 판단
        pols = [_polarity(c) for c in _clauses(r)] + list(hits.values())
        pos, neg = pols.count(1), pols.count(-1)
        if pos and neg:
            label = "mixed"
        elif pos:
            label = "positive"
        elif neg:
            label = "negative"
        else:
            label = None
        if label:
            result[label] += 1

        for s in _skin_types(r):
            row = result["by_skin"].setdefault(s, {"리뷰 수": 0, "긍정": 0, "부정": 0, "혼합": 0})
            row["리뷰 수"] += 1
            if label:
                row[{"positive": "긍정", "negative": "부정", "mixed": "혼합"}[label]] += 1
        if skin_type in _skin_types(r):
            result["same_skin"] += 1
            result["same_skin_positive"] += label == "positive"
    return result


def summarize_reviews(reviews, skin_type):
    """통계를 사람이 읽기 쉬운 요약 문장과 좋은 점/아쉬운 점 TOP 3로 만든다."""
    n = reviews["count"]
    if n == 0:
        return {"text": "분석할 리뷰가 없어요.", "good": [], "bad": []}
    aspects = reviews["aspects"]
    good = sorted((a for a in aspects if aspects[a]["좋음"]), key=lambda a: -aspects[a]["좋음"])[:3]
    bad = sorted((a for a in aspects if aspects[a]["아쉬움"]), key=lambda a: -aspects[a]["아쉬움"])[:3]

    pos_rate = round(reviews["positive"] / n * 100)
    lines = [f"리뷰 {n}개 중 **긍정 {reviews['positive']}개, 부정 {reviews['negative']}개, "
             f"장단점이 섞인 리뷰 {reviews['mixed']}개**예요."]
    if reviews["sponsored"]:
        lines[0] += f" (협찬·체험단 리뷰 {reviews['sponsored']}개는 빼고 계산했어요)"
    if good:
        lines.append("좋다는 의견은 주로 **" + ", ".join(f"{a} {aspects[a]['좋음']}건" for a in good) + "**에 대한 거예요.")
    if bad:
        lines.append("아쉽다는 의견은 주로 **" + ", ".join(f"{a} {aspects[a]['아쉬움']}건" for a in bad) + "**에 대한 거예요.")

    by_skin = reviews["by_skin"]
    skin_notes = []
    for s, row in by_skin.items():
        if row["긍정"] > row["부정"] + row["혼합"]:
            skin_notes.append(f"{s} 😊 대체로 만족")
        elif row["부정"] + row["혼합"] > row["긍정"]:
            skin_notes.append(f"{s} 😥 아쉬움이 많음")
    if skin_notes:
        lines.append("피부 타입별 반응: " + ", ".join(skin_notes))
    if skin_type in by_skin:
        row = by_skin[skin_type]
        lines.append(f"나와 같은 **{skin_type}** 리뷰는 {row['리뷰 수']}개이고, 그중 긍정은 {row['긍정']}개예요.")
    else:
        lines.append(f"나와 같은 **{skin_type}** 피부라고 밝힌 리뷰는 없었어요.")

    if pos_rate >= 70:
        lines.append("👉 전반적으로 **평이 좋은 제품**이에요.")
    elif reviews["negative"] + reviews["mixed"] > reviews["positive"]:
        lines.append("👉 **호불호가 갈리거나 아쉬운 평이 많은 제품**이에요. 아쉬운 점이 나에게 중요한지 확인해 보세요.")
    else:
        lines.append("👉 **평이 무난한 제품**이에요.")

    q = reviews["quotes"]
    return {"text": "\n\n".join(lines),
            "good": [(a, aspects[a]["좋음"], q[a]["좋음"][0]) for a in good],
            "bad": [(a, aspects[a]["아쉬움"], q[a]["아쉬움"][0]) for a in bad]}


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


# ---------------------------------------------------------------------------
# 5. 총평: 리뷰, 피부 타입, 광고 비교 결과를 이어지는 문장으로 정리
# ---------------------------------------------------------------------------
GOOD_PHRASE = {"효과": "눈에 보이는 효과", "보습": "보습력", "진정/순함": "순하고 진정되는 느낌", "산뜻함": "산뜻한 사용감", "흡수": "빠른 흡수",
               "트러블": "트러블이 적은 점", "미백/톤업": "톤업 효과", "백탁": "백탁이 없는 점", "지속력": "지속력",
               "향": "향", "가격": "가성비"}
BAD_PHRASE = {"효과": "효과를 못 느낀 점", "보습": "건조함", "진정/순함": "자극", "산뜻함": "끈적임", "흡수": "잘 흡수되지 않는 점",
              "트러블": "트러블", "미백/톤업": "효과를 못 느낀 점", "백탁": "백탁", "지속력": "짧은 지속력",
              "향": "향", "가격": "가격"}


def _josa(word, pair):
    """받침에 따라 조사 고르기. pair 예: ('이', '가'), ('은', '는'), ('과', '와')"""
    last = word[-1]
    if "가" <= last <= "힣":
        return word + (pair[0] if (ord(last) - 0xAC00) % 28 else pair[1])
    return word + pair[0]


def _join(words):
    if len(words) == 1:
        return words[0]
    return ", ".join(words[:-1]) + ", " + words[-1] if len(words) > 2 else _josa(words[0], ("과", "와")) + " " + words[1]


def overall_comment(reviews, claims, skin_type, fit):
    n = reviews["count"]
    if n == 0:
        return "리뷰가 없어서 총평을 만들 수 없어요."
    aspects = reviews["aspects"]
    good = sorted((a for a in aspects if aspects[a]["좋음"]), key=lambda a: -aspects[a]["좋음"])[:2]
    bad = sorted((a for a in aspects if aspects[a]["아쉬움"]), key=lambda a: -aspects[a]["아쉬움"])[:2]
    pos, neg, mixed = reviews["positive"], reviews["negative"], reviews["mixed"]
    out = []

    # 1) 전체 분위기
    if pos >= (neg + mixed) * 2:
        out.append("전체적으로 **만족한다는 평이 많은 제품**이에요.")
    elif neg > pos + mixed:
        out.append("전체적으로 **아쉽다는 평이 더 많은 제품**이에요.")
    else:
        out.append("**호불호가 갈리는 제품**이에요.")

    # 2) 장점과 단점
    if good and bad:
        out.append(f"사용자들은 {_josa(_join([GOOD_PHRASE[a] for a in good]), ('을', '를'))} 좋게 평가했지만, "
                   f"{_join([BAD_PHRASE[a] for a in bad])} 때문에 아쉬워하는 의견도 있었어요.")
    elif good:
        out.append(f"특히 {_josa(_join([GOOD_PHRASE[a] for a in good]), ('을', '를'))} 좋게 평가했고, 눈에 띄는 불만은 적었어요.")
    elif bad:
        out.append(f"특히 {_join([BAD_PHRASE[a] for a in bad])}에 대한 불만이 많았어요.")

    # 3) 피부 타입별 차이
    liked = [s for s, r in reviews["by_skin"].items() if r["긍정"] > r["부정"] + r["혼합"]]
    disliked = [s for s, r in reviews["by_skin"].items() if r["부정"] + r["혼합"] > r["긍정"]]
    if liked and disliked:
        out.append(f"피부 타입별로 보면 {_josa(', '.join(liked), ('은', '는'))} 만족한 반면, "
                   f"{_josa(', '.join(disliked), ('은', '는'))} 아쉽다는 반응이 많아 **피부 타입에 따라 차이가 커요.**")
    elif liked:
        out.append(f"특히 {', '.join(liked)} 피부 사용자들의 만족도가 높았어요.")
    elif disliked:
        out.append(f"특히 {', '.join(disliked)} 피부 사용자들의 불만이 많았어요.")

    # 4) 광고와 실제
    differ = [c["항목"] for c in claims if c["판정"] == "❌ 광고와 다름"]
    match = [c["항목"] for c in claims if c["판정"] == "✅ 광고와 일치"]
    if differ:
        out.append(f"광고에서 강조한 {_josa(_join([GOOD_PHRASE[a] for a in differ]), ('은', '는'))} **실제 리뷰와 달랐어요.**")
    elif match:
        out.append(f"광고에서 말한 {_josa(_join([GOOD_PHRASE[a] for a in match]), ('은', '는'))} 실제 리뷰에서도 확인됐어요.")
    if reviews["sponsored"]:
        out.append(f"(협찬·체험단 리뷰 {reviews['sponsored']}개는 빼고 판단했어요.)")

    # 5) 나에게는?
    if skin_type in liked:
        out.append(f"👉 **{skin_type}**인 나와 같은 피부의 반응이 좋아서, **나에게도 잘 맞을 가능성이 높아요.**")
    elif skin_type in disliked:
        out.append(f"👉 **{skin_type}**인 나와 같은 피부의 반응이 좋지 않아서, **구매 전에 샘플로 먼저 써보는 게 좋아요.**")
    elif fit >= 70:
        out.append(f"👉 나와 같은 피부의 리뷰는 부족하지만, 성분으로 보면 **{skin_type}**인 나에게 잘 맞는 편이에요.")
    else:
        out.append(f"👉 나와 같은 피부의 리뷰가 부족하고 성분 적합도도 높지 않아서, **신중하게 고르는 게 좋아요.**")
    return " ".join(out)
