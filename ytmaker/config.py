"""영상 포맷과 폰트 탐색 등 공통 설정."""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class VideoFormat:
    name: str
    width: int
    height: int
    fps: int = 30

    @property
    def vertical(self) -> bool:
        return self.height > self.width


FORMATS = {
    # 일반 유튜브 영상 (가로 16:9)
    "long": VideoFormat("long", 1920, 1080),
    # 유튜브 쇼츠 / 릴스 (세로 9:16)
    "shorts": VideoFormat("shorts", 1080, 1920),
}

# 한글이 들어있는 굵은 폰트 후보 (Windows / macOS / Linux 순)
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/Library/Fonts/AppleGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumSquareRoundEB.ttf",
    "/usr/share/fonts/truetype/nanum/NanumSquareB.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
]
_FONT_GLOBS = [
    "/usr/share/fonts/**/Noto*CJK*Bold*.tt[cf]",
    "/usr/share/fonts/**/Noto*Sans*KR*Bold*.[ot]tf",
    "/usr/share/fonts/**/Nanum*.ttf",
    os.path.expanduser("~/.fonts/**/*.tt[cf]"),
    os.path.expanduser("~/Library/Fonts/*.tt[cf]"),
]


def find_font(explicit: str | None = None) -> str:
    """한글을 표시할 수 있는 폰트 파일 경로를 찾는다."""
    if explicit:
        if not os.path.isfile(explicit):
            raise FileNotFoundError(f"폰트 파일을 찾을 수 없습니다: {explicit}")
        return explicit
    env = os.environ.get("YTMAKER_FONT")
    if env and os.path.isfile(env):
        return env
    for path in _FONT_CANDIDATES:
        if os.path.isfile(path):
            return path
    for pattern in _FONT_GLOBS:
        hits = sorted(glob.glob(pattern, recursive=True))
        if hits:
            return hits[0]
    raise FileNotFoundError(
        "한글 폰트를 찾지 못했습니다. --font 옵션이나 YTMAKER_FONT 환경변수로 "
        ".ttf/.otf 경로를 지정하세요 (예: 나눔고딕, 맑은 고딕)."
    )
