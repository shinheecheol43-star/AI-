# AI 유튜브 영상 자동 제작 (ytmaker)

주제 한 줄만 넣으면 **대본 → 음성 → 장면 → 자막 → MP4 영상 + 썸네일 + 업로드용 제목/설명/태그**까지 만들어 주는 도구입니다.

```
주제 ──(Claude)──▶ 대본 script.json ──(Edge TTS)──▶ 내레이션 음성
                         │
                         ├─▶ visual_prompts.md ──(Higgsfield 등)──▶ assets/scene_XX.mp4
                         ▼
              장면 영상 + Ken Burns 효과 + 자막 + 배경음악 ──(ffmpeg)──▶ video.mp4
```

- 일반 영상(가로 16:9, 1920×1080)과 **쇼츠**(세로 9:16, 1080×1920)를 지원합니다.
- 무료 Microsoft Edge 한국어 음성(TTS)으로 내레이션을 만들고, 문장 타이밍에 맞춰 자막을 넣습니다.
- 장면마다 AI 영상이나 이미지를 넣을 수 있습니다. 넣지 않은 장면은 핵심 문구가 들어간 그라데이션 카드로 채웁니다.

## 준비물

1. **Python 3.10 이상**
2. **ffmpeg**
   - Windows: `winget install ffmpeg`
   - macOS: `brew install ffmpeg`
   - Ubuntu: `sudo apt install ffmpeg`
3. 패키지 설치

```bash
pip install -r requirements.txt
```

4. (AI 대본 생성 시) [Claude API 키](https://console.anthropic.com/)

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Windows PowerShell에서는 `$env:ANTHROPIC_API_KEY="sk-ant-..."` 로 설정합니다.

## 사용법

### 한 번에 만들기

```bash
python -m ytmaker make "직장인을 위한 아침 습관 3가지"
```

쇼츠를 만들 때:

```bash
python -m ytmaker make "고양이가 상자를 좋아하는 이유" --format shorts
```

결과물은 `projects/<주제>/output/` 폴더에 저장됩니다.

| 파일 | 내용 |
|---|---|
| `video.mp4` | 완성된 영상 |
| `thumbnail.png` | 썸네일 |
| `subtitles.srt` | 자막 파일 (유튜브에 따로 올릴 수도 있음) |
| `metadata.txt` | 제목, 설명, 태그 |

### 단계별로 만들기 (추천)

**1) 대본 생성**

```bash
python -m ytmaker script "직장인을 위한 아침 습관 3가지" --minutes 3 --style "친근하고 빠른 템포"
```

`projects/<주제>/script.json` 을 열어 내레이션과 문구를 마음대로 고칩니다.

**2) (선택) AI 영상 넣기 — Higgsfield 등**

`projects/<주제>/visual_prompts.md` 에 장면별 영어 프롬프트가 정리되어 있습니다.
Higgsfield 같은 AI 영상/이미지 생성기에서 프롬프트를 넣어 만든 결과물을 다음 이름으로 저장합니다.

```
projects/<주제>/assets/scene_01.mp4
projects/<주제>/assets/scene_02.png
...
```

mp4, mov, webm, png, jpg, webp를 쓸 수 있고, 화면 비율은 자동으로 맞춰 잘립니다.
영상이 장면보다 짧으면 반복 재생되고, 파일이 없는 장면은 자동 카드로 채워집니다.
`script.json` 의 장면에 `"media": "경로"` 를 직접 적어도 됩니다.

**3) 영상 만들기**

```bash
python -m ytmaker build projects/<주제>/script.json --bgm music.mp3
```

### 주요 옵션 (`build` / `make`)

| 옵션 | 설명 |
|---|---|
| `--format long\|shorts` | 가로 16:9 / 세로 9:16 |
| `--voice` | 목소리. `ko-KR-SunHiNeural`(여, 기본), `ko-KR-InJoonNeural`(남), `ko-KR-HyunsuMultilingualNeural`(남) |
| `--rate +10%` | 말하기 속도 |
| `--bgm 파일` / `--bgm-volume 0.12` | 배경음악과 볼륨 |
| `--font 경로` | 한글 폰트 지정. 기본은 맑은 고딕, 애플 SD 고딕, 나눔 폰트를 자동으로 찾습니다. |
| `--no-burn-subs` | 자막을 영상에 굽지 않고 `.srt` 파일만 만듭니다. |
| `--tts silent` | 음성 없이 예상 길이로만 만듭니다. 직접 녹음하거나 미리보기할 때 씁니다. |

API 키 없이도 쓸 수 있습니다. `examples/sample/script.json` 처럼 대본을 직접 쓰고 `build` 하면 됩니다.

```bash
python -m ytmaker build examples/sample/script.json
```

## 대본 형식 (`script.json`)

```json
{
  "title": "영상 제목",
  "description": "유튜브 설명란",
  "tags": ["태그1", "태그2"],
  "thumbnail_text": "썸네일 문구",
  "scenes": [
    {
      "caption": "화면에 크게 띄울 문구",
      "narration": "읽어 줄 내레이션",
      "visual_prompt": "AI 영상 생성기용 영어 프롬프트",
      "media": "assets/my_clip.mp4"
    }
  ]
}
```

`media` 는 선택 항목입니다.

## 참고 사항

- Edge TTS와 Claude API는 인터넷 연결이 필요합니다.
- 배경음악은 [YouTube 오디오 보관함](https://studio.youtube.com/) 같은 저작권 걱정 없는 음원을 쓰세요.
- AI가 쓴 대본의 사실 관계는 올리기 전에 꼭 직접 확인하세요.
- Higgsfield를 Claude와 바로 연결하려면 claude.ai 커넥터 설정에서 Higgsfield MCP를 추가하세요. 그러면 장면 프롬프트로 영상을 생성해 `assets/` 에 넣는 일까지 Claude에게 맡길 수 있습니다.
