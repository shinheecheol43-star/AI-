"""내레이션 음성 합성 + 문장별 타이밍 추출."""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
from dataclasses import dataclass

DEFAULT_VOICE = "ko-KR-SunHiNeural"  # 여성. 남성: ko-KR-InJoonNeural / ko-KR-HyunsuMultilingualNeural


@dataclass
class Cue:
    start: float  # 장면 내 시작 시각(초)
    end: float
    text: str


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。？！…])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def probe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _proportional_cues(sentences: list[str], duration: float) -> list[Cue]:
    total = sum(len(s) for s in sentences) or 1
    cues, t = [], 0.0
    for s in sentences:
        d = duration * len(s) / total
        cues.append(Cue(t, t + d, s))
        t += d
    return cues


async def _edge_tts(text: str, voice: str, rate: str, pitch: str, out_path: str) -> list[Cue]:
    import edge_tts

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="SentenceBoundary", proxy=proxy)
    cues: list[Cue] = []
    with open(out_path, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                start = chunk["offset"] / 1e7  # 100ns 단위
                cues.append(Cue(start, start + chunk["duration"] / 1e7, chunk["text"]))
    return cues


def synthesize(
    text: str,
    out_path: str,
    engine: str = "edge",
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> tuple[float, list[Cue]]:
    """음성 파일을 만들고 (길이, 자막 큐 목록)을 반환한다.

    engine:
      edge   - Microsoft Edge 온라인 TTS (무료, 인터넷 필요)
      silent - 무음 + 예상 길이 (직접 녹음할 때 / 오프라인 테스트용)
    """
    sentences = split_sentences(text)
    if engine == "edge":
        cues = asyncio.run(_edge_tts(text, voice, rate, pitch, out_path))
        duration = probe_duration(out_path)
        if not cues:
            cues = _proportional_cues(sentences, duration)
    elif engine == "silent":
        duration = max(1.5, len(text.replace(" ", "")) * 0.17)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
             "anullsrc=r=24000:cl=mono", "-t", f"{duration:.3f}", "-q:a", "9", out_path],
            check=True,
        )
        cues = _proportional_cues(sentences, duration)
    else:
        raise ValueError(f"알 수 없는 TTS 엔진: {engine}")
    return duration, cues


def chunk_cue(cue: Cue, max_chars: int) -> list[Cue]:
    """긴 문장을 화면에 맞게 여러 자막으로 나눈다 (어절 단위)."""
    if len(cue.text) <= max_chars:
        return [cue]
    words = cue.text.split()
    # 필요한 줄 수를 정한 뒤, 각 줄 길이가 비슷해지도록 어절을 나눈다
    n = min(len(words), -(-len(cue.text) // max_chars))
    target = len(cue.text) / n
    lines, cur = [], ""
    for i, w in enumerate(words):
        remaining_words = len(words) - i
        remaining_lines = n - len(lines)
        trial = f"{cur} {w}".strip()
        if cur and (len(trial) > target * 1.15 or remaining_words < remaining_lines) \
                and len(lines) < n - 1:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    total = sum(len(x) for x in lines) or 1
    out, t = [], cue.start
    for line in lines:
        d = (cue.end - cue.start) * len(line) / total
        out.append(Cue(t, t + d, line))
        t += d
    return out
