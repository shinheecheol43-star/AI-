"""링크(제품 페이지)에서 광고 문구, 전성분, 리뷰를 무료로 가져오는 모듈.

유료 AI 없이 페이지의 글자만 읽어서 찾습니다.
- 글자로 된 페이지(브랜드 공식몰 등)는 잘 동작합니다.
- 성분이 이미지로만 되어 있거나, 리뷰를 나중에 불러오는 대형 쇼핑몰은 못 가져올 수 있습니다.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import analyzer as az

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

# 광고 문구로 볼 만한 줄을 고르는 단어 (효과 주장 + 과장 표현 + 해시태그)
CLAIM_WORDS = sorted({w for words, _, _ in az.ASPECTS.values() for w in words}
                     | set(az.EXAGGERATION) | set(az.MEDICAL) | {"#"})
INGREDIENT_HINTS = ["정제수", "글리세린", "water", "aqua"]


class FetchError(Exception):
    pass


def fetch_html(url, timeout=10):
    if not re.match(r"^https?://", url):
        url = "https://" + url
    try:
        res = requests.get(url, headers=HEADERS, timeout=timeout)
    except requests.RequestException as e:
        raise FetchError(f"사이트에 접속하지 못했어요. ({type(e).__name__})") from e
    if res.status_code != 200:
        raise FetchError(f"사이트가 접속을 거절했어요. (응답 코드 {res.status_code}) "
                         "자동 접속을 막는 사이트일 수 있어요.")
    if res.encoding is None or res.encoding.lower() == "iso-8859-1":
        res.encoding = res.apparent_encoding
    return res.text


# ---------------------------------------------------------------------------
# 페이지 안의 구조화 데이터(JSON-LD): 많은 쇼핑몰이 검색엔진용으로 제품 정보와 리뷰를 넣어둡니다.
# ---------------------------------------------------------------------------
def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _json_ld(soup):
    product = {"name": "", "description": "", "reviews": []}
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _walk(data):
            kind = node.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if "Product" in kinds:
                product["name"] = product["name"] or str(node.get("name", ""))
                product["description"] = product["description"] or str(node.get("description", ""))
            if "Review" in kinds and node.get("reviewBody"):
                product["reviews"].append(str(node["reviewBody"]))
    return product


def _meta(soup, *names):
    for n in names:
        tag = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


def _lines(soup):
    text = soup.get_text("\n")
    seen, out = set(), []
    for line in text.split("\n"):
        line = re.sub(r"\s+", " ", line).strip()
        if line and line not in seen:
            seen.add(line)
            out.append(line)
    return out


def _find_ingredients_in_table(soup):
    """상품정보제공고시 표의 '화장품법에 따라 기재해야 하는 모든 성분' 같은 칸을 찾는다."""
    for label in soup.find_all(["th", "td", "dt", "strong", "span"]):
        text = label.get_text(" ", strip=True)
        if "성분" not in text or len(text) > 40:
            continue
        value = label.find_next_sibling(["td", "dd"]) or label.find_next(["td", "dd"])
        if value:
            v = re.sub(r"\s+", " ", value.get_text(" ", strip=True))
            if v.count(",") >= 4:
                return v
    return ""


def _find_ingredients(lines):
    """'전성분' 다음에 오는 글, 또는 정제수·글리세린이 들어간 쉼표 많은 줄을 성분표로 본다."""
    for i, line in enumerate(lines):
        if "전성분" in line or "모든 성분" in line or "ingredients" in line.lower():
            after = re.split(r"전성분|모든 성분|ingredients", line, flags=re.I)[-1].strip(" :：")
            candidates = [after] + lines[i + 1:i + 4]
            for c in candidates:
                if c.count(",") >= 4:
                    return c
    best = ""
    for line in lines:
        if any(h in line.lower() for h in INGREDIENT_HINTS) and line.count(",") >= 4:
            if line.count(",") > best.count(","):
                best = line
    return best


REVIEW_JUNK = re.compile(r"^(포토|동영상|전체|베스트|최신|추천)?\s*(리뷰|후기|상품평|구매평)\s*(\(?[\d,]+|쓰기|작성|더보기|전체|보기|순)|"
                         r"^[\d,.\s★☆점%()/]+$|로그인|장바구니|구매하기|배송|도움이 돼요|신고|평점")


def _looks_like_review(text):
    """버튼·제목 글자('리뷰 1,234건', '리뷰 쓰기')가 아니라 실제 후기 문장인지 판단."""
    if len(text) < 10 or REVIEW_JUNK.search(text):
        return False
    return bool(re.search(r"[가-힣]{2,}", text)) and bool(re.search(r"(요|다|음|함|듯|네|ㅎ|ㅋ|[!~.])\s*$|요\s", text))


def _find_reviews(soup):
    """class나 id에 'review'가 들어간 영역에서 리뷰 문장을 모은다."""
    reviews = []
    pattern = re.compile(r"review|리뷰|후기|comment", re.I)
    areas = soup.find_all(attrs={"class": pattern}) + soup.find_all(attrs={"id": pattern})
    for area in areas:
        for el in area.find_all(["p", "li", "span", "div"]):
            if el.find(["p", "li", "div"]):
                continue  # 가장 안쪽 글자만
            text = re.sub(r"\s+", " ", el.get_text(" ")).strip()
            if len(text) <= 300 and _looks_like_review(text):
                reviews.append(text)
    return reviews


def _find_ad_lines(lines, limit=15):
    picked = []
    for line in lines:
        if 6 <= len(line) <= 150 and line.count(",") < 4 and any(w in line for w in CLAIM_WORDS):
            picked.append(line)
        if len(picked) >= limit:
            break
    return picked


def clean_title(title):
    """'[55%] [더블기획] 제품명 _1개당 22,375원' 같은 할인 문구를 정리한다."""
    t = re.sub(r"\[[^\]]*\]|【[^】]*】", " ", title)
    t = re.sub(r"\s*[_|]\s*\d.*원.*$", "", t)
    t = re.sub(r"\s*\|.*$", "", t)  # '제품명 | 쇼핑몰 이름'
    return re.sub(r"\s+", " ", t).strip() or title.strip()


def parse(html):
    soup = BeautifulSoup(html, "html.parser")
    ld = _json_ld(soup)
    frames = [f.get("src") for f in soup.find_all("iframe")
              if f.get("src") and re.search(r"review|cre\.ma|vreview|리뷰", f.get("src"), re.I)]
    table_ingredients = _find_ingredients_in_table(soup)
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()

    lines = _lines(soup)
    reviews = list(dict.fromkeys([r for r in ld["reviews"] if len(r) >= 5] + _find_reviews(soup)))[:50]
    review_set = set(reviews)
    ingredients = table_ingredients or _find_ingredients(lines)

    title = ld["name"] or _meta(soup, "og:title") or (soup.title.get_text(strip=True) if soup.title else "")
    description = ld["description"] or _meta(soup, "og:description", "description")
    body_lines = [l for l in lines if l not in review_set and l != ingredients]
    ad_lines = [l for l in [description] + _find_ad_lines(body_lines) if l]
    ad_text = "\n".join(dict.fromkeys(ad_lines))

    notes = []
    if not ingredients:
        n_img = len(soup.find_all("img"))
        notes.append(f"전성분을 글자로 찾지 못했어요. 상세페이지가 이미지(이미지 {n_img}개)로 되어 있을 수 있어요. "
                     "성분표를 직접 붙여넣어 주세요.")
    if not reviews:
        notes.append("리뷰를 찾지 못했어요. 리뷰를 따로 불러오는 사이트일 수 있어요. 리뷰를 직접 붙여넣어 주세요.")
    if not ad_text:
        notes.append("광고 문구를 찾지 못했어요.")

    return {"title": clean_title(title), "ad": ad_text, "ingredients": ingredients,
            "reviews": "\n".join(reviews), "notes": notes, "frames": frames}


# ---------------------------------------------------------------------------
# 리뷰를 따로 불러오는 사이트를 위한 추가 경로
# ---------------------------------------------------------------------------
def _product_no(url):
    q = parse_qs(urlparse(url).query)
    if "product_no" in q:
        return q["product_no"][0]
    m = re.search(r"/product/[^/]+/(\d+)/", url) or re.search(r"/surl/p/(\d+)", url)
    return m.group(1) if m else None


def _reviews_from_page(url):
    try:
        soup = BeautifulSoup(fetch_html(url, timeout=6), "html.parser")
    except FetchError:
        return []
    return _find_reviews(soup)


def _cafe24_board(url, product_no, limit=10):
    """카페24 쇼핑몰의 상품 후기 게시판(보통 board_no=4)에서 후기 제목과 내용을 읽는다."""
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    list_url = f"{base}/board/product/list.html?board_no=4&link_product_no={product_no}"
    try:
        soup = BeautifulSoup(fetch_html(list_url, timeout=6), "html.parser")
    except FetchError:
        return []
    links = []
    for a in soup.find_all("a", href=True):
        title = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if re.search(r"/article/|board/product/read\.html", a["href"]) and len(title) >= 4:
            links.append((title, urljoin(base, a["href"])))
    links = list(dict(links).items())[:limit] if links else []

    def read(item):
        title, link = item
        try:
            page = BeautifulSoup(fetch_html(link, timeout=6), "html.parser")
        except FetchError:
            return title
        boxes = [re.sub(r"\s+", " ", d.get_text(" ", strip=True))
                 for d in page.find_all(attrs={"class": re.compile(r"detail|fr-view|view|content", re.I)})]
        boxes = [b for b in boxes if 5 <= len(b) <= 1500]
        body = max(boxes, key=len) if boxes else ""
        return body if len(body) >= 10 else f"{title} {body}".strip()

    with ThreadPoolExecutor(max_workers=5) as pool:
        texts = list(pool.map(read, links))
    return [t[:300] for t in texts if len(t) >= 8]


def _crema(url, product_no):
    """CREMA(크리마) 리뷰 서비스를 쓰는 쇼핑몰의 리뷰 화면을 읽는다."""
    host = urlparse(url).netloc
    domain = re.sub(r"^(www|m)\.", "", host)
    return _reviews_from_page(f"https://review4.cre.ma/{domain}/products/reviews?product_code={product_no}&iframe=1")


def read_link(url):
    url = url.strip()
    result = parse(fetch_html(url))
    reviews = result["reviews"].split("\n") if result["reviews"] else []
    sources = []
    if len(reviews) < 10:  # 상품 페이지에서 찾은 게 적으면 (버튼 글자일 수도 있으니) 다른 곳도 찾아본다
        extra = []
        for src in result["frames"]:
            got = _reviews_from_page(urljoin(url, src))
            if got:
                extra += got
                sources.append("리뷰 창")
        product_no = _product_no(url)
        if product_no and not extra:
            got = _cafe24_board(url, product_no)
            if got:
                extra += got
                sources.append("상품 후기 게시판")
        if product_no and not extra:
            got = _crema(url, product_no)
            if got:
                extra += got
                sources.append("크리마 리뷰")
        if extra:
            reviews = list(dict.fromkeys(extra + reviews))[:50]
            result["reviews"] = "\n".join(reviews)
            result["notes"] = [n for n in result["notes"] if not n.startswith("리뷰를 찾지")]
        elif not reviews:
            result["notes"] = [n for n in result["notes"] if not n.startswith("리뷰를 찾지")] + [
                "리뷰를 찾지 못했어요. 이 사이트는 리뷰를 화면에서 따로 불러오는 방식이에요. "
                "리뷰 글을 복사해서 ‘직접 붙여넣기 → 실사용 리뷰’ 칸에 넣어 주세요."]
    result["sources"] = sources
    return result
