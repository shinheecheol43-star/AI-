"""링크에서 정보가 부족할 때, 검색 API로 블로그·카페 후기와 전성분을 더 모은다.

- 카카오(다음) 검색 API (추천): 무료, 카드 등록 없음, 블로그·카페 각각 하루 30,000번.
  developers.kakao.com 에서 앱을 만들고 'REST API 키'를 Streamlit Secrets의 KAKAO_REST_API_KEY 에 넣으면 켜져요.
- 네이버 검색 API (선택): 2026년부터 NAVER API HUB(네이버 클라우드)로 옮겨졌어요.
  NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 에 API HUB에서 받은 키를 넣으면 함께 써요.
- 검색 결과의 '요약 글(본문 일부)'만 써요. 블로그 본문을 통째로 긁어오지 않아요.
"""

import html
import os
import re
from concurrent.futures import ThreadPoolExecutor

import requests

NAVER_HUB = "https://naverapihub.apigw.ntruss.com/search/v1/{kind}"
NAVER_OLD = "https://openapi.naver.com/v1/search/{kind}.json"   # 예전 개발자센터 키 (2027년 6월까지)
KAKAO = "https://dapi.kakao.com/v2/search/{kind}"
SPONSOR = re.compile(r"협찬|체험단|제공받|원고료|서포터즈|무상으로|광고|소정의|대가를|지원받|홍보")
STOP_TITLE = {"앰플", "크림", "세럼", "토너", "로션", "에센스", "특가", "세트", "기획", "증정", "본품", "단품", "1개", "2개",
              "선크림", "마스크", "패드", "클렌저", "폼", "오일", "미스트"}


def _secret(name):
    try:
        import streamlit as st
        value = st.secrets.get(name)
        if value:
            return value
    except Exception:
        pass
    return os.environ.get(name)


def keys():
    """사용할 수 있는 검색 서비스와 키. 반환: {"kakao": 키, "naver": (id, secret)} (없는 것은 빠짐) 또는 {}"""
    out = {}
    if _secret("KAKAO_REST_API_KEY"):
        out["kakao"] = _secret("KAKAO_REST_API_KEY")
    if _secret("NAVER_CLIENT_ID") and _secret("NAVER_CLIENT_SECRET"):
        out["naver"] = (_secret("NAVER_CLIENT_ID"), _secret("NAVER_CLIENT_SECRET"))
    return out


def _clean(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()


def _get(url, params, headers):
    try:
        res = requests.get(url, params=params, headers=headers, timeout=8)
        return res.json() if res.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def _search(kind, query, page, credentials):
    """kind: blog | cafe | web. 결과를 같은 모양으로 맞춘다: [{title, description, link, postdate(YYYYMMDD), source}]"""
    out = []
    if "kakao" in credentials:
        k_kind = {"blog": "blog", "cafe": "cafe", "web": "web"}[kind]
        data = _get(KAKAO.format(kind=k_kind), {"query": query, "page": page, "size": 50, "sort": "accuracy"},
                    {"Authorization": f"KakaoAK {credentials['kakao']}"})
        for d in (data or {}).get("documents", []):
            out.append({"title": d.get("title", ""), "description": d.get("contents", ""), "link": d.get("url", ""),
                        "postdate": re.sub(r"\D", "", d.get("datetime", ""))[:8], "source": kind})
    if "naver" in credentials:
        n_kind = {"blog": "blog", "cafe": "cafearticle", "web": "webkr"}[kind]
        cid, csec = credentials["naver"]
        params = {"query": query, "display": 100, "start": (page - 1) * 100 + 1, "sort": "sim"}
        data = _get(NAVER_HUB.format(kind=n_kind), params, {"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": csec})
        if data is None:  # 예전 개발자센터 키일 수 있음
            data = _get(NAVER_OLD.format(kind=n_kind), params, {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec})
        for d in (data or {}).get("items", []):
            out.append({"title": d.get("title", ""), "description": d.get("description", ""), "link": d.get("link", ""),
                        "postdate": d.get("postdate", ""), "source": kind})
    return out


def product_words(title):
    """제품명에서 검색·관련성 판단에 쓸 핵심 단어 (용량, 수량, 흔한 제품 종류 단어는 뺌)."""
    t = re.sub(r"\[[^\]]*\]|\([^)]*\)|【[^】]*】|[^\w\s가-힣&+]", " ", title)
    words = [w for w in t.split() if len(w) >= 2 and not re.fullmatch(r"[\d+]+(ml|g|매|개|ea)?", w, re.I)]
    words = list(dict.fromkeys(words))
    return [w for w in words if w not in STOP_TITLE] or words


def _brand(brand):
    return re.sub(r"(공식|몰|스토어|쇼핑몰|official|성분제일주의)", "", brand or "", flags=re.I).strip()


def make_query(title, brand=""):
    words = product_words(title)[:4]
    brand = _brand(brand)
    if brand and brand not in words:
        words = [brand] + words
    return " ".join(words[:5])


def _relevant(text, words):
    """제품명 핵심 단어가 2개 이상(단어가 적으면 1개) 들어 있는 글만 이 제품 이야기로 본다."""
    need = 2 if len(words) >= 2 else 1
    compact = text.replace(" ", "")
    return sum(1 for w in words if w.replace(" ", "") in compact) >= need


def collect_reviews(title, brand="", limit=300):
    """블로그·카페에서 이 제품 후기를 모은다. 반환: (후기 목록, 사용한 검색어)
    후기 = {"source": "블로그"|"카페", "title", "text", "link", "date", "sponsored"}"""
    credentials = keys()
    if not credentials or not title:
        return [], ""
    base = make_query(title, brand)
    query = f"{base} 후기"
    words = product_words(title)[:4] + ([_brand(brand)] if _brand(brand) else [])
    pages = 3 if "naver" in credentials and "kakao" not in credentials else 4  # 카카오는 한 번에 50개, 네이버는 100개
    jobs = [(kind, q, page) for kind in ("blog", "cafe") for q in (query, f"{base} 사용 후기") for page in range(1, pages + 1)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda j: (j[0], _search(j[0], j[1], j[2], credentials)), jobs))
    out, seen = [], set()
    for kind, items in results:
        for it in items:
            link = it.get("link", "")
            if link in seen:
                continue
            seen.add(link)
            t, d = _clean(it.get("title")), _clean(it.get("description"))
            if not _relevant(t + " " + d, words):
                continue
            date = it.get("postdate", "")
            out.append({"source": "블로그" if kind == "blog" else "카페", "title": t, "text": d, "link": link,
                        "date": f"{date[:4]}-{date[4:6]}-{date[6:]}" if len(date) == 8 else "",
                        "sponsored": bool(SPONSOR.search(t + " " + d))})
    return out[:limit], query


def find_ingredients(title, brand=""):
    """'제품명 전성분'으로 검색해서 전성분 글(앞부분)을 찾는다. 검색 요약은 길이가 짧아 뒷부분이 잘릴 수 있다."""
    credentials = keys()
    if not credentials or not title:
        return "", ""
    words = product_words(title)[:4] + ([_brand(brand)] if _brand(brand) else [])
    best, src = "", ""
    for kind in ("blog", "web", "cafe"):
        for it in _search(kind, f"{make_query(title, brand)} 전성분", 1, credentials):
            d = _clean(it.get("description"))
            if "정제수" not in d or not _relevant(_clean(it.get("title")) + " " + d, words):
                continue
            part = d[d.find("정제수"):].split("...")[0]
            if part.count(",") > best.count(","):
                best, src = part.rstrip(", "), it.get("link", "")
    return (best, src) if best.count(",") >= 4 else ("", "")
