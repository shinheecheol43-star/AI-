"""상세페이지 '이미지' 속 전성분 읽기 (무료 글자 인식 Tesseract 사용).

많은 쇼핑몰이 성분표를 글자가 아니라 이미지로 올려요. 그래서
1) 상세 이미지 중 글자가 많은 이미지부터 읽어서 '전성분'이 나오는 이미지를 찾고
2) 그 부분 글자를 뽑은 뒤
3) 글자 인식에서 자주 생기는 실수를 고쳐서 성분 목록으로 만든다.

서버에 tesseract-ocr, tesseract-ocr-kor 가 설치돼 있어야 해요 (packages.txt).
"""

import difflib
import io
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"}
START = re.compile(r"전\s*성\s*분|모든\s*성분|성\s*분\s*명|INGREDIENTS", re.I)
STOP = re.compile(r"\d\s*\.\s*화장품\s*사용|화장품\s*사용\s*시|화장품\s*법|사용\s*(전|시|상|할\s*때)\s*(의\s*)?주의|주의\s*사항|사용\s*방법|사용\s*기한|보관\s*방법|품질\s*보증|"
                  r"화장품\s*책임|제조\s*(국|업자|번호)|기능성\s*화장품|용량|중량|소비자\s*상담")
# 이름이 이렇게 끝나면 성분 하나가 끝난 것으로 본다 (쉼표가 빠져도 나누기 위해)
ENDINGS = ("추출물", "발효물", "여과물", "오일", "워터", "수", "올", "콜", "린", "드", "트", "인", "산", "머", "텐", "민",
           "놀", "콘", "세인", "에터", "이트", "소포", "아민", "겔", "왁스", "분말", "액", "즙", "검", "료", "솔", "논",
           "젠", "론", "틴", "신", "닌", "롤", "벤", "졸", "슘", "륨", "늄", "케이트", "에이트", "라이드", "오사이드",
           "에이", "티", "버터", "스", "말", "업", "녹스", "넨", "란", "카", "아")
# 글자 인식이 자주 헷갈리는 글자 고치기
FIXES = [
    (r"[추주수]\s*[출줄]\s*[물몰]", "추출물"), (r"추출\s*몰", "추출물"), (r"발효\s*몰", "발효물"), (r"추출\s+물", "추출물"), (r"핵실", "헥실"), (r"핵산", "헥산"),
    (r"^1?2-?(한|핵산|헥산|헤산|해산|핵|헥)?\s*다이올", "1,2-헥산다이올"), (r"(헤산|해산)다이올", "헥산다이올"),
    (r"(?<=[가-힣])\d{1,2}$", ""),  # '펜틸렌글라이콜1'처럼 이름 끝에 붙은 잘못 읽은 숫자 ('세테스-20'처럼 - 뒤 숫자는 그대로)
    (r"소[듬등튬]", "소듐"), (r"펠타이드", "펩타이드"), (r"포타[승숨슴]", "포타슘"), (r"솔베이트", "소르베이트"), (r"포타슴", "포타슘"), (r"클라이콜", "글라이콜"),
    (r"꿀품", "꿀풀"), (r"([가-힣])(익|위|임)추출물", r"\1잎추출물"), (r"(껄|낄|겁질|껍칠)추출물", "껍질추출물"),
    (r"야풍년화", "아풍년화"), (r"/2?10-30", "/C10-30"), (r"^l", "1"), (r"소튬", "소듐"), (r"글리세런", "글리세린"),
    (r"정재수", "정제수"), (r"정제 수", "정제수"), (r"밥질추출물", "밤껍질추출물"),
    (r"에[칠틸]렉실", "에칠헥실"), (r"헤노에이트", "헥사노에이트"), (r"나무질추출물", "나무껍질추출물"),
    (r"\([^)]*[ㄱ-ㅎㅏ-ㅣ][^)]*\)", ""),  # '(101.860ㅁㅁ0)'처럼 괄호 안이 깨진 글자
]


def available():
    """서버에 글자 인식 프로그램이 있는지"""
    try:
        import PIL  # noqa: F401
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return shutil.which("tesseract") is not None


def image_urls(html, base_url):
    """상세 설명 영역의 이미지 주소 (나중에 불러오는 이미지도 포함)"""
    soup = BeautifulSoup(html, "html.parser")
    # 카페24: prdDetail / edibot, 고도몰: detail_explain_box, 그 밖: detail·cont 가 들어간 영역
    area = (soup.find(id="prdDetail") or soup.find(class_=re.compile(r"edibot-product-detail|detail_explain|goods_description|txt-manual", re.I))
            or soup.find(class_=re.compile(r"detail|cont", re.I)) or soup)
    if len(area.find_all("img")) < 2:
        area = soup
    urls = []
    for img in area.find_all("img"):
        src = (img.get("ec-data-src") or img.get("data-src") or img.get("data-original") or img.get("data-lazy")
               or img.get("data-lazy-src") or img.get("src") or "")
        if not src or src.startswith("data:") or re.search(r"icon|btn|logo|banner_top|blank|spacer", src, re.I):
            continue
        u = urljoin(base_url, src)
        if u not in urls:
            urls.append(u)
    return urls


def _download(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200 and len(res.content) < 12_000_000:
            return url, res.content
    except requests.RequestException:
        pass
    return url, None


def _ocr(image, scale=2):
    """이미지를 키워서 한글로 읽는다. 아주 긴 이미지는 잘라서 읽는다."""
    import pytesseract
    from PIL import Image, ImageOps
    gray = image.convert("L")
    texts = []
    for top, bottom in _cuts(gray):
        piece = gray.crop((0, top, gray.width, bottom))
        piece = ImageOps.autocontrast(piece.resize((piece.width * scale, piece.height * scale), Image.LANCZOS))
        texts.append(pytesseract.image_to_string(piece, lang="kor", config="--psm 6"))
    return "\n".join(texts)


def _cuts(gray, size=3500):
    """아주 긴 이미지는 글자가 없는 줄(가장 고른 줄)에서 잘라 겹치지 않게 나눈다."""
    import numpy as np
    if gray.height <= size + 500:
        return [(0, gray.height)]
    arr = np.asarray(gray, dtype=np.float32)
    rows = arr.std(axis=1)
    cuts, top = [], 0
    while gray.height - top > size + 500:
        lo, hi = top + size - 400, min(gray.height - 1, top + size + 400)
        y = lo + int(rows[lo:hi].argmin())
        cuts.append((top, y))
        top = y
    cuts.append((top, gray.height))
    return cuts


def extract_section(text):
    """글자 전체에서 '전성분' 다음부터 다음 항목(주의사항 등) 전까지"""
    m = START.search(text)
    if not m:
        i = text.find("정제수")
        if i < 0:
            return ""
        seg = text[i:]
    else:
        # 표 왼쪽 칸에 '전성분'이 세로 가운데에 있으면, 목록 앞부분이 이 글자보다 먼저 읽힌다 → '정제수'부터 시작
        before = text[max(0, m.start() - 900): m.start()]
        j = before.rfind("정제수")
        if j >= 0 and before[j:].count(",") >= 2:
            seg = before[j:] + " " + text[m.end():]
        else:
            seg = text[m.end():]
    e = STOP.search(seg)
    seg = seg[: e.start()] if e else seg[:2500]
    return seg.strip(" :：\n")


def _vocab():
    import analyzer as az
    words = set()
    for info in az.INGREDIENTS.values():
        words.update(a for a in info["alias"] if re.search(r"[가-힣]", a))
    return sorted(words, key=len, reverse=True)


def clean_ingredients(segment):
    """글자 인식 결과 → '성분1, 성분2, ...' (실수 고치기 + 쉼표 빠진 곳 나누기)"""
    text = re.sub(r"\n+", "", segment)                       # 줄바꿈으로 잘린 이름 잇기
    for pat, rep_ in FIXES:
        if not pat.startswith("^"):
            text = re.sub(pat, rep_, text)                  # '주출물' 같은 실수를 먼저 고쳐야 이름 끝을 알아봄
    text = re.sub(r"[·ㆍ|]", ",", text)
    text = re.sub(r"[^\w가-힣,/()\-.%\s]", " ", text)
    pieces = []
    for chunk in text.split(","):
        parts = [p for p in chunk.split() if p]
        buf = ""
        for p in parts:
            buf += p
            if buf.endswith(ENDINGS) and len(buf) >= 2:
                pieces.append(buf)
                buf = ""
        if buf:
            if pieces and len(buf) <= 2:
                pieces[-1] += buf
            else:
                pieces.append(buf)
    vocab = _vocab()
    out = []
    for p in pieces:
        p = p.strip(" .-")
        for pat, rep in FIXES:
            p = re.sub(pat, rep, p)
        if not re.search(r"[가-힣]", p) or len(p) < 2:
            continue  # 영어 쓰레기 글자 등
        close = difflib.get_close_matches(p, vocab, n=1, cutoff=0.86)
        out.append(close[0] if close and abs(len(close[0]) - len(p)) <= 2 else p)
    return ", ".join(dict.fromkeys(out))


def _priority(item):
    """글자가 많은 이미지(흰 바탕에 글씨 → 같은 크기면 파일이 작음)와 뒤쪽 이미지를 먼저 읽는다.
    아주 긴 홍보 이미지(세로 6000px 이상)는 성분표일 가능성이 낮아 마지막에 읽는다."""
    idx, (url, data, size) = item
    w, h = size
    density = len(data) / max(w * h, 1)
    return (h > 6000, density > 0.6, density, -idx)


def _quick(image):
    """'전성분'이 있는지만 빠르게 확인 (원래 크기로 읽음)"""
    import pytesseract
    from PIL import ImageOps
    gray = ImageOps.autocontrast(image.convert("L"))
    texts = []
    for top, bottom in _cuts(gray, size=4000):
        texts.append(pytesseract.image_to_string(gray.crop((0, top, gray.width, bottom)), lang="kor", config="--psm 6"))
    return "\n".join(texts)


def find_in_images(html, base_url, budget=70, max_images=60):
    """상세 이미지에서 전성분을 찾는다. 반환: (전성분 글, 그 이미지 주소) 또는 ("", "")"""
    if not available():
        return "", ""
    from PIL import Image
    start = time.time()
    urls = image_urls(html, base_url)[:max_images]
    with ThreadPoolExecutor(max_workers=8) as pool:
        downloaded = [(u, d) for u, d in pool.map(_download, urls) if d]
    items = []
    for i, (u, d) in enumerate(downloaded):
        try:
            img = Image.open(io.BytesIO(d))
            img.load()
        except Exception:
            continue
        if img.width < 300 or img.height < 150:
            continue
        items.append((i, (u, d, img.size, img)))
    order = sorted(((i, (u, d, s)) for i, (u, d, s, _) in items), key=_priority)
    images = {i: img for i, (_, _, _, img) in items}
    cache = {}

    def read(i):
        if i not in cache:
            cache[i] = _ocr(images[i]) if i in images else ""
        return cache[i]

    for i, (u, _, _) in order:
        if time.time() - start > budget:
            break
        quick = _quick(images[i])  # 1단계: 빠르게 훑어서 성분표 이미지 찾기
        if not (START.search(quick) or "정제수" in quick or re.search(r"[가-힣]+(추출물|글라이콜|다이올)", quick)):
            continue
        text = read(i)              # 2단계: 찾은 이미지만 크게 키워서 정확하게 읽기
        if START.search(text) or text.count("정제수"):
            # 성분표가 이미지 두 장에 걸쳐 있을 수 있어서, 앞뒤 이미지도 이어서 읽는다
            if not START.search(text) and i - 1 in images:
                text = read(i - 1) + "\n" + text
            if not STOP.search(text[(START.search(text) or re.search("정제수", text)).end():]) and i + 1 in images:
                text = text + "\n" + read(i + 1)
            seg = extract_section(text)
            cleaned = clean_ingredients(seg)
            if cleaned.count(",") >= 4:
                return cleaned, u
    return "", ""


def read_upload(data):
    """사용자가 올린 성분표 캡처에서 전성분 읽기 (보완 방법)"""
    if not available():
        return ""
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    text = _ocr(img)
    seg = extract_section(text) or text
    return clean_ingredients(seg)
