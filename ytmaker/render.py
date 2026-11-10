"""대본 JSON → 장면 클립 → 최종 MP4 (ffmpeg)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass

from PIL import ImageFont

from . import tts, visuals
from .config import VideoFormat, find_font

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_EXT = (".mp4", ".mov", ".webm", ".mkv")
TAIL_PAD = 0.35  # 장면 사이 숨 고르기(초)


@dataclass
class BuildOptions:
    fmt: VideoFormat
    tts_engine: str = "edge"
    voice: str = tts.DEFAULT_VOICE
    rate: str = "+0%"
    font: str | None = None
    bgm: str | None = None
    bgm_volume: float = 0.12
    burn_subs: bool = True
    keep_work: bool = False


def _run(cmd: list[str], cwd: str | None = None) -> None:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"ffmpeg 실패:\n{' '.join(cmd)}\n{tail}")


def _find_media(scene: dict, idx: int, script_dir: str) -> str | None:
    media = scene.get("media")
    if media:
        path = media if os.path.isabs(media) else os.path.join(script_dir, media)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"장면 {idx + 1}의 media 파일이 없습니다: {path}")
        return path
    # assets/scene_01.mp4 같은 파일을 자동으로 사용 (Higgsfield 등에서 받은 결과물)
    assets = os.path.join(script_dir, "assets")
    for ext in VIDEO_EXT + IMAGE_EXT:
        cand = os.path.join(assets, f"scene_{idx + 1:02d}{ext}")
        if os.path.isfile(cand):
            return cand
    return None


def _cover(w: int, h: int) -> str:
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"


def _scene_clip(bg: str, audio: str, duration: float, out: str, fmt: VideoFormat, idx: int) -> None:
    w, h, fps = fmt.width, fmt.height, fmt.fps
    frames = max(1, int(round(duration * fps)))
    enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    audio_f = f"[1:a]apad,atrim=0:{duration:.3f}[a]"

    if bg.lower().endswith(VIDEO_EXT):
        vf = f"[0:v]{_cover(w, h)},fps={fps},trim=0:{duration:.3f},setpts=PTS-STARTPTS[v]"
        cmd = ["ffmpeg", "-y", "-stream_loop", "-1", "-i", bg, "-i", audio]
    else:
        # Ken Burns: 장면마다 확대/축소와 이동 방향을 바꾼다
        bw, bh = int(w * 1.25) // 2 * 2, int(h * 1.25) // 2 * 2
        zoom_in = idx % 2 == 0
        z = f"1+0.12*on/{frames}" if zoom_in else f"1.12-0.12*on/{frames}"
        pans = ["iw/2-(iw/zoom/2)", "(iw-iw/zoom)*on/{f}", "(iw-iw/zoom)*(1-on/{f})"]
        x = pans[idx % 3].format(f=frames)
        y = "ih/2-(ih/zoom/2)"
        vf = (f"[0:v]{_cover(bw, bh)},zoompan=z='{z}':x='{x}':y='{y}':d=1:s={w}x{h}:fps={fps},"
              f"trim=end_frame={frames},setpts=PTS-STARTPTS[v]")
        cmd = ["ffmpeg", "-y", "-loop", "1", "-framerate", str(fps), "-i", bg, "-i", audio]

    cmd += ["-filter_complex", f"{vf};{audio_f}", "-map", "[v]", "-map", "[a]",
            "-t", f"{duration:.3f}", *enc, out]
    _run(cmd)


def _ts(t: float, sep: str) -> str:
    t = max(0.0, t)
    hh, rem = divmod(t, 3600)
    mm, ss = divmod(rem, 60)
    if sep == ",":  # SRT
        return f"{int(hh):02d}:{int(mm):02d}:{int(ss):02d},{int(round((ss % 1) * 1000)) % 1000:03d}"
    return f"{int(hh)}:{int(mm):02d}:{ss:05.2f}"  # ASS


def _write_srt(cues: list[tts.Cue], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for i, c in enumerate(cues, 1):
            f.write(f"{i}\n{_ts(c.start, ',')} --> {_ts(c.end, ',')}\n{c.text}\n\n")


def _write_ass(cues: list[tts.Cue], path: str, fmt: VideoFormat, family: str) -> None:
    w, h = fmt.width, fmt.height
    size = 78 if fmt.vertical else 62
    margin_v = int(h * 0.27) if fmt.vertical else 64
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{family},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,5,2,2,80,80,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        for c in cues:
            text = c.text.replace("\n", "\\N").replace("{", "(").replace("}", ")")
            f.write(f"Dialogue: 0,{_ts(c.start, '.')},{_ts(c.end, '.')},Default,,0,0,0,,{text}\n")


def build_video(script: dict, script_dir: str, out_dir: str, opts: BuildOptions) -> dict:
    fmt = opts.fmt
    scenes = script.get("scenes") or []
    if not scenes:
        raise ValueError("대본에 scenes가 없습니다.")
    font_path = find_font(opts.font)
    family = ImageFont.truetype(font_path, 20).getname()[0]

    os.makedirs(out_dir, exist_ok=True)
    work = os.path.join(out_dir, "work")
    os.makedirs(work, exist_ok=True)

    max_chars = 16 if fmt.vertical else 30
    all_cues: list[tts.Cue] = []
    clips: list[str] = []
    offset = 0.0
    total = len(scenes)

    for i, scene in enumerate(scenes):
        n = f"{i + 1:02d}"
        narration = scene.get("narration", "").strip()
        print(f"[{n}/{total:02d}] {scene.get('caption') or narration[:20]}")

        audio = os.path.join(work, f"voice_{n}.mp3")
        dur, cues = tts.synthesize(narration or "…", audio, opts.tts_engine, opts.voice, opts.rate)
        clip_dur = dur + TAIL_PAD

        bg = _find_media(scene, i, script_dir)
        if bg is None:
            bg = os.path.join(work, f"card_{n}.png")
            visuals.make_scene_card(bg, scene.get("caption", ""), i, total,
                                    (fmt.width, fmt.height), font_path, fmt.vertical)

        clip = os.path.join(work, f"clip_{n}.mp4")
        _scene_clip(bg, audio, clip_dur, clip, fmt, i)
        clips.append(clip)

        for c in cues:
            for part in tts.chunk_cue(c, max_chars):
                all_cues.append(tts.Cue(part.start + offset, part.end + offset, part.text))
        offset += tts.probe_duration(clip)

    # 1) 장면 이어붙이기
    concat_list = os.path.join(work, "clips.txt")
    with open(concat_list, "w", encoding="utf-8") as f:
        for c in clips:
            f.write(f"file '{os.path.basename(c)}'\n")
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "clips.txt", "-c", "copy",
          "joined.mp4"], cwd=work)

    # 2) 자막 파일
    srt_path = os.path.join(out_dir, "subtitles.srt")
    _write_srt(all_cues, srt_path)
    _write_ass(all_cues, os.path.join(work, "subs.ass"), fmt, family)
    fonts_dir = os.path.join(work, "fonts")
    os.makedirs(fonts_dir, exist_ok=True)
    shutil.copy(font_path, fonts_dir)

    # 3) 자막 굽기 + 배경음악 믹스 (작업 폴더 기준 상대경로로 Windows 경로 문제 회피)
    final = os.path.abspath(os.path.join(out_dir, "video.mp4"))
    cmd = ["ffmpeg", "-y", "-i", "joined.mp4"]
    filters, vmap, amap = [], "0:v", "0:a"
    if opts.burn_subs:
        filters.append("[0:v]ass=subs.ass:fontsdir=fonts[v]")
        vmap = "[v]"
    if opts.bgm:
        cmd += ["-stream_loop", "-1", "-i", os.path.abspath(opts.bgm)]
        fade_st = max(0.0, offset - 2.5)
        filters.append(
            f"[1:a]volume={opts.bgm_volume},atrim=0:{offset:.3f},"
            f"afade=t=in:d=1.5,afade=t=out:st={fade_st:.3f}:d=2.5[bgm];"
            f"[0:a][bgm]amix=inputs=2:duration=first:normalize=0[a]"
        )
        amap = "[a]"
    if filters:
        cmd += ["-filter_complex", ";".join(filters)]
    cmd += ["-map", vmap, "-map", amap]
    cmd += (["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p"]
            if opts.burn_subs else ["-c:v", "copy"])
    cmd += (["-c:a", "aac", "-b:a", "192k"] if opts.bgm else ["-c:a", "copy"])
    cmd += ["-movflags", "+faststart", final]
    _run(cmd, cwd=work)

    # 4) 썸네일 + 업로드용 메타데이터
    thumb = os.path.join(out_dir, "thumbnail.png")
    first_media = _find_media(scenes[0], 0, script_dir)
    thumb_bg = first_media if first_media and first_media.lower().endswith(IMAGE_EXT) else None
    visuals.make_thumbnail(thumb, script.get("thumbnail_text") or script.get("title", ""),
                           (1080, 1920) if fmt.vertical else (1280, 720), font_path, thumb_bg)

    meta_path = os.path.join(out_dir, "metadata.txt")
    tags = script.get("tags") or []
    if fmt.vertical and "#Shorts" not in tags:
        tags = tags + ["#Shorts"]
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write(f"제목:\n{script.get('title', '')}\n\n")
        f.write(f"설명:\n{script.get('description', '')}\n\n")
        f.write(f"태그:\n{', '.join(tags)}\n")

    if not opts.keep_work:
        shutil.rmtree(work, ignore_errors=True)

    return {"video": final, "subtitles": srt_path, "thumbnail": thumb,
            "metadata": meta_path, "duration": round(offset, 2)}


def load_script(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)
