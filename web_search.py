"""링크에서 정보가 부족할 때, 네이버 검색 API로 블로그·카페 후기와 전성분을 더 모은다.

- 네이버 검색 API는 무료예요 (하루 25,000번). developers.naver.com 에서 키를 받아
  Streamlit 'Secrets'에 NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 으로 넣으면 켜져요.
- 검색 결과의 '요약 글(본문 일부)'만 써요. 블로그 본문을 통째로 긁어오지 않아요.
"""

import html
import os
import re
from concurrent.futures import ThreadPoolExecutor

import requests

API = "https://openapi.naver.com/v1/search/{kind}.json"
SPONSOR = re.compile(r"협찬|체험단|제공받|원고료|서포터즈|무상으로|광고|소정의|대가를|지원받|홍보")
STOP_TITLE = {"앰플", "크림", "세럼", "토너", "로션", "에센스", "특가", "세트", "기획", "증정", "본품", "단품", "1개", "2개",
              "선크림", "마스크", "패드", "클렌저", "폼", "오일", "미스트"}


def keys():
    """Streamlit Secrets 또는 환경 변수에서 키를 읽는다. 없으면 None."""
    cid = csec = None
    try:
        import streamlit as st
        cid, csec = st.secrets.get("NAVER_CLIENT_ID"), st.secrets.get("NAVER_CLIENT_SECRET")
    except Exception:
        pass
    cid = cid or os.environ.get("NAVER_CLIENT_ID")
    csec = csec or os.environ.get("NAVER_CLIENT_SECRET")
    return (cid, csec) if cid and csec else None


def _clean(text):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text or ""))).strip()


def _search(kind, query, start, credentials):
    cid, csec = credentials
    try:
        res = requests.get(API.format(kind=kind), params={"query": query, "display": 100, "start": start, "sort": "sim"},
                           headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec}, timeout=8)
        if res.status_code != 200:
            return []
        return res.json().get("items", [])
    except (requests.RequestException, ValueError):
        return []


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
    jobs = [(kind, q, start) for kind in ("blog", "cafearticle") for q in (query, f"{base} 사용 후기")
            for start in range(1, min(limit, 300) + 1, 100)]
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
    for kind in ("blog", "webkr", "cafearticle"):
        for it in _search(kind, f"{make_query(title, brand)} 전성분", 1, credentials):
            d = _clean(it.get("description"))
            if "정제수" not in d or not _relevant(_clean(it.get("title")) + " " + d, words):
                continue
            part = d[d.find("정제수"):].split("...")[0]
            if part.count(",") > best.count(","):
                best, src = part.rstrip(", "), it.get("link", "")
    return (best, src) if best.count(",") >= 4 else ("", "")
