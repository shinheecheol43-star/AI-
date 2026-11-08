"""링크(제품 페이지)에서 광고 문구, 전성분, 리뷰를 무료로 가져오는 모듈.

유료 AI 없이 페이지의 글자만 읽어서 찾습니다.
- 글자로 된 페이지(브랜드 공식몰 등)는 잘 동작합니다.
- 성분이 이미지로만 되어 있거나, 리뷰를 나중에 불러오는 대형 쇼핑몰은 못 가져올 수 있습니다.
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
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


AD_JUNK = re.compile(r"\{#|\{\$|SHIPPING|BOX|증정|할인|소득공제|\(\+[\d,]+원\)|쿠폰|적립|배송비|무료배송|^[\d,]+원|"
                     r"장바구니|구매하기|옵션|수량|품절|재입고|로그인|회원가입|적당량|펴 바르|사용 방법|사용법|덜어", re.I)
# 쇼핑몰이 직접 만든 리뷰 요약 문장 (리뷰가 아님)
SITE_SUMMARY = re.compile(r"^(고객|구매자|사용자)들은.*(평가|받았|좋아합|만족했)|평가를 받았습니다")
REVIEW_SERVICES = {"크리마(CREMA)": r"cre\.ma|crema", "브이리뷰": r"vreview", "알파리뷰": r"alph\.kr|alpha-?review",
                   "스냅리뷰": r"snapreview", "리뷰톡": r"reviewtalk"}


MENU_ITEM = re.compile(r"^\S{2,12}(패드|크림|토너|세럼|앰플|마스크|클렌저|폼|선크림|미스트|로션|에센스|팩|오일)$"
                       r"|^\S{1,6}\s*/\s*\S{1,6}$")  # '모공 / 결', '수분 / 보습' 같은 카테고리 메뉴


def clean_ad(text):
    lines = [l.strip() for l in text.split("\n")]
    # 'AD_JUNK': 가격·옵션·배송 글자 / 'MENU_ITEM': '제로모공패드'처럼 메뉴에 있는 다른 상품 이름
    return "\n".join(l for l in lines if len(l) >= 4 and not AD_JUNK.search(l) and not MENU_ITEM.match(l))


def _find_ad_lines(lines, limit=15):
    picked = []
    for line in lines:
        if line.startswith("[") or line.startswith("#") and line.count("#") == 1 or "주세요" in line:
            continue  # '[즉각 쿨링] 131 토너'처럼 다른 상품을 소개하는 메뉴
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
    services = [name for name, pat in REVIEW_SERVICES.items() if re.search(pat, html, re.I)]
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
    description = re.sub(r"[ \t]*\r?\n[\s]*", "\n", description).strip()
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
            "reviews": "\n".join(reviews), "notes": notes, "frames": frames, "services": services}


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


NAVERPAY_NOTE = re.compile(r"\(\s*\d{4}-\d{2}-\d{2}[^)]*구매평\s*\)")


def _board_article(item):
    """후기 글 하나를 열어 본문을 읽는다. 신고 양식 같은 다른 글자는 빼고 본문 칸만 본다."""
    title, link = item
    try:
        page = BeautifulSoup(fetch_html(link, timeout=6), "html.parser")
    except FetchError:
        return title
    for cls in ("fr-view", "detail"):
        box = page.find(attrs={"class": re.compile(rf"(^|\s){cls}(\s|$)")})
        if box:
            body = NAVERPAY_NOTE.sub("", re.sub(r"\s+", " ", box.get_text(" ", strip=True))).strip()
            if body:
                return body
    return title


DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _board_list_page(args):
    list_url, base = args
    try:
        soup = BeautifulSoup(fetch_html(list_url, timeout=10), "html.parser")
    except FetchError:
        return [], 0
    items, top = [], 0
    for tr in soup.find_all("tr"):
        a = tr.find("a", href=re.compile(r"/article/[^/]+/4/\d+|board/product/read\.html"))
        if not a:
            continue
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if cells and cells[0].replace(",", "").isdigit():  # 첫 칸의 글 번호 = 이 상품 후기 전체 개수 근처
            top = max(top, int(cells[0].replace(",", "")))
        m = DATE.search(tr.get_text(" "))
        items.append((re.sub(r"\s+", " ", a.get_text(" ", strip=True)), urljoin(base, a["href"]),
                      m.group(0) if m else ""))
    return items, top


def _spread_pages(n_pages, k):
    """1쪽부터 마지막 쪽까지 k개 쪽을 고르게 고른다. (최근 리뷰만 보지 않도록)"""
    if k >= n_pages:
        return list(range(1, n_pages + 1))
    if k == 1:
        return [1]
    return sorted({1 + round(i * (n_pages - 1) / (k - 1)) for i in range(k)})


def _cafe24_board(url, product_no, limit=400, progress=None):
    """카페24 상품 후기 게시판에서 이 상품의 후기를 전체 기간에 걸쳐 고르게 limit개 읽는다.
    반환: ([{"text", "date"}], 게시판의 이 상품 후기 전체 개수)"""
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    list_url = f"{base}/board/product/list.html?board_no=4&link_product_no={product_no}&page={{}}"
    first, total = _board_list_page((list_url.format(1), base))
    if not first:
        return [], 0
    per_page = len(first)
    n_pages = max(1, -(-max(total, per_page) // per_page))
    pages = _spread_pages(n_pages, max(1, -(-limit // per_page)))
    with ThreadPoolExecutor(max_workers=6) as pool:
        listed = list(pool.map(_board_list_page, [(list_url.format(p), base) for p in pages if p != 1]))
    rows = (first if 1 in pages else []) + [r for items, _ in listed for r in items]
    seen, picked = set(), []
    for title, link, date in rows:
        key = link.split("?")[0]  # 같은 제목('만족')이어도 글마다 따로
        if key not in seen:
            seen.add(key)
            picked.append((title, link, date))
    picked = picked[:limit]

    results = [None] * len(picked)
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_board_article, (t, l)): i for i, (t, l, _) in enumerate(picked)}
        for done, fut in enumerate(as_completed(futures), start=1):
            results[futures[fut]] = fut.result()
            if progress and done % 10 == 0:
                progress(done, len(picked))
    out = [{"text": t[:300], "date": d} for t, (_, _, d) in zip(results, picked) if t and len(t) >= 2]
    return out, max(total, len(out))


def _crema(url, product_no):
    """CREMA(크리마) 리뷰 서비스를 쓰는 쇼핑몰의 리뷰 화면을 읽는다."""
    host = urlparse(url).netloc
    domain = re.sub(r"^(www|m)\.", "", host)
    return _reviews_from_page(f"https://review4.cre.ma/{domain}/products/reviews?product_code={product_no}&iframe=1")


def read_link(url, review_limit=400, progress=None):
    url = url.strip()
    result = parse(fetch_html(url))
    # 상품 페이지에서 찾은 글 중 평가가 없는 건 안내 문구일 가능성이 높아서 뺀다
    result["ad"] = clean_ad(result["ad"])
    page_reviews = result["reviews"].split("\n") if result["reviews"] else []
    result["site_summary"] = [r for r in page_reviews if SITE_SUMMARY.search(r)]
    reviews = [r for r in page_reviews if _has_opinion(r) and r not in result["site_summary"]]
    sources, total, dated = [], 0, []
    if len(reviews) < 10:  # 적으면 다른 곳도 찾아본다
        extra = []
        for src in result["frames"]:
            got = [r for r in _reviews_from_page(urljoin(url, src)) if _has_opinion(r)]
            if got:
                extra += got
                sources.append("리뷰 창")
        product_no = _product_no(url)
        if product_no and not extra:
            items, total = _cafe24_board(url, product_no, review_limit, progress)
            if items:
                extra += [it["text"] for it in items]
                dated = items
                sources.append("상품 후기 게시판")
        if product_no and not extra:
            got = [r for r in _crema(url, product_no) if _has_opinion(r)]
            if got:
                extra += got
                sources.append("크리마 리뷰")
        reviews = extra + [r for r in reviews if r not in extra]
    reviews = reviews[:review_limit]
    result["notes"] = [n for n in result["notes"] if not n.startswith("리뷰를 찾지")]
    service = next(iter(result.get("services") or []), "")
    if len(reviews) < 10 and service:
        result["notes"].append(f"이 쇼핑몰은 리뷰를 외부 리뷰 서비스({service})에 모아 두어서 링크로는 "
                               f"{'리뷰를 읽을 수 없어요' if not reviews else f'리뷰를 {len(reviews)}개밖에 읽지 못했어요'}. "
                               "쇼핑몰 리뷰 화면에서 리뷰를 복사해 ‘직접 붙여넣기 → 실사용 리뷰’ 칸에 넣으면 제대로 분석할 수 있어요.")
    elif not reviews:
        result["notes"].append("리뷰를 찾지 못했어요. 이 사이트는 리뷰를 화면에서 따로 불러오는 방식이에요. "
                               "리뷰 글을 복사해서 ‘직접 붙여넣기 → 실사용 리뷰’ 칸에 넣어 주세요.")
    result["reviews"] = "\n".join(reviews)
    result["sources"] = sources
    result["review_total"] = total
    result["review_dates"] = [it["date"] for it in dated[:review_limit]] if dated else []
    result["sampled_evenly"] = bool(dated) and total > len(reviews)
    return result


def _has_opinion(text):
    clauses = az._clauses(text)
    if any(az._polarity(c) for c in clauses):
        return True
    return any(az._aspect_hit(c, p, n, t) for c in clauses for t, p, n in az.ASPECTS.values())
