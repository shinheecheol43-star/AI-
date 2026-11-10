"""명령줄 인터페이스.

  python -m ytmaker script "주제"            # AI 대본 생성 → projects/<이름>/script.json
  python -m ytmaker build projects/x/script.json   # 대본 → 영상
  python -m ytmaker make "주제"              # 대본 생성 + 영상 제작을 한 번에
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from .config import FORMATS


def _slug(text: str) -> str:
    s = re.sub(r"[^\w가-힣]+", "_", text).strip("_")
    return s[:40] or "video"


def write_prompts(script: dict, path: str, fmt: str) -> None:
    """Higgsfield 같은 AI 영상/이미지 생성기에 넣을 장면별 프롬프트 목록."""
    ratio = "9:16" if fmt == "shorts" else "16:9"
    lines = [f"# {script.get('title', '')} — 장면별 AI 영상 프롬프트 ({ratio})", "",
             "각 프롬프트로 만든 영상/이미지를 `assets/scene_01.mp4`(또는 .png) 처럼 저장한 뒤",
             "`build`를 다시 실행하면 자동으로 해당 장면 배경으로 들어갑니다.", ""]
    for i, sc in enumerate(script.get("scenes", []), 1):
        lines += [f"## scene_{i:02d} — {sc.get('caption', '')}", "",
                  f"- 내레이션: {sc.get('narration', '')}", "",
                  "```", f"{sc.get('visual_prompt', '')}, aspect ratio {ratio}", "```", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _save_script(script: dict, out: str | None, topic: str, fmt: str) -> str:
    if out is None:
        out = os.path.join("projects", _slug(topic), "script.json")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    prompts = os.path.join(os.path.dirname(os.path.abspath(out)), "visual_prompts.md")
    write_prompts(script, prompts, fmt)
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(out)), "assets"), exist_ok=True)
    print(f"대본 저장: {out}\n장면 프롬프트: {prompts}")
    return out


def _cmd_script(a) -> str:
    from .script_gen import generate_script

    print(f"대본 생성 중… (주제: {a.topic})")
    script = generate_script(a.topic, a.minutes, a.format, a.style)
    return _save_script(script, a.output, a.topic, a.format)


def _cmd_build(a, script_path: str | None = None) -> None:
    from .render import BuildOptions, build_video, load_script

    path = script_path or a.script
    script = load_script(path)
    script_dir = os.path.dirname(os.path.abspath(path))
    out_dir = a.out or os.path.join(script_dir, "output")
    opts = BuildOptions(
        fmt=FORMATS[a.format], tts_engine=a.tts, voice=a.voice, rate=a.rate, font=a.font,
        bgm=a.bgm, bgm_volume=a.bgm_volume, burn_subs=not a.no_burn_subs, keep_work=a.keep_work,
    )
    result = build_video(script, script_dir, out_dir, opts)
    print("\n완성!")
    for k in ("video", "thumbnail", "subtitles", "metadata"):
        print(f"  {k:10s} {result[k]}")
    print(f"  길이       {result['duration']}초")


def _add_build_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--out", help="출력 폴더 (기본: 대본 폴더/output)")
    p.add_argument("--tts", choices=["edge", "silent"], default="edge",
                   help="edge=무료 Edge TTS(인터넷 필요), silent=무음(직접 녹음/테스트)")
    p.add_argument("--voice", default="ko-KR-SunHiNeural",
                   help="Edge TTS 목소리 (예: ko-KR-InJoonNeural, ko-KR-HyunsuMultilingualNeural)")
    p.add_argument("--rate", default="+5%", help="말하기 속도 (예: +10%%, -5%%)")
    p.add_argument("--font", help="한글 폰트 파일 경로 (.ttf/.otf)")
    p.add_argument("--bgm", help="배경음악 파일 (mp3 등, 저작권 무료 음원 권장)")
    p.add_argument("--bgm-volume", type=float, default=0.12)
    p.add_argument("--no-burn-subs", action="store_true",
                   help="자막을 영상에 굽지 않음 (subtitles.srt만 생성 → 유튜브에 따로 업로드)")
    p.add_argument("--keep-work", action="store_true", help="중간 작업 파일 보관")


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="ytmaker", description="AI 유튜브 영상 자동 제작")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def topic_args(p):
        p.add_argument("topic", help="영상 주제")
        p.add_argument("--minutes", type=float, default=None, help="목표 길이(분)")
        p.add_argument("--style", help="톤/스타일 (예: '유쾌하고 빠른 템포', '차분한 다큐')")
        p.add_argument("-o", "--output", help="대본 저장 경로 (기본: projects/<주제>/script.json)")

    for name in ("script", "make"):
        p = sub.add_parser(name, help="AI로 대본 생성" if name == "script" else "대본 생성 + 영상 제작")
        topic_args(p)
        p.add_argument("--format", choices=list(FORMATS), default="long",
                       help="long=가로 16:9, shorts=세로 9:16")
        if name == "make":
            _add_build_args(p)

    p = sub.add_parser("build", help="대본 JSON으로 영상 제작")
    p.add_argument("script", help="script.json 경로")
    p.add_argument("--format", choices=list(FORMATS), default="long")
    _add_build_args(p)

    p = sub.add_parser("prompts", help="대본에서 장면별 AI 영상 프롬프트(visual_prompts.md) 다시 생성")
    p.add_argument("script")
    p.add_argument("--format", choices=list(FORMATS), default="long")

    a = parser.parse_args(argv)
    if getattr(a, "minutes", None) is None and a.cmd in ("script", "make"):
        a.minutes = 0.75 if a.format == "shorts" else 3.0

    try:
        if a.cmd == "script":
            _cmd_script(a)
        elif a.cmd == "make":
            _cmd_build(a, _cmd_script(a))
        elif a.cmd == "build":
            _cmd_build(a)
        elif a.cmd == "prompts":
            from .render import load_script
            out = os.path.join(os.path.dirname(os.path.abspath(a.script)), "visual_prompts.md")
            write_prompts(load_script(a.script), out, a.format)
            print(f"저장: {out}")
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        sys.exit(f"오류: {exc}")
