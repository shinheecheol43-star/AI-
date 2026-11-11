"""채널 성격별 프리셋: 대본 지침, 목소리, 색감, 업로드 설정."""

from __future__ import annotations

from dataclasses import dataclass, field

_GENERAL_PALETTES = [
    ((20, 24, 58), (88, 40, 140)),
    ((8, 48, 72), (16, 128, 140)),
    ((60, 16, 40), (196, 72, 72)),
    ((18, 18, 22), (64, 64, 84)),
    ((14, 56, 40), (60, 150, 100)),
    ((70, 40, 10), (210, 130, 40)),
]

# 밝은 파스텔 계열: 아이들 영상용
_KIDS_PALETTES = [
    ((255, 214, 102), (255, 150, 120)),  # 해님 노랑 → 살구
    ((140, 210, 255), (120, 150, 255)),  # 하늘 → 파랑
    ((170, 235, 170), (80, 190, 150)),   # 연두 → 초록
    ((255, 180, 220), (200, 140, 255)),  # 분홍 → 보라
    ((255, 200, 140), (255, 120, 140)),  # 주황 → 딸기
    ((150, 230, 230), (100, 180, 230)),  # 민트 → 바다
]


@dataclass(frozen=True)
class Preset:
    name: str
    script_rules: str
    voice: str
    rate: str
    pitch: str = "+0Hz"
    palettes: list = field(default_factory=lambda: _GENERAL_PALETTES)
    card_text_color: tuple = (255, 255, 255)
    visual_style: str = ""
    preferred_fonts: tuple = ()
    made_for_kids: bool = False


GENERAL = Preset(
    name="general",
    script_rules="""- 첫 장면은 3초 안에 시청자를 붙잡는 훅(질문, 놀라운 사실, 갈등)으로 시작한다.
- 내레이션은 소리 내어 읽기 좋은 짧은 문장의 구어체로 쓴다.
- 마지막 장면은 요약과 구독/댓글 유도로 마무리한다.""",
    voice="ko-KR-SunHiNeural",
    rate="+5%",
)

KIDS = Preset(
    name="kids",
    script_rules="""이 영상은 {age}세 어린이가 보는 영상이다.
- 다정한 선생님이나 언니/형이 옆에서 이야기해 주듯 따뜻한 존댓말 구어체("~해요", "~일까요?")로 쓴다.
- 그 나이 아이가 아는 쉬운 낱말만 쓴다. 한자어, 어려운 용어, 숫자 나열은 피하고, 꼭 필요하면 바로 쉽게 풀어 준다.
- 한 문장은 짧게(15자 안팎), 한 장면은 1~2문장으로 한다.
- 첫 장면은 아이가 궁금해할 질문이나 귀여운 등장인물로 시작한다.
- 중간중간 "여러분은 어떻게 생각해요?", "같이 따라 해 볼까요?"처럼 아이가 대답하거나 따라 할 수 있는 순간을 넣는다.
- 중요한 낱말이나 핵심 문장은 한 번 더 반복해서 기억에 남게 한다.
- 무섭거나 폭력적인 장면, 위험한 행동(따라 하면 다칠 수 있는 것), 부정적인 표현, 광고·구매 유도, 개인정보를 묻는 말은 절대 넣지 않는다.
- 사실은 정확하게 쓰고, 확실하지 않은 내용은 쓰지 않는다.
- 마지막 장면은 배운 내용을 한 문장으로 정리하고, 다정한 인사로 끝낸다. 구독·좋아요·댓글을 요청하지 않는다.""",
    voice="ko-KR-SunHiNeural",
    rate="-8%",
    pitch="+8Hz",
    palettes=_KIDS_PALETTES,
    card_text_color=(255, 255, 255),
    visual_style="cute 3D animated children's cartoon style, soft rounded shapes, bright pastel colors, "
    "friendly smiling characters, gentle lighting, safe and cheerful atmosphere, no text",
    preferred_fonts=(
        "/usr/share/fonts/truetype/nanum/NanumSquareRoundEB.ttf",
        "/usr/share/fonts/truetype/nanum/NanumSquareRoundB.ttf",
        r"C:\Windows\Fonts\NanumSquareRoundB.ttf",
        "~/Library/Fonts/NanumSquareRoundB.ttf",
    ),
    made_for_kids=True,
)

PRESETS = {"general": GENERAL, "kids": KIDS}
