"""장면 배경 카드와 썸네일 이미지 생성 (Pillow)."""

from __future__ import annotations

import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .presets import GENERAL


def _gradient(w: int, h: int, top, bottom, seed: int) -> Image.Image:
    base = Image.new("RGB", (1, 256))
    for y in range(256):
        t = y / 255
        base.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    img = base.resize((w, h), Image.BILINEAR)
    # 부드러운 빛 번짐 몇 개로 단조로움을 줄인다
    rng = random.Random(seed)
    glow = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(glow)
    for _ in range(4):
        r = rng.randint(min(w, h) // 5, min(w, h) // 2)
        x, y = rng.randint(0, w), rng.randint(0, h)
        d.ellipse((x - r, y - r, x + r, y + r), fill=rng.randint(40, 90))
    glow = glow.filter(ImageFilter.GaussianBlur(min(w, h) // 8))
    return Image.composite(Image.new("RGB", (w, h), (255, 255, 255)), img, glow.point(lambda v: v // 3))


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split():
            trial = f"{cur} {word}".strip()
            if draw.textlength(trial, font=font) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        # 띄어쓰기 없이 긴 단어는 글자 단위로 자른다
        while cur and draw.textlength(cur, font=font) > max_w:
            i = len(cur)
            while i > 1 and draw.textlength(cur[:i], font=font) > max_w:
                i -= 1
            lines.append(cur[:i])
            cur = cur[i:]
        if cur:
            lines.append(cur)
    return lines


def _draw_centered(img: Image.Image, text: str, font_path: str, size: int, y_center: float,
                   max_w_ratio: float = 0.82, fill=(255, 255, 255), stroke=0, accent=None):
    draw = ImageDraw.Draw(img)
    w, h = img.size
    font = ImageFont.truetype(font_path, size)
    lines = _wrap(draw, text, font, int(w * max_w_ratio))
    line_h = int(size * 1.25)
    y = int(h * y_center - line_h * len(lines) / 2)
    for i, line in enumerate(lines):
        tw = draw.textlength(line, font=font)
        color = accent if (accent and i == len(lines) - 1 and len(lines) > 1) else fill
        draw.text(((w - tw) / 2, y), line, font=font, fill=color,
                  stroke_width=stroke, stroke_fill=(0, 0, 0))
        y += line_h
    return y


def make_scene_card(path: str, caption: str, index: int, total: int, size: tuple[int, int],
                    font_path: str, vertical: bool, palettes=None) -> None:
    """AI 영상/이미지가 없는 장면용 배경 카드."""
    w, h = size
    # Ken Burns 확대 여유를 위해 약간 크게 만든다
    W, H = int(w * 1.15), int(h * 1.15)
    palettes = palettes or GENERAL.palettes
    top, bottom = palettes[index % len(palettes)]
    img = _gradient(W, H, top, bottom, seed=index)
    if caption:
        fs = int(min(W, H) * (0.085 if vertical else 0.095))
        # 세로 영상은 자막이 아래쪽이므로 문구를 위로 올린다
        _draw_centered(img, caption, font_path, fs, 0.36 if vertical else 0.42,
                       stroke=max(2, fs // 18))
    # 진행 표시 점
    d = ImageDraw.Draw(img)
    r = max(6, W // 220)
    gap = r * 4
    x0 = W / 2 - (total - 1) * gap / 2
    yy = int(H * (0.12 if vertical else 0.1))
    for i in range(total):
        fill = (255, 255, 255) if i == index else (255, 255, 255, 90)
        x = x0 + i * gap
        d.ellipse((x - r, yy - r, x + r, yy + r), fill=fill if i == index else (140, 140, 160))
    img.save(path)


def make_thumbnail(path: str, text: str, size: tuple[int, int], font_path: str,
                   background: str | None = None, colors=((180, 20, 40), (30, 10, 60))) -> None:
    """유튜브 썸네일 (가로 1280x720 / 쇼츠는 1080x1920)."""
    w, h = size
    if background:
        bg = Image.open(background).convert("RGB")
        scale = max(w / bg.width, h / bg.height)
        bg = bg.resize((int(bg.width * scale) + 1, int(bg.height * scale) + 1), Image.LANCZOS)
        left, top = (bg.width - w) // 2, (bg.height - h) // 2
        img = bg.crop((left, top, left + w, top + h))
        shade = Image.new("RGB", (w, h), (0, 0, 0))
        img = Image.blend(img, shade, 0.35)
    else:
        img = _gradient(w, h, colors[0], colors[1], seed=99)
    fs = int(min(w, h) * (0.2 if h <= w else 0.12))
    _draw_centered(img, text, font_path, fs, 0.5, max_w_ratio=0.9,
                   fill=(255, 255, 255), stroke=max(4, fs // 12), accent=(255, 230, 0))
    img.save(path)
