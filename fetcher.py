"""링크(제품 페이지)에서 광고 문구, 전성분, 리뷰를 무료로 가져오는 모듈.

유료 AI 없이 페이지의 글자만 읽어서 찾습니다.
- 글자로 된 페이지(브랜드 공식몰 등)는 잘 동작합니다.
- 성분이 이미지로만 되어 있거나, 리뷰를 나중에 불러오는 대형 쇼핑몰은 못 가져올 수 있습니다.
"""

import json
import re

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


def fetch_html(url):
    if not re.match(r"^https?://", url):
        url = "https://" + url
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
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


def _find_ingredients(lines):
    """'전성분' 다음에 오는 글, 또는 정제수·글리세린이 들어간 쉼표 많은 줄을 성분표로 본다."""
    for i, line in enumerate(lines):
        if "전성분" in line or "ingredients" in line.lower():
            after = re.split(r"전성분|ingredients", line, flags=re.I)[-1].strip(" :：")
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
            if 10 <= len(text) <= 300:
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


def parse(html):
    soup = BeautifulSoup(html, "html.parser")
    ld = _json_ld(soup)
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()

    lines = _lines(soup)
    reviews = list(dict.fromkeys(ld["reviews"] + _find_reviews(soup)))[:50]
    review_set = set(reviews)
    ingredients = _find_ingredients(lines)

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

    return {"title": title, "ad": ad_text, "ingredients": ingredients,
            "reviews": "\n".join(reviews), "notes": notes}


def read_link(url):
    return parse(fetch_html(url.strip()))
