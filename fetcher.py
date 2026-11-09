"""링크(제품 페이지)에서 광고 문구, 전성분, 리뷰를 무료로 가져오는 모듈.

유료 AI 없이 페이지의 글자만 읽어서 찾습니다.
- 글자로 된 페이지(브랜드 공식몰 등)는 잘 동작합니다.
- 성분이 이미지로만 되어 있거나, 리뷰를 나중에 불러오는 대형 쇼핑몰은 못 가져올 수 있습니다.
"""

import html
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
    for attempt in range(2):  # 사이트가 잠깐 느릴 때를 위해 한 번 더 시도
        try:
            res = requests.get(url, headers=HEADERS, timeout=timeout + 5 * attempt)
            break
        except (requests.Timeout, requests.ConnectionError) as e:
            if attempt == 1:
                raise FetchError(f"사이트에 접속하지 못했어요. ({type(e).__name__})") from e
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


def _join_broken(lines):
    """성분 목록 중간에 줄바꿈이 들어간 경우('…추출물' / ', 피토스테롤, …') 한 줄로 잇는다."""
    out = []
    for line in lines:
        if out and (line.startswith(",") or out[-1].rstrip().endswith(",")) and out[-1].count(",") >= 2:
            out[-1] = out[-1].rstrip(" ,") + ", " + line.lstrip(" ,")
        else:
            out.append(line)
    return out


def _find_ingredients(lines):
    """'전성분' 다음에 오는 글, 또는 정제수·글리세린이 들어간 쉼표 많은 줄을 성분표로 본다."""
    lines = _join_broken(lines)
    # 1순위: '전성분/FULL INGREDIENTS', 2순위: 그냥 'ingredients' ('Key Ingredients' 같은 주요 성분 소개는 빼고)
    for label in (r"전\s*성분|모든 성분|full\s+ingredients?|ingredients?\s*list", r"(?<!key )ingredients"):
        for i, line in enumerate(lines):
            if not re.search(label, line, re.I) or re.search(r"key\s+ingredients?|주요\s*성분", line, re.I) and \
                    not re.search(r"전\s*성분|full", line, re.I):
                continue
            after = re.split(label, line, flags=re.I)[-1].strip(" :：")
            for c in [after] + lines[i + 1:i + 4]:
                if c.count(",") >= 4:
                    return c
    best = ""
    for line in lines:
        if any(h in line.lower() for h in INGREDIENT_HINTS) and line.count(",") >= 4:
            if line.count(",") > best.count(","):
                best = line
    return best


REVIEW_JUNK = re.compile(r"^(포토|동영상|전체|베스트|최신|추천)?\s*(리뷰|후기|상품평|구매평)\s*(\(?[\d,]+|쓰기|작성|더보기|전체|보기|순)|"
                         r"^[\d,.\s★☆점%()/]+$|로그인|장바구니|구매하기|배송|도움이 돼요|신고|평점|"
                         r"교환\s*및\s*반품|반품\s*및\s*환불|전자상거래|청약\s*철회")


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
    title = re.sub(r"<[^>]+>", " ", html.unescape(title))  # 제목 속 HTML 태그(<br /> 등) 지우기
    # '제품명 이벤트 혜택/52% 특가/6개/118000원/증정' → '/'로 나눈 조각 중 홍보 문구가 나오기 전까지만
    PROMO = r"특가|할인|증정|혜택|이벤트|\d+%|\d[\d,]*원|\d+\s*(개|BOX|box|세트|매)|기획|사은품|무료배송|1\+1"
    parts = title.split("/")
    kept = []
    for part in parts:
        if kept and re.search(PROMO, part):
            break
        kept.append(part)
    title = "/".join(kept)
    title = re.sub(r"\s*(이벤트\s*혜택|이벤트|혜택가|특가|기획전?)\s*$", "", title)
    title = re.sub(r"\s+\S*(세일|SALE)\b.*$", "", title, flags=re.I)  # '제품명 슈퍼빅세일 BOX(130mL)'

    t = re.sub(r"\[[^\]]*\]|【[^】]*】", " ", title)
    t = re.sub(r"\s*[_|]\s*\d.*원.*$", "", t)
    t = re.sub(r"\s*\|.*$", "", t)  # '제품명 | 쇼핑몰 이름'
    t = re.sub(r"\s+", " ", t).strip() or title.strip()
    words = t.split()
    half = len(words) // 2
    if half and len(words) % 2 == 0 and words[:half] == words[half:]:  # '제품명 100ML 제품명 100ML'
        t = " ".join(words[:half])
    return t


SCRIPT_ING = re.compile(r'(?:모든\s*성분|전\s*성분|full\s*ingredients?)[^"]{0,40}"\s*[,:]\s*"((?:[^"\\]|\\.){30,5000})"', re.I)


def _ingredients_in_scripts(raw):
    """화면이 자바스크립트로 그려지는 쇼핑몰은 성분표가 페이지 속 데이터(JSON)에만 있다."""
    for m in SCRIPT_ING.finditer(raw):
        try:
            value = json.loads(f'"{m.group(1)}"')
        except ValueError:
            value = m.group(1)
        value = re.sub(r"<[^>]+>", " ", html.unescape(value)).replace("*", "")
        value = re.sub(r"\s+", " ", value).strip()
        if value.count(",") >= 4:
            return value
    return ""


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
    ingredients = table_ingredients or _find_ingredients(lines) or _ingredients_in_scripts(html)

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

    raw_title = soup.title.get_text(strip=True) if soup.title else ""
    site = _meta(soup, "og:site_name") or (re.split(r"\s[-|]\s", raw_title)[-1] if re.search(r"\s[-|]\s", raw_title) else "")
    return {"site_name": site.strip(), "title": clean_title(title), "ad": ad_text, "ingredients": ingredients,
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
        row_text = tr.get_text(" ", strip=True)
        if (cells and not cells[0].replace(",", "").isdigit() and re.search(r"공지|notice", str(tr), re.I)) or \
                re.search(r"적립금\s*안내|리뷰\s*작성\s*안내|REVIEW\s*MILEAGE|이벤트\s*안내", row_text, re.I):
            continue  # 맨 위에 고정된 공지 글은 리뷰가 아님
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
        # 같은 제목('만족')이어도 글마다 따로. 'read.html?no=123'처럼 글 번호가 ? 뒤에 있는 쇼핑몰도 있어서 page= 만 빼고 비교
        key = re.sub(r"[?&](page|link_product_no|board_no|cate_no)=[^&]*", "", link)
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
    out = [{"text": t[:300], "date": d} for t, (_, _, d) in zip(results, picked)
           if t and len(t) >= 2 and not re.search(r"적립금\s*안내|REVIEW\s*MILEAGE|리뷰\s*작성\s*안내", t, re.I)]
    return out, max(total, len(out))


# ---- 고도몰(NHN커머스) 쇼핑몰: 상품 화면이 불러오는 '상품후기' 게시판 목록을 똑같이 연다 ----
def _godomall_goods_no(url):
    q = parse_qs(urlparse(url).query)
    return q["goodsNo"][0] if "goodsNo" in q and "goods_view" in url else None


def _godomall_list_page(args):
    base, goods_no, page = args
    try:
        html = fetch_html(f"{base}/goods/goods_board_list.php?bdId=goodsreview&goodsNo={goods_no}&gboard=y&page={page}", timeout=10)
    except FetchError:
        return [], 1
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for tr in soup.select("tr.js_data_row"):
        if tr.get("data-notice") == "y":
            continue
        title = re.sub(r"\s+", " ", (tr.select_one(".board_tit") or tr).get_text(" ", strip=True))
        m = re.search(r"(\d{4})[.-](\d{2})[.-](\d{2})", tr.get_text(" "))
        items.append((title, f"{base}/board/view.php?bdId=goodsreview&sno={tr.get('data-sno')}",
                      "-".join(m.groups()) if m else ""))
    pages = [int(a.get_text(strip=True)) for a in soup.select(".pagination a, .pagination strong, .paging a")
             if a.get_text(strip=True).isdigit()]
    last = soup.select_one(".pagination .btn_page_last a, a.btn_page_last, .last a")
    if last and last.get("href"):
        m = re.search(r"page=(\d+)", last["href"])
        if m:
            pages.append(int(m.group(1)))
    return items, max(pages or [1])


def _godomall_article(item):
    title, link = item
    try:
        page = BeautifulSoup(fetch_html(link, timeout=6), "html.parser")
    except FetchError:
        return title
    box = page.select_one(".board_view_content") or page.select_one(".seem_cont")
    if not box:
        return title
    body = re.sub(r"\s+", " ", box.get_text(" ", strip=True))
    body = re.sub(r"^.{0,120}?판매\s*금액\s*\S+\s*", "", body)  # 맨 앞의 상품 이름·가격 칸
    return NAVERPAY_NOTE.sub("", body).strip() or title


def _godomall_board(url, goods_no, limit=400, progress=None):
    """고도몰 상품후기 게시판에서 전체 기간에 걸쳐 고르게 limit개 읽는다. 반환 형식은 _cafe24_board 와 같다."""
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    first, n_pages = _godomall_list_page((base, goods_no, 1))
    if not first:
        return [], 0
    per_page = len(first)
    pages = _spread_pages(n_pages, max(1, -(-limit // per_page)))
    with ThreadPoolExecutor(max_workers=6) as pool:
        listed = list(pool.map(_godomall_list_page, [(base, goods_no, p) for p in pages if p != 1]))
    rows = first + [r for items, _ in listed for r in items]
    picked = list({link: (t, link, d) for t, link, d in rows}.values())[:limit]
    results = [None] * len(picked)
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(_godomall_article, (t, l)): i for i, (t, l, _) in enumerate(picked)}
        for done, fut in enumerate(as_completed(futures), start=1):
            results[futures[fut]] = fut.result()
            if progress and done % 10 == 0:
                progress(done, len(picked))
    out = [{"text": t[:300], "date": d} for t, (_, _, d) in zip(results, picked) if t and len(t) >= 2]
    total = per_page * (n_pages - 1) + (len(listed[-1][0]) if listed and pages[-1] == n_pages else per_page) if n_pages > 1 else len(first)
    return out, max(total, len(out))


def _godomall_plus_page(args):
    """고도몰 '플러스리뷰' 목록 한 쪽 (본문이 목록에 다 들어 있음)"""
    base, goods_no, page = args
    try:
        html = fetch_html(f"{base}/board/plus_review_list.php?goodsNo={goods_no}&page={page}&activeSno=&sort=", timeout=10)
    except FetchError:
        return [], 1
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for row in soup.select(".js_pr_row"):
        box = row.select_one(".js_pr_contents_desc") or row.select_one(".js_pr_contents_short") or row.select_one(".review_text")
        if not box:
            continue
        for junk in box.select("style, a, script"):
            junk.decompose()
        text = re.sub(r"\s+", " ", box.get_text(" ", strip=True)).strip()
        m = re.search(r"(\d{4})[.-](\d{2})[.-](\d{2})", (row.select_one(".star_day_name") or row).get_text(" "))
        if text:
            items.append({"text": text[:300], "date": "-".join(m.groups()) if m else "", "sno": row.get("data-sno")})
    pages = [int(n) for n in re.findall(r"page=(\d+)", html)] + [page]
    return items, max(pages)


def _godomall_plus(url, goods_no, limit=400, progress=None):
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    first, n_pages = _godomall_plus_page((base, goods_no, 1))
    if not first:
        return [], 0
    # 쪽 번호가 10개씩만 보이는 경우가 있어서, 보이는 마지막 쪽을 열어 더 뒤가 있는지 확인
    for _ in range(30):
        _, more = _godomall_plus_page((base, goods_no, n_pages))
        if more <= n_pages:
            break
        n_pages = more
    per_page = len(first)
    pages = _spread_pages(n_pages, max(1, -(-limit // per_page)))
    with ThreadPoolExecutor(max_workers=6) as pool:
        listed = list(pool.map(_godomall_plus_page, [(base, goods_no, p) for p in pages if p != 1]))
    if progress:
        progress(1, 1)
    rows = first + [r for items, _ in listed for r in items]
    out = list({r["sno"] or r["text"]: r for r in rows}.values())[:limit]
    last = listed[-1][0] if listed and pages[-1] == n_pages else first
    total = per_page * (n_pages - 1) + len(last) if n_pages > 1 else len(first)
    return out, max(total, len(out))


def _crema(url, product_no):
    """CREMA(크리마) 리뷰 서비스를 쓰는 쇼핑몰의 리뷰 화면을 읽는다."""
    host = urlparse(url).netloc
    domain = re.sub(r"^(www|m)\.", "", host)
    return _reviews_from_page(f"https://review4.cre.ma/{domain}/products/reviews?product_code={product_no}&iframe=1")


def read_link(url, review_limit=400, progress=None):
    url = url.strip()
    html = fetch_html(url)
    result = parse(html)
    result["ing_image"] = ""
    if not result["ingredients"]:  # 성분표가 이미지로만 있으면 글자 인식으로 읽어 본다
        import ocr
        if ocr.available():
            found, image_url = ocr.find_in_images(html, url)
            if found:
                result["ingredients"], result["ing_image"] = found, image_url
                result["notes"] = [n for n in result["notes"] if not n.startswith("전성분을")]
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
        goods_no = _godomall_goods_no(url)
        if goods_no and not extra:
            items, total = _godomall_plus(url, goods_no, review_limit, progress)
            if len(items) < 10:  # 플러스리뷰가 적으면 일반 상품후기 게시판도 본다
                more, more_total = _godomall_board(url, goods_no, review_limit, progress)
                if len(more) > len(items):
                    items, total = more, more_total
            if items:
                extra += [it["text"] for it in items]
                dated = items
                sources.append("상품 후기 게시판")
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
    elif not reviews and re.search(r"(상품\s*후기|리뷰|REVIEW)\s*\(\s*0\s*\)", html, re.I):
        result["notes"].append("이 상품은 쇼핑몰에 아직 등록된 리뷰가 없어요(리뷰 0개). 블로그·카페 후기로 대신 분석해요.")
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
