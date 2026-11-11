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

## 어린이 채널 모드 (`--preset kids`)

```bash
python -m ytmaker make "동물들은 어떻게 잘까?" --preset kids --age 4~7 --format shorts
```

키즈 모드에서는 다음이 달라집니다.

- **대본**: 쉬운 낱말, 짧은 문장, 다정한 존댓말("~해요")로 씁니다. 아이가 대답하거나 따라 할 수 있는 질문을 넣고, 핵심 내용은 한 번 더 반복합니다.
- **금지 내용**: 무섭거나 위험한 내용(따라 하면 다칠 수 있는 행동 포함), 구매 유도, 구독·댓글 요청은 넣지 않습니다.
- **목소리**: 조금 느리고(`-8%`) 밝은 톤(`+8Hz`)으로 읽습니다.
- **화면**: 파스텔 색감, 둥근 글꼴(나눔스퀘어라운드가 있으면 사용), 큰 자막을 씁니다.
- **AI 영상 프롬프트**: 귀여운 3D 애니메이션 화풍이 자동으로 붙습니다.
- **업로드 체크리스트**: `metadata.txt`에 아동용 설정 안내가 함께 들어갑니다.

예시 대본은 `examples/kids_animals_sleep/script.json` 입니다.

> **어린이 영상을 올릴 때 꼭 확인할 것**
> - 업로드할 때 시청자층을 **"예, 아동용으로 설정합니다"** 로 선택하세요. 미국 COPPA 규정 때문에 의무이며, 이렇게 설정하면 댓글과 맞춤 광고가 꺼집니다.
> - AI로 만든 사실적인 영상은 "변경된 콘텐츠 또는 합성 콘텐츠" 항목에 표시해야 할 수 있습니다.
> - 비슷한 영상을 대량으로 찍어내면 수익화가 제한될 수 있습니다. 주제, 캐릭터, 구성에 채널만의 개성을 넣으세요.

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

## Higgsfield를 Claude에 연결하기 (커스텀 커넥터)

1. claude.ai → **설정 → 커넥터**(https://claude.ai/customize/connectors) → **커스텀 커넥터 추가**
2. 이름에는 `Higgsfield`, URL에는 `https://mcp.higgsfield.ai/mcp` 를 넣습니다.
3. **연결** 버튼을 누르고 Higgsfield 계정으로 로그인해 권한을 허용합니다.
4. **새 대화나 세션을 시작**합니다. 커넥터는 세션이 시작될 때 불러옵니다.

연결하려면 Higgsfield 유료 구독이 있어야 하고, 영상을 만들 때마다 Higgsfield 크레딧이 차감됩니다.
연결한 뒤에는 Claude에게 "visual_prompts.md의 장면들을 Higgsfield로 만들어 assets에 넣어 줘"라고 맡길 수 있습니다.
