"""리뷰 글 전체에서 '많은 사람이 반복해서 쓴 표현'과 '비슷한 문장 묶음'을 찾는 모듈.

미리 정한 단어 사전에 없는 표현도 찾아낼 수 있도록, 리뷰에 실제로 나온 단어를 세어서 판단합니다.
"""

import re

from analyzer import NEGATIVE, POSITIVE, SPONSORED, split_reviews

# 단어 끝에 붙는 조사·어미를 떼서 '촉촉하고', '촉촉해요'를 같은 '촉촉'으로 본다.
ENDINGS = sorted([
    "했습니다", "습니다", "합니다", "입니다", "했습니", "습니", "입니", "됩니다", "겠습니다", "더라구요", "더라고요",
    "했어요", "했는데", "하네요", "해서", "해요", "하고", "하게", "하는", "한데", "합니다", "했다", "하다", "해",
    "인데", "이에요", "예요", "네요", "어요", "아요", "에요", "이고", "이라", "이랑", "에서", "으로", "까지",
    "부터", "처럼", "보다", "니까", "는데", "지만", "고", "게", "은", "는", "이", "가", "을", "를", "도", "에",
    "로", "요", "서", "지", "다", "임", "음",
], key=len, reverse=True)

STOPWORDS = {
    "진짜", "정말", "너무", "완전", "그냥", "제품", "사용", "느낌", "생각", "이거", "이건", "저는", "제가", "그리고",
    "근데", "그래서", "같아", "같아요", "있어", "없어", "있는", "하나", "조금", "약간", "많이", "계속", "처음", "이번",
    "사서", "샀어", "구매", "써보", "써봤", "쓰고", "쓰는", "바르", "발라", "바르고", "때문", "정도", "우선", "솔직히",
    "리뷰", "후기", "한번", "아직", "해서", "하고", "있고", "없고", "피부", "얼굴",
    # 좋다/별로 같은 감정 단어는 '무엇이' 좋은지가 아니라서 뺀다 (분위기 색으로만 표시)
    "항상", "매번", "계속", "자주", "재주문", "사용중", "사용하", "감사", "고맙", "제품도", "아주", "너무너무",
    "좋아", "좋고", "좋은", "좋다", "좋네", "좋습니", "별로", "추천", "만족", "재구매", "최고", "괜찮", "아쉬", "아쉽",
}


# '쓰는데', '사용중', '재구매했' 처럼 '썼다/샀다'는 뜻이라 내용이 없는 단어들
STOP_PREFIX = ("쓰", "써", "사용", "바르", "발라", "구매", "재구매", "주문", "재주문", "여전", "열심", "있습", "있어", "꾸준",
               "다년", "몇년", "매년", "매달", "주로", "모르", "좋아", "기대", "바라", "바래", "감사", "구매", "구입")


def stem(word):
    for end in ENDINGS:
        if word.endswith(end) and len(word) - len(end) >= 2:
            return word[: -len(end)]
    return word


def _keys(text):
    """단어의 앞 두 글자를 열쇠로 써서 '흡수', '흡수돼서', '흡수가'를 하나로 묶는다."""
    out = {}
    for w in re.findall(r"[가-힣A-Za-z]{2,}", text):
        st = stem(w)
        if len(st) < 2 or st in STOPWORDS or w in STOPWORDS or st.startswith(STOP_PREFIX):
            continue
        out.setdefault(st[:2], st)
    return out


def _sentences(review):
    parts = re.split(r"(?<=[.!?~])\s+|\n|(?<=요)\s+|(?<=다)\s+", review)
    return [p.strip(" .!?~") for p in parts if len(p.strip()) >= 6]


def _tone(text):
    """좋다/별로 같은 말과 '트러블 덜남' 같은 항목별 평가를 함께 보고 분위기를 정한다."""
    import analyzer as az
    score = 0
    for c in az._clauses(text):
        score += az._polarity(c)
        score += sum(az._aspect_hit(c, p, n, t) for t, p, n in az.ASPECTS.values())
    return (score > 0) - (score < 0)


def topics(reviews, top=8):
    """여러 리뷰에서 반복해서 나온 이야기.
    반환: [{"word": 대표 단어, "count": 언급한 리뷰 수, "tone": 분위기 합, "quote": 대표 문장, "others": 다른 문장들}]
    """
    mentions = {}  # 열쇠 -> {"forms": {형태: 횟수}, "sentences": [(리뷰 번호, 문장)]}
    for i, r in enumerate(reviews):
        for sent in _sentences(r) or [r]:
            for key, form in _keys(sent).items():
                m = mentions.setdefault(key, {"forms": {}, "sentences": []})
                m["forms"][form] = m["forms"].get(form, 0) + 1
                m["sentences"].append((i, sent))

    min_count = 2 if len(reviews) < 30 else max(2, len(reviews) // 15)
    result, used = [], set()
    ranked = sorted(mentions.items(), key=lambda kv: -len({i for i, _ in kv[1]["sentences"]}))
    for key, m in ranked:
        review_ids = {i for i, _ in m["sentences"]}
        if len(review_ids) < min_count:
            break
        sents = list(dict.fromkeys(s for _, s in m["sentences"]))
        if set(sents) <= used:  # 이미 다른 이야기에서 다 보여준 문장이면 건너뜀
            continue
        used.update(sents)
        word = min(m["forms"], key=lambda f: (-m["forms"][f], len(f)))
        tone = sum(_tone(reviews[i]) for i in review_ids)
        sign = (tone > 0) - (tone < 0)
        same = ([x for x in sents if sign and _tone(x) == sign]          # 다수 의견과 같은 쪽의 '의견 있는' 문장
                or [x for x in sents if _tone(x) * tone >= 0] or sents)
        quote = min(same, key=lambda x: abs(len(x) - 22))
        result.append({"word": word, "count": len(review_ids), "tone": tone,
                       "quote": quote, "others": [x for x in sents if x != quote][:3]})
        if len(result) >= top:
            break
    return result


def mine(text):
    reviews = [r for r in split_reviews(text) if not any(s in r for s in SPONSORED)]
    return {"topics": topics(reviews), "count": len(reviews)}
