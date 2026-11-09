"""링크에서 정보가 부족할 때, 검색 API로 블로그·카페 후기와 전성분을 더 모은다.

- 카카오(다음) 검색 API (추천): 무료, 카드 등록 없음, 블로그·카페 각각 하루 30,000번.
  developers.kakao.com 에서 앱을 만들고 'REST API 키'를 Streamlit Secrets의 KAKAO_REST_API_KEY 에 넣으면 켜져요.
- 네이버 검색 API (선택): 2026년부터 NAVER API HUB(네이버 클라우드)로 옮겨졌어요.
  NAVER_CLIENT_ID, NAVER_CLIENT_SECRET 에 API HUB에서 받은 키를 넣으면 함께 써요.
- 후기는 검색 결과의 '요약 글(본문 일부)'만 써요. 전성분은 검색으로 찾은 페이지를 열어 성분 목록만 뽑고, 본문은 저장·표시하지 않아요.
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


def _page_url(link):
    """네이버 블로그는 본문이 안쪽 창(iframe)에 있어서 모바일 주소로 연다."""
    m = re.match(r"https?://blog\.naver\.com/([^/?#]+)/(\d+)", link)
    if m:
        return f"https://m.blog.naver.com/{m.group(1)}/{m.group(2)}"
    m = re.match(r"https?://blog\.naver\.com/PostView\.n(?:hn|aver)\?(.*)", link)
    if m:
        return f"https://m.blog.naver.com/PostView.naver?{m.group(1)}"
    return link


def _list_from_text(text):
    """글 전체에서 '전성분' 뒤(없으면 '정제수'부터)의 쉼표 목록만 잘라낸다. 문장이 나오면 거기서 멈춘다."""
    import ocr
    seg = ocr.extract_section(text)
    if not seg:
        return ""
    lines = [l for l in seg.split("\n") if l.strip()]
    if seg.count(",") < 5 and len(lines) >= 8:   # 성분을 한 줄에 하나씩 적은 글
        seg = ", ".join(lines)
    seg = re.sub(r"\s*\n\s*", " ", seg)
    items = []
    for part in re.split(r",(?!\s*\d+-)", seg):  # '1,2-헥산다이올'의 쉼표는 나누지 않음
        part = part.strip(" .·*")
        if not part:
            continue
        if len(part) > 45 or re.search(r"(니다|어요|해요|에요|네요|습니다|[.!?~]\s)", part):
            if len(items) >= 8:
                break
            items = []          # 아직 목록이 시작되기 전의 문장
            continue
        items.append(part)
    return ", ".join(items) if len(items) >= 8 else ""


def _ingredients_from_page(link, words, allow_ocr):
    """검색으로 찾은 페이지 하나에서 이 제품의 전성분만 뽑는다. 본문은 저장하지 않는다."""
    import fetcher
    url = _page_url(link)
    try:
        page = fetcher.fetch_html(url, timeout=8)
    except Exception:
        return "", link
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(page, "html.parser")
    head = (soup.title.get_text(" ", strip=True) if soup.title else "") + " " + soup.get_text(" ", strip=True)[:3000]
    if not _relevant(head, words):
        return "", link
    found = fetcher.parse(page)["ingredients"]
    if not found or found.count(",") < 8:
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        found = _list_from_text(soup.get_text("\n", strip=True)) or found
    if (not found or found.count(",") < 8) and allow_ocr:
        import ocr
        if ocr.available():
            found, _ = ocr.find_in_images(page, url, budget=25, max_images=30)
    return (found if found and found.count(",") >= 8 else ""), link


def _names(text):
    return {re.sub(r"\(.*?\)|\s", "", t) for t in re.split(r",(?!\s*\d+-)", text) if t.strip()}


def _same_list(a, b):
    x, y = _names(a), _names(b)
    return len(x & y) / max(1, min(len(x), len(y))) >= 0.7


def find_ingredients(title, brand=""):
    """'제품명 전성분'으로 검색하고, 찾은 페이지(다른 쇼핑몰·블로그 등)를 열어 전성분 목록만 뽑는다.
    여러 곳의 목록이 서로 같으면 그 목록을 믿는다.
    반환: (전성분, 출처 링크, {"pages": 목록을 찾은 곳 수, "agree": 같은 목록을 낸 곳 수, "partial": 검색 요약만 찾았는지})"""
    credentials = keys()
    if not credentials or not title:
        return "", "", {}
    words = product_words(title)[:4] + ([_brand(brand)] if _brand(brand) else [])
    query = f"{make_query(title, brand)} 전성분"
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda k: (k, _search(k, query, 1, credentials)), ("web", "blog", "cafe")))
    snippet, snippet_src, links = "", "", []
    for kind, items in results:
        for it in items:
            t, d = _clean(it.get("title")), _clean(it.get("description"))
            if not _relevant(t + " " + d, words):
                continue
            if "정제수" in d:
                part = d[d.find("정제수"):].split("...")[0]
                if part.count(",") > snippet.count(","):
                    snippet, snippet_src = part.rstrip(", "), it.get("link", "")
            # 카페 글은 로그인이 필요한 경우가 많아 요약만 쓰고, 쇼핑몰·블로그 페이지를 연다
            if kind != "cafe" and ("전성분" in t + d or "성분" in t) and it.get("link", "").startswith("http"):
                links.append((kind, it["link"]))
    links = list(dict.fromkeys(links))[:6]
    with ThreadPoolExecutor(max_workers=6) as pool:
        # 글자로 된 목록이 없을 때 이미지 글자 인식은 쇼핑몰 페이지 2곳까지만 (시간이 오래 걸려서)
        ocr_ok = {link for _, link in [l for l in links if l[0] == "web"][:2]}
        found = [f for f in pool.map(lambda l: _ingredients_from_page(l[1], words, l[1] in ocr_ok), links) if f[0]]
    if found:
        scored = [(sum(_same_list(a, b) for b, _ in found), a.count(","), a, src) for a, src in found]
        agree, _, best, src = max(scored)
        return best, src, {"pages": len(found), "agree": agree, "partial": False}
    if snippet.count(",") >= 4:
        return snippet, snippet_src, {"pages": 0, "agree": 0, "partial": True}
    return "", "", {}
