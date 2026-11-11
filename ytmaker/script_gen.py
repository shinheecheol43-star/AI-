"""Claude API로 유튜브 대본(JSON)을 생성한다."""

from __future__ import annotations

import json

from .presets import GENERAL, Preset

MODEL = "claude-opus-5-5"

SCRIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "유튜브 영상 제목 (클릭을 부르는, 40자 이내)"},
        "description": {"type": "string", "description": "유튜브 설명란 텍스트"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "thumbnail_text": {"type": "string", "description": "썸네일에 넣을 짧은 문구 (12자 이내)"},
        "scenes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "caption": {
                        "type": "string",
                        "description": "화면에 크게 띄울 핵심 문구 (15자 이내)",
                    },
                    "narration": {
                        "type": "string",
                        "description": "이 장면에서 읽을 내레이션. 자연스러운 구어체 한국어.",
                    },
                    "visual_prompt": {
                        "type": "string",
                        "description": "AI 이미지/영상 생성기(Higgsfield 등)에 넣을 영어 프롬프트. "
                        "피사체, 구도, 카메라 움직임, 조명, 분위기를 구체적으로.",
                    },
                },
                "required": ["caption", "narration", "visual_prompt"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "description", "tags", "thumbnail_text", "scenes"],
    "additionalProperties": False,
}

BASE_PROMPT = """너는 인기 있는 한국어 유튜브 채널의 전문 작가다.
요청받은 주제로 영상 대본을 장면 단위로 쓴다.

공통 원칙:
- 내레이션은 소리 내어 읽기 좋은 구어체 한국어로 쓴다. 괄호, 이모지, 기호, 영어 약어는 피한다.
- 한 장면의 내레이션은 1~3문장(대략 5~15초 분량)으로 한다.
- 사실 관계가 불확실한 숫자나 주장은 쓰지 않는다.
- visual_prompt는 영어로, 장면 내용을 그대로 보여주는 장면 묘사로 쓴다. 화면 안에 글자가 들어가지 않게 한다.

이 채널의 규칙:
{rules}"""


def build_system_prompt(preset: Preset, age: str = "4~7") -> str:
    prompt = BASE_PROMPT.format(rules=preset.script_rules.format(age=age))
    if preset.visual_style:
        prompt += f"\n- 모든 visual_prompt 끝에 다음 화풍을 붙인다: {preset.visual_style}"
    return prompt


def _target(minutes: float, fmt: str, slow: bool = False) -> str:
    # 한국어 TTS는 대략 분당 300~350자, 어린이용은 천천히 읽으므로 더 적게
    chars = int(minutes * (270 if slow else 320))
    scenes = max(3, round(minutes * 60 / 9))
    orient = "세로(9:16) 쇼츠" if fmt == "shorts" else "가로(16:9) 일반"
    return (
        f"형식: {orient} 영상\n"
        f"길이: 약 {minutes:g}분 (내레이션 총 {chars}자 안팎)\n"
        f"장면 수: 약 {scenes}개"
    )


def generate_script(
    topic: str,
    minutes: float = 3.0,
    fmt: str = "long",
    style: str | None = None,
    model: str = MODEL,
    preset: Preset = GENERAL,
    age: str = "4~7",
) -> dict:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("anthropic 패키지가 필요합니다: pip install anthropic") from exc

    client = anthropic.Anthropic()
    user = f"주제: {topic}\n{_target(minutes, fmt, preset.made_for_kids)}"
    if style:
        user += f"\n톤/스타일: {style}"

    try:
        response = client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=build_system_prompt(preset, age),
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": SCRIPT_SCHEMA},
            },
            # 안전 분류기가 거절하면 서버에서 다른 모델로 자동 재시도
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as exc:
        raise SystemExit(
            "Claude API 인증 실패: ANTHROPIC_API_KEY 환경변수를 확인하세요."
        ) from exc
    except anthropic.RateLimitError as exc:
        raise SystemExit("요청 한도 초과: 잠시 후 다시 시도하세요.") from exc
    except anthropic.APIConnectionError as exc:
        raise SystemExit(f"Claude API에 연결하지 못했습니다: {exc}") from exc

    if response.stop_reason == "refusal":
        raise SystemExit("요청이 거절되었습니다. 주제를 바꿔서 다시 시도하세요.")
    if response.stop_reason == "max_tokens":
        raise SystemExit("대본이 너무 길어 잘렸습니다. --minutes 값을 줄여 보세요.")

    text = next(b.text for b in response.content if b.type == "text")
    script = json.loads(text)
    script["preset"] = preset.name
    return script
