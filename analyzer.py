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
    "다이프로필렌글라이콜": {"alias": ["다이프로필렌글라이콜", "dipropylene glycol"], "role": "보습·용매", "good": [], "caution": []},
    "글리세레스-26": {"alias": ["글리세레스-26", "glycereth-26"], "role": "보습·유화", "good": [], "caution": []},
    "세테아릴알코올": {"alias": ["세테아릴알코올", "세틸알코올", "cetearyl", "cetyl alcohol"], "role": "지방 알코올(보습·유화)", "good": ["건성"], "caution": []},
    "에칠헥실글리세린": {"alias": ["에칠헥실글리세린", "ethylhexylglycerin"], "role": "보습·보존 보조", "good": [], "caution": []},
    "카프릴릴글라이콜": {"alias": ["카프릴릴글라이콜", "caprylyl glycol"], "role": "보습·보존 보조", "good": [], "caution": []},
    "소듐시트레이트": {"alias": ["소듐시트레이트", "시트릭애씨드", "citric"], "role": "pH 조절", "good": [], "caution": []},
    "에칠헥실메톡시신나메이트": {"alias": ["에칠헥실메톡시신나메이트"], "role": "유기자차 성분",
                      "good": [], "caution": ["민감성"]},
}

SKIN_TYPES = ["건성", "지성", "복합성", "중성", "민감성"]
CONCERNS = ["여드름/트러블", "건조/보습", "미백/잡티", "주름/탄력", "모공", "진정/홍조"]
AVOID_OPTIONS = ["향료", "알코올", "파라벤", "에센셜오일"]


def _tokens(text):
    """전성분 글을 성분 이름 목록으로 (적힌 순서 그대로). '1,2-헥산다이올'처럼 이름 속 쉼표는 지킨다."""
    text = re.sub(r"(\d),(\d)", r"\1§\2", text)
    out = []
    for t in re.split(r"[,\n/·]", text):
        t = re.sub(r"\(.*?\)|[\[\]*]", "", t.replace("§", ",")).strip(" .")
        if 2 <= len(t) <= 40:
            out.append(t)
    return list(dict.fromkeys(out))


def _match(token):
    low = token.lower()
    for name, info in INGREDIENTS.items():
        if any(low.startswith(a.lower()) for a in info["alias"]):
            return name, info
    return None, None


def ingredient_report(text, profile):
    """전성분을 적힌 순서대로 하나씩 설명하고, 요약 정보를 만든다."""
    from ingredients_info import ALLERGENS, DESC, FUNCTIONAL, PRESERVATIVES, guess
    mine = {profile["skin_type"], *profile["concerns"], *profile["avoid"]}
    rows = []
    for idx, token in enumerate(_tokens(text), start=1):
        name, info = _match(token)
        if info:
            good = [g for g in info["good"] if g in mine]
            bad = [c for c in info["caution"] if c in mine]
            verdict = "⚠️ 주의" if bad else "✅ 잘 맞음" if good else "➖ 보통"
            category, desc, guessed = info["role"], DESC.get(name, ""), False
            reason = ", ".join(bad or good)
        else:
            category, desc = guess(token)
            verdict, reason, guessed = "❔ 사전에 없음", "", True
            if not category:
                category, desc = "기타", "아직 정보가 없는 성분이에요."
        rows.append({
            "순서": idx, "성분": token, "사전 이름": name or token, "분류": category, "설명": desc,
            "나에게": verdict, "이유": reason, "추정": guessed,
            "기능성": FUNCTIONAL.get(name or "", ""),
            "알레르기": any(token.startswith(a) for a in ALLERGENS),
            "방부제": any(token.startswith(p) for p in PRESERVATIVES) or category == "방부제",
            "주요": idx <= 5,
        })
    summary = {
        "total": len(rows),
        "main": [r["성분"] for r in rows if r["주요"]],
        "functional": [(r["성분"], r["기능성"]) for r in rows if r["기능성"]],
        "allergens": [r["성분"] for r in rows if r["알레르기"]],
        "fragrance": [r["성분"] for r in rows if r["사전 이름"] == "향료" or r["분류"] == "향료"],
        "preservatives": [r["성분"] for r in rows if r["방부제"]],
        "good": [r["성분"] for r in rows if r["나에게"] == "✅ 잘 맞음"],
        "caution": [(r["성분"], r["이유"]) for r in rows if r["나에게"] == "⚠️ 주의"],
        "guessed": sum(r["추정"] for r in rows),
    }
    return rows, summary


def analyze_ingredients(text, profile):
    """점수 계산과 표에 쓰는 간단한 형태 (주의 → 잘 맞음 → 보통 → 사전에 없음 순)."""
    rows, _ = ingredient_report(text, profile)
    order = {"⚠️ 주의": 0, "✅ 잘 맞음": 1, "➖ 보통": 2, "❔ 사전에 없음": 3}
    out = [{"성분": r["사전 이름"], "역할": r["분류"], "나에게": r["나에게"], "이유": r["이유"] or "-"} for r in rows]
    out = list({r["성분"]: r for r in out}.values())
    out.sort(key=lambda r: order[r["나에게"]])
    return out


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
           ["건조해", "건조하고", "건조함이", "건조했", "당김", "당겨", "땡겨", "보습이 부족", "보습력이 약", "속건조가"]),
    "진정/순함": (["진정", "순한", "자극 없", "민감"], ["진정", "순하", "순해", "자극 없", "자극이 없", "편안", "붉은기가 가라"],
              ["따가", "따끔", "자극", "붉어", "가려", "화끈", "홍조 생", "홍조가 생"]),
    "산뜻함": (["산뜻", "가벼운", "끈적임 없", "보송"], ["산뜻", "가볍", "보송", "뽀송", "끈적임 없", "끈적이지 않", "안 끈적", "번들거림 잡", "유분 잡", "기름 잡"],
            ["끈적", "무거", "번들거림", "번들거려", "번들거리고", "번들번들", "기름져", "기름이 돌", "기름지", "답답"]),
    "흡수": (["흡수"], ["흡수 빠", "흡수가 빠", "흡수가 잘", "스며"], ["흡수가 안", "흡수가 느", "겉돌", "밀려", "밀림"]),
    "트러블": (["트러블", "여드름", "피지", "모공"], ["트러블 없", "트러블이 없", "트러블이 줄", "트러블 안", "좁쌀이 들어", "여드름이 줄", "진정됐", "진정되", "진정이 잘", "가라앉", "사라졌", "들어갔", "들어가", "덜남", "덜 나", "트러블 덜", "트러블이 덜", "줄어", "없어졌", "없어지", "안 나", "안나",
             "줄었", "줄고", "안올라", "안 올라", "잡혀", "잡아", "잡히", "잡혔", "좋아졌", "깨끗해", "가라 앉", "옅어", "안난", "안 난",
             "해방", "피지가 빠", "모공이 작아", "모공도 작아", "모공이 조여", "모공 조여", "연해", "완화", "안날", "안 날"],
            ["트러블이 나", "트러블이 생", "트러블 생", "트러블이 올라", "트러블 올라", "올라왔", "올라와요", "뾰루지가 나",
             "뾰루지가 올라", "좁쌀이 올라", "좁쌀이 생", "여드름이 났", "여드름 났", "여드름이 더", "더 심해", "더심해", "뒤집어", "뒤집혔"]),
    "미백/톤업": (["미백", "톤업", "브라이트닝", "잡티", "광채"], ["톤업", "밝아", "환해", "화사", "잡티가 옅"],
              ["톤업이 안", "어두워", "칙칙해"]),
    "효과": (["효과", "개선", "인체 시험", "임상"], ["효과가 좋", "효과 좋", "효과가 눈에", "효과 있", "효과가 있", "효과를 봤", "효과 봤", "효과가 바로", "효과보", "효과 보고", "효자템", "확실히", "확연히", "효과는 정말", "효과는 있", "효과는 좀 있", "효과가 보", "효과가 다음날", "나아지", "효과가 나오", "효과가 있", "효과 있"],
           ["효과 없", "효과없", "효과가 없", "효과가 전혀", "효과는 없", "효과를 못", "효과는 잘", "모르겠", "모르겟", "그대로",
            "속은", "속았", "변화 없", "변화가 없", "별다른 효과", "원점", "악화", "1도 없", "낚였", "낚임"]),
    "백탁": (["백탁"], ["백탁 없", "백탁이 없"], ["백탁", "회색", "하얗게 떠"]),
    "지속력": (["하루종일", "지속", "오래", "24시간"], ["하루종일 촉촉", "유지력 좋", "지속력 좋", "오래 유지"], ["오후에", "무너져", "무너지", "무너짐", "날아가", "금방 건조", "금방 무너"]),
    "향": (["향"], ["향 좋", "향이 좋", "은은", "향이 없어", "무향"], ["향이 강", "향이 너무", "냄새", "향 별로", "향이 별로"]),
    "용량": (["대용량", "넉넉한 용량"], ["용량이 넉넉", "양이 많", "오래 써"],
           ["용량이 작", "용량이 적", "용량적", "양이 적", "양이 작", "양이적", "금방 써", "빨리 써", "금방쓸", "빨리 쓰", "빨리쓰"]),
    "배송": (["빠른 배송", "당일 배송", "무료배송"], ["배송이 빠", "배송 빠", "빠른 배송", "빠른배송", "배송도 빠", "빨리 왔", "바로 왔", "바로왔", "꼼꼼"],
           ["배송이 느", "배송 느", "늦게 왔", "늦게 도착", "오배송", "잘못 왔", "파손", "받은게 없", "받은 게 없", "누락"]),
    "가격": (["가성비", "합리적", "착한 가격"], ["가성비 좋", "가성비 최고", "가성비가 좋", "저렴", "싸게", "가격도 착"],
           ["비싸", "가격이 부담", "가성비 별로", "가격 대비"]),
}
POSITIVE = ["좋", "추천", "재구매", "만족", "최고", "인생템", "괜찮", "강추", "대박", "짱", "잘 맞", "또 살",
            "효자템", "정착", "매끈", "부드러워", "부드럽", "좋아졌", "줄었", "효과보", "효과 보", "확실히", "확연히", "뛰어",
            "나쁘지 않", "나쁘진 않", "굿", "조아", "잘맞", "마음에 들", "맘에 들", "마음에 든", "맘에 든", "부들부들", "완화", "개선되",
            "효과가 나오", "효과가 있", "효과 있", "잘돼", "잘되", "잘 돼", "잘 되", "이것만 쓸", "이것만쓸", "찐입니", "찐이에", "찐템", "잘 먹", "뽀송", "쫀쫀", "도움되", "도움이 되", "도움이 돼", "도움 됐", "해방", "나아지", "나아졌"]
NEGATIVE = ["별로", "비추", "실망", "안 맞", "안맞", "환불", "최악", "다시는", "아쉽", "아쉬", "안 좋", "좋지 않",
            "좋진 않", "좋지는 않", "그닥", "글쎄", "버렸", "안 살", "속은", "속았", "효과 없", "효과없", "효과가 없", "효과를 못",
            "효과가 전혀", "효과는 없", "돈 아까", "돈아까", "좋아지지 않", "심해졌", "원점", "악화", "1도 없", "낚였", "낚임", "의문"]
# 아직 써본 지 얼마 안 돼서 판단을 미룬 리뷰 ("아직 잘 모르겠어요, 더 써볼게요") → 불만이 아니라 '판단 보류'
PENDING = ["아직", "안 써봤", "안써봤", "안 써본", "써보지", "안써뵜", "더 써봐", "더써봐", "써봐야", "써보고", "써볼", "사용해볼", "사용해 볼", "사용해보고", "발라볼", "발라보", "지켜보",
           "며칠", "이틀", "사흘", "한번밖에", "몇번 사용", "얼마 안", "기간이 짧", "기한이 짧", "기대", "바래", "바랍", "업데이트",
           "다시 리뷰", "다시 후기", "후기 남기", "리뷰 남기"]
UNSURE = ["모르겠", "모르겟", "잘모르", "잘 모르", "판단하기", "어렵지만"]
# 바람·기대를 말하는 표현 ("효과가 있기를", "봤으면 좋겠어요") → 실제 경험이 아님
HOPE_AFTER = ["좋겠", "바라", "바래", "바랍", "기를", "길 바", "길바", "으면", "면 좋", "기대"]
SPONSORED = ["제공받", "협찬", "체험단", "서포터즈", "무상으로", "원고료"]
# 리뷰 속 피부 타입 표현 → 앱의 피부 타입
SKIN_WORDS = {"건성": ["건성", "건조한 피부", "악건성"], "지성": ["지성", "기름진 피부", "기름 좔좔", "개기름", "피지가 많", "번들거리는 피부"],
              "복합성": ["복합성", "수부지"], "중성": ["중성"], "민감성": ["민감성", "민감한 피부", "예민한 피부", "피부 예민", "피부가 예민", "예민한데", "예민해서"]}
# 사이트에서 복사할 때 섞여 들어오는 잡음 줄
NOISE = ["도움이 돼요", "도움돼요", "신고", "더보기", "답글", "판매자", "구매확정", "옵션:", "작성일"]  # 짧은 줄일 때만 잡음으로 봄
CLAUSE_SPLIT = re.compile(r"은데|는데|지만|근데|그런데|하지만|그러나|다만|[.!?~,\n]")


def _clauses(review):
    return [c.strip() for c in CLAUSE_SPLIT.split(review) if c.strip()]


CONDITIONAL = re.compile(r"(으면|면)\s*(환불|재구매는|안\s*살|안\s*사)|없으면|안\s*맞으면|안맞으면")


def _polarity(text):
    """문장 조각의 긍정(1)/부정(-1)/중립(0). '안 좋', '좋지 않'처럼 부정이 붙으면 부정."""
    text = re.sub(r"(했|었|았)?(으면|음)\s*좋겠\S*|좋겠\S*", " ", text)  # "진정했음 좋겠네" → 바람이라 평가 아님
    for p in POSITIVE:  # "하나도 좋아지는거 없네요", "산뜻하지 않아요"
        i = text.find(p)
        if i >= 0 and NEGATED_TAIL.match(text[i + len(p): i + len(p) + 8]):
            return -1
    if any(n in text for n in NEGATIVE):
        if CONDITIONAL.search(text) or re.search(r"환불\s*안", text) or any(b in text for b in PAST_BEFORE):
            return 0  # "안 맞으면 환불할 거예요", "결론적으로 환불 안 했어요"
        return -1
    if any(p in text for p in POSITIVE):
        return 1
    compact = text.replace(" ", "")
    if (any(n.replace(" ", "") in compact for n in NEGATIVE) and not CONDITIONAL.search(compact)
            and not any(b in compact for b in PAST_BEFORE)):
        return -1
    if any(p.replace(" ", "") in compact for p in POSITIVE):
        return 1
    return 0


# 문제를 뜻하는 말 뒤에 이런 말이 오면 '문제가 해결됐다' = 좋은 평가로 본다
# 예: "따가움 전혀 없어요", "번들거림 잡아줘요", "여드름이 많이 줄었어요"
RESOLVED_AFTER = ["없", "않", "안 ", "안나", "안올라", "안 올라", "줄", "잡아", "잡혀", "잡히", "잡혔", "가라앉",
                  "덜", "사라", "들어가", "들어갔", "진정", "개선", "해결", "좋아졌", "괜찮", "기 전", "예방", "관리용", "나아"]
OTHER_PRODUCT = ["다른 제품", "다른 화장품", "수많은", "이것저것", "여러 제품", "제품써 봤", "제품 써 봤", "제품들 써", "제품 중", "제품이 많",
                 "안 써본", "다 써봤", "온갖"]
RESOLVED_BEFORE = ["전혀", "하나도", "없이", "안쓰면", "안 쓰면", "끊으면", "안 바르면", "안바르면", "안발라보면", "안 발라보면"]
# 예전 피부 상태를 설명하는 말 ("여드름의 노예였는데", "트러블이 심해서 샀는데") → 제품 평가가 아니므로 무시
PAST_BEFORE = ["처음엔", "처음에는", "처음에"]
PAST_AFTER = ["였는데", "었는데", "였던", "었던", "였어서", "이라 고민", "라서 구매", "때문에 구매", "때문에 주문", "해서 샀", "해서 구매",
              "구매", "구입", "샀어", "사봤", "주문", "때메", "때문에"]


def _resolved(text, start, word):
    after = text[start + len(word): start + len(word) + 14]
    before = text[max(0, start - 12): start]
    return any(r in after for r in RESOLVED_AFTER) or any(r in before for r in RESOLVED_BEFORE)


def _hoped(text, start, word):
    return any(h in text[start + len(word): start + len(word) + 8] for h in HOPE_AFTER)


NEGATED_TAIL = re.compile(r"^\S{0,4}\s?(않|없)|^\S{0,2}\s?안\s")
# 원래 '없다/못하다'는 뜻을 담은 불만 ("효과가 없다", "효과를 못 봤다") → '하나도', '전혀'가 붙어도 해결이 아님
NO_RESOLVE = ("효과", "변화", "그대로", "원점", "모르")


def _aspect_hit_once(clause, pos, neg, topic):
    for p in pos:
        i = clause.find(p)
        if i < 0 or _hoped(clause, i, p):
            continue
        tail = clause[i + len(p): i + len(p) + 6]
        if NEGATED_TAIL.match(tail) and not p.endswith(("없", "않")):
            return -1  # "가격도 착하지않음", "좋진 않아요"
        return 1
    stripped = clause
    for p in pos:
        stripped = stripped.replace(p, "")
    found = [(m.start(), n) for n in neg for m in re.finditer(re.escape(n), stripped)]
    if found:
        marks = []
        for i, n in found:
            after = stripped[i + len(n): i + len(n) + 30]
            if _hoped(stripped, i, n):
                marks.append(0)   # "트러블에 효과가 있기를" 같은 바람
            elif not n.startswith(NO_RESOLVE) and _resolved(stripped, i, n):
                marks.append(1)   # 문제가 없거나 해결됐다는 말
            elif (any(p in after for p in PAST_AFTER) or after.strip().endswith(("였", "었")) or "몇번째" in stripped
                  or "몇 번째" in stripped or any(b in stripped[max(0, i - 12): i] for b in PAST_BEFORE)):
                marks.append(0)   # 예전 상태 설명
            else:
                marks.append(-1)
        if -1 in marks:
            return -1
        if 1 in marks:
            return 1
    if topic and any(t in clause for t in topic):
        return _polarity(clause)  # "보습은 좋아요"처럼 항목 이름 + 좋다/별로
    return 0


def _aspect_hit(clause, pos, neg, topic=()):
    """문장 조각 하나에서 항목의 긍정(1)/부정(-1)/언급 없음(0). 띄어쓰기가 달라도 찾는다."""
    if any(u in clause for u in UNSURE):
        return 0  # "트러블이 없어지는 건 아직 모르겠어요" → 판단 보류 (analyze_reviews에서 따로 셈)
    hit = _aspect_hit_once(clause, pos, neg, topic)
    if hit:
        return hit
    squash = lambda ws: [w.replace(" ", "") for w in ws]
    return _aspect_hit_once(clause.replace(" ", ""), squash(pos), squash(neg), squash(topic))


def _skin_types(review):
    return [s for s, words in SKIN_WORDS.items() if any(w in review for w in words)]


def _quote(review, clause, n=70):
    """리뷰가 길면, 그 의견이 들어 있는 문장 부분만 잘라서 보여준다."""
    if len(review) <= n:
        return review
    i = review.find(clause)
    if i < 0:
        return _short(review, n)
    start = max(review.rfind(ch, 0, i) for ch in ".!?~\n")
    start = 0 if start < 0 else start + 1
    if i - start > n // 2:
        start = max(0, i - 15)
    piece = review[start:start + n].strip(" .~")
    return ("…" if start > 0 else "") + piece + ("…" if start + n < len(review) else "")


def _short(text, n=60):
    return text if len(text) <= n else text[:n] + "…"


def split_reviews(text):
    out, seen = [], set()
    for r in re.split(r"\n+", text):
        r = re.sub(r"\s+", " ", r).strip()
        if len(r) < 2 or re.fullmatch(r"[\d.\-/: ★☆점]+", r) or re.fullmatch(r"\S{1,3}\*{2,}\S*", r):
            continue
        if len(r) < 15 and any(w in r for w in NOISE):
            continue  # '도움이 돼요' 같은 버튼 글자 (긴 리뷰 속의 '도움이 돼요'는 지키기)
        if len(r) > 20:  # 긴 리뷰가 똑같이 두 번 나오면 복사 실수 → 한 번만. 짧은 '만족'은 사람마다 따로 셈
            if r in seen:
                continue
            seen.add(r)
        out.append(r)
    return out


def analyze_reviews(text, skin_type):
    """협찬 리뷰는 따로 세고, 나머지 리뷰만으로 통계를 낸다."""
    all_reviews = split_reviews(text)
    sponsored = [r for r in all_reviews if any(s in r for s in SPONSORED)]
    reviews = [r for r in all_reviews if r not in sponsored]
    result = {"count": len(reviews), "positive": 0, "negative": 0, "mixed": 0, "pending": 0,
              "pending_quotes": [],
              "sponsored": len(sponsored), "same_skin": 0, "same_skin_positive": 0,
              "aspects": {a: {"좋음": 0, "아쉬움": 0} for a in ASPECTS},
              "quotes": {a: {"좋음": [], "아쉬움": []} for a in ASPECTS},
              "by_skin": {}, "skin_type": skin_type}
    for r in reviews:
        hits, all_hits = {}, []
        other = False  # "다른 제품 써봤지만 효과를 못봤어요" → 이 제품 이야기가 아님
        for clause in _clauses(r):
            if any(o in clause for o in OTHER_PRODUCT):
                other = True
            for a, (topic, p_words, n_words) in ASPECTS.items():
                hit = _aspect_hit(clause, p_words, n_words, topic)
                if hit == -1 and other:
                    continue
                if hit:
                    hits[a] = (hit, clause)  # 같은 리뷰에서 뒤에 나온 의견을 우선
                    all_hits.append(hit)
        unsure = next((c for c in _clauses(r) if any(u in c for u in UNSURE)), None)
        pending = bool(unsure) and any(p in r for p in PENDING)
        if unsure and not pending and "효과" not in hits and not re.search(r"몇\s*번째", r):
            hits["효과"] = (-1, unsure)  # 충분히 써봤는데도 "효과는 잘 모르겠어요" → 효과 아쉬움
        for a, (hit, clause) in hits.items():
            key = "좋음" if hit == 1 else "아쉬움"
            result["aspects"][a][key] += 1
            result["quotes"][a][key].append(_quote(r, clause))

        # 리뷰 전체의 느낌: 조각별 긍정/부정 + 항목별 평가를 합쳐서 판단
        pols, seen_other = [], False
        for c in _clauses(r):
            seen_other = seen_other or any(o in c for o in OTHER_PRODUCT)
            pol = _polarity(c)
            if not (pol == -1 and seen_other):
                pols.append(pol)
        pols += all_hits + [h for h, _ in hits.values()]
        pos, neg = pols.count(1), pols.count(-1)
        if pos and neg:
            label = "mixed"
        elif pos:
            label = "positive"
        elif neg:
            label = "negative"
        else:
            label = None
        if pending and label in (None, "negative"):
            label = "pending"  # 아직 써본 지 얼마 안 돼 판단을 미룬 리뷰
            result["pending_quotes"].append(_short(r, 70))
        if label:
            result[label] += 1

        for s in _skin_types(r):
            row = result["by_skin"].setdefault(s, {"리뷰 수": 0, "긍정": 0, "부정": 0, "혼합": 0})
            row["리뷰 수"] += 1
            if label in ("positive", "negative", "mixed"):
                row[{"positive": "긍정", "negative": "부정", "mixed": "혼합"}[label]] += 1
        if skin_type in _skin_types(r):
            result["same_skin"] += 1
            result["same_skin_positive"] += label == "positive"
    return result


MIN_SKIN = 5  # 피부 타입별로 판단하려면 그 피부 리뷰가 최소 이만큼은 있어야 함


def skin_verdict(row, total=100):
    """피부 타입별 반응: 'liked' / 'disliked' / 'mixed' / None(리뷰가 적어 판단 어려움).
    리뷰를 많이 모았으면 그 피부 리뷰가 5개 이상일 때만, 직접 붙여넣은 소수 리뷰면 2개 이상일 때 판단."""
    n = row["긍정"] + row["부정"] + row["혼합"]
    if n < (MIN_SKIN if total >= 30 else 2):
        return None
    rate = (row["긍정"] + row["혼합"] * 0.5) / n
    return "liked" if rate >= 0.7 else "disliked" if rate < 0.5 else "mixed"


def satisfaction(reviews):
    """의견을 밝힌 리뷰(긍정·부정·혼합) 중 만족 비율. 혼합은 절반으로 셈. 반환: (비율 %, 의견 리뷰 수)"""
    n = reviews["positive"] + reviews["negative"] + reviews["mixed"]
    if not n:
        return None, 0
    return round((reviews["positive"] + reviews["mixed"] * 0.5) / n * 100), n


def margin_of_error(pct, n, total=0):
    """표본 n개로 본 비율의 95% 오차 범위(±%p). 전체 개수를 알면 보정한다."""
    if not n or pct is None:
        return None
    import math
    p = pct / 100
    moe = 1.96 * math.sqrt(max(p * (1 - p), 0.0025) / n)
    if total and total > n:
        moe *= math.sqrt((total - n) / (total - 1))
    return max(1, round(moe * 100))


def trend_by_year(review_text, dates, skin_type):
    """리뷰를 쓴 해마다 만족 비율이 어떻게 바뀌었는지. 반환: [(연도, 만족 %, 의견 리뷰 수)]"""
    lines = [l for l in review_text.split("\n")]
    groups = {}
    for line, date in zip(lines, dates):
        if date[:4].isdigit():
            groups.setdefault(date[:4], []).append(line)
    out = []
    for year in sorted(groups):
        sat, n = satisfaction(analyze_reviews("\n".join(groups[year]), skin_type))
        if n >= 5:
            out.append((year, sat, n))
    return out


def summarize_reviews(reviews, skin_type):
    """통계를 사람이 읽기 쉬운 요약 문장과 좋은 점/아쉬운 점 TOP 3로 만든다."""
    n = reviews["count"]
    if n == 0:
        return {"text": "분석할 리뷰가 없어요.", "good": [], "bad": []}
    aspects = {a: v for a, v in reviews["aspects"].items() if a != "배송"}  # TOP 3는 제품 이야기만
    good = sorted((a for a in aspects if aspects[a]["좋음"]), key=lambda a: -aspects[a]["좋음"])[:3]
    bad = sorted((a for a in aspects if aspects[a]["아쉬움"]), key=lambda a: -aspects[a]["아쉬움"])[:3]

    sat, opinion_n = satisfaction(reviews)
    pos_rate = sat or 0
    none_n = n - opinion_n - reviews["pending"]
    lines = [f"리뷰 {n}개 중 **긍정 {reviews['positive']}개, 부정 {reviews['negative']}개, "
             f"장단점이 섞인 리뷰 {reviews['mixed']}개**예요. "
             f"아직 써본 지 얼마 안 돼 **판단을 미룬 리뷰 {reviews['pending']}개**, "
             f"'잘 쓸게요'처럼 평가가 없는 리뷰 {none_n}개는 만족도 계산에서 뺐어요."]
    if reviews["sponsored"]:
        lines[0] += f" (협찬·체험단 리뷰 {reviews['sponsored']}개는 빼고 계산했어요)"
    if good:
        lines.append("좋다는 의견은 주로 **" + ", ".join(f"{a} {aspects[a]['좋음']}건" for a in good) + "**에 대한 거예요.")
    if bad:
        lines.append("아쉽다는 의견은 주로 **" + ", ".join(f"{a} {aspects[a]['아쉬움']}건" for a in bad) + "**에 대한 거예요.")

    by_skin = reviews["by_skin"]
    skin_notes = []
    for s, row in by_skin.items():
        v = skin_verdict(row, reviews["count"])
        if v == "liked":
            skin_notes.append(f"{s} 😊 대체로 만족")
        elif v == "disliked":
            skin_notes.append(f"{s} 😥 아쉬움이 많음")
        elif v is None:
            skin_notes.append(f"{s} (리뷰 {row['리뷰 수']}개라 판단 어려움)")
    if skin_notes:
        lines.append("피부 타입별 반응: " + ", ".join(skin_notes))
    if skin_type in by_skin:
        row = by_skin[skin_type]
        lines.append(f"나와 같은 **{skin_type}** 리뷰는 {row['리뷰 수']}개이고, 그중 긍정은 {row['긍정']}개예요."
                     + ("" if skin_verdict(row, n) else " (리뷰가 적어서 참고만 해 주세요)"))
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
    row = reviews["by_skin"].get(reviews.get("skin_type", ""), None)
    if row and skin_verdict(row, reviews["count"]):  # 같은 피부 리뷰가 충분할 때만 반영
        n = row["긍정"] + row["부정"] + row["혼합"]
        rate = (row["긍정"] + row["혼합"] * 0.5) / n
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
GOOD_PHRASE = {"용량": "넉넉한 용량", "배송": "빠른 배송", "효과": "눈에 보이는 효과", "보습": "보습력", "진정/순함": "순하고 진정되는 느낌", "산뜻함": "산뜻한 사용감", "흡수": "빠른 흡수",
               "트러블": "트러블이 적은 점", "미백/톤업": "톤업 효과", "백탁": "백탁이 없는 점", "지속력": "지속력",
               "향": "향", "가격": "가성비"}
BAD_PHRASE = {"용량": "적은 용량", "배송": "배송 문제", "효과": "효과를 못 느낀 점", "보습": "건조함", "진정/순함": "자극", "산뜻함": "끈적임", "흡수": "잘 흡수되지 않는 점",
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
    aspects = {a: v for a, v in reviews["aspects"].items() if a != "배송"}  # 총평은 제품 이야기만
    good = sorted((a for a in aspects if aspects[a]["좋음"]), key=lambda a: -aspects[a]["좋음"])[:2]
    bad = sorted((a for a in aspects if aspects[a]["아쉬움"]), key=lambda a: -aspects[a]["아쉬움"])[:2]
    pos, neg, mixed = reviews["positive"], reviews["negative"], reviews["mixed"]
    sat, opinion_n = satisfaction(reviews)
    out = []

    # 1) 전체 분위기
    if pos >= (neg + mixed) * 2:
        out.append("전체적으로 **만족한다는 평이 많은 제품**이에요.")
    elif neg > pos + mixed:
        out.append("전체적으로 **아쉽다는 평이 더 많은 제품**이에요.")
    else:
        out.append("**호불호가 갈리는 제품**이에요.")
    if sat is not None:
        out.append(f"평가를 남긴 리뷰 {opinion_n}개 중 **만족 비율은 {sat}%**예요.")
    if reviews.get("pending"):
        out.append(f"(아직 써본 지 얼마 안 돼 판단을 미룬 리뷰 {reviews['pending']}개는 따로 봤어요.)")

    # 2) 장점과 단점
    if good and bad:
        out.append(f"사용자들은 {_josa(_join([GOOD_PHRASE[a] for a in good]), ('을', '를'))} 좋게 평가했지만, "
                   f"{_join([BAD_PHRASE[a] for a in bad])} 때문에 아쉬워하는 의견도 있었어요.")
    elif good:
        out.append(f"특히 {_josa(_join([GOOD_PHRASE[a] for a in good]), ('을', '를'))} 좋게 평가했고, 눈에 띄는 불만은 적었어요.")
    elif bad:
        out.append(f"특히 {_join([BAD_PHRASE[a] for a in bad])}에 대한 불만이 많았어요.")

    # 3) 피부 타입별 차이
    liked = [s for s, r in reviews["by_skin"].items() if skin_verdict(r, reviews["count"]) == "liked"]
    disliked = [s for s, r in reviews["by_skin"].items() if skin_verdict(r, reviews["count"]) == "disliked"]
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
