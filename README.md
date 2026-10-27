# SMC 전략 검증 도구

쉽알남 「비밀 생존 전략」 중 1장 오더블럭, 2장 FVG, 5장 거짓 돌파와 함정의 규칙을 코드로 옮겨서
**① 백테스트로 검증하고, ② 실시간 알림을 받고, ③ 차트에서 눈으로 확인**하는 도구입니다.
3장 추세선과 4장 채널은 작도 기준이 더 주관적이라 아직 넣지 않았습니다.

> 알림과 분석만 합니다. 주문은 넣지 않습니다. 투자 판단과 책임은 본인에게 있습니다.

## 설치

```bash
pip install -r requirements.txt     # pandas, numpy, requests
```

## ① 백테스트

```bash
python -m smc.backtest                     # 들어 있는 BTC/USD 1시간봉 (2017-07 ~ 2019-10)
python -m smc.backtest --resample 4h       # 4시간봉으로 묶어서
python -m smc.backtest --source upbit --symbol KRW-BTC --count 5000     # 업비트 최신 데이터
python -m smc.backtest --source binance --symbol ETHUSDT --interval 15m --count 20000
```

결과는 화면 표와 `reports/backtest.json`(거래 하나하나 포함)으로 나옵니다.

### 들어 있는 데이터로 돌린 결과 (BTC/USD 1시간봉, 20,111개 캔들, 수수료 한쪽 0.05%)

| 전략 | 거래 수 | 승률 | 거래당 평균 | 무작위 진입 |
|---|---:|---:|---:|---:|
| 오더블럭 | 1,324 | 28.5% | −0.340R | −0.113R |
| FVG | 1,879 | 48.7% | −0.177R | −0.103R |
| 거짓 돌파 | 1,232 | 43.6% | −0.187R | −0.098R |

- 세 전략 모두 **손실**이었고, 같은 손익비로 아무 때나 들어간 경우(무작위 진입)보다도 나빴습니다.
- 수수료를 0으로 해도 −0.04 ~ −0.08R로 0 근처입니다. 타점 자체의 우위가 보이지 않습니다.
  손절폭이 좁다 보니(오더블럭은 중간값 0.5%) 수수료가 R 기준으로 크게 작용합니다.
- 강의에서 "신뢰도가 오른다"고 한 **유동성 흡수 동반** 조건은 실제로 손실을 줄였지만 플러스로 바꾸진 못했습니다.
  (오더블럭 −0.34R → −0.12R, FVG −0.18R → −0.06R, 표본 100건 남짓)
- 4시간봉 FVG만 +0.03R로 약간 플러스였지만 표본 오차(±0.05R 정도) 안이라 우위로 보기 어렵습니다.
- 한계: 데이터가 2017~2019년 한 종목뿐이고, 강의의 "여러 근거가 겹치는 자리"(예: FVG와 오더블럭이 겹침,
  상위 타임프레임 채널 하단)는 아직 조합해 보지 않았습니다. 업비트·바이낸스 최신 데이터로 꼭 다시 돌려 보세요.

### R이란?

손절폭을 1로 놓은 손익입니다. −1R = 손절 한 번, +2R = 손절폭의 2배 이익.
평균 R이 0보다 커야 장기적으로 이깁니다. 승률이 높아도 평균 R이 마이너스면 잃습니다.

## ② 알림 봇

```bash
python -m smc.alert --source upbit --symbol KRW-BTC --interval 1h
python -m smc.alert --source binance --symbol BTCUSDT --interval 15m --only-sweep --min-rr 1.5
python -m smc.alert --replay --last 200      # 인터넷 없이 과거 데이터로 시험
```

알림 종류: 새 OB·FVG 생성 / 존 첫 도달(진입 타점, 손절·익절·손익비 안내) / 거짓 돌파·함정 후 복귀.

**텔레그램으로 받기**
1. 텔레그램에서 `@BotFather` → `/newbot` → 토큰 받기
2. 만든 봇에게 아무 메시지나 보낸 뒤 `https://api.telegram.org/bot<토큰>/getUpdates` 에서 `chat.id` 확인
3. 환경변수를 설정하고 실행
   ```bash
   export TELEGRAM_BOT_TOKEN=123456:ABC...
   export TELEGRAM_CHAT_ID=987654321
   python -m smc.alert --source upbit --symbol KRW-BTC
   ```

계속 켜 두려면 항상 켜져 있는 PC나 작은 서버(예: 클라우드 무료 VM)에서 `nohup`이나 `tmux`로 실행하세요.

## ②-1 매매 신호 알림 봇 (통합 전략)

`smc.system` 과 같은 규칙·같은 코드로 BTC·ETH 의 스윙 신호(스윙 롱, 숏 S5, 숏 S2)를 알려 줍니다. 주문은 넣지 않습니다.
데이 롱은 15분봉·미국장 시간대 매매라 알림을 보고 따라가기 어려워 기본에서 뺐습니다(`--with-day` 로 포함 가능).

```bash
python -m smc.signal_bot                          # 스윙만, 바이낸스 API 로 1시간마다 확인 (내 PC·서버에서)
python -m smc.signal_bot --balance 5000           # 잔고(USDT)를 넣으면 권장 수량까지 계산
python -m smc.signal_bot --source archive --once  # 공개 저장소 데이터로 한 번 시험 (하루 늦은 데이터)
```

알림 내용
- **진입**: 전략·방향, 근거 5개(✅/❌)와 근거 일치도(10점), 진입가, 손절가(1R), 익절 참고가 1R·2R·3R 과 과거 도달 비율, 이 전략의 과거 승률·평균 R, 권장 수량
- **손절 이동**: 추적 손절이 0.3R 이상 유리하게 움직였을 때 새 손절가
- **청산**: 손절선에 닿아 끝났을 때 결과(R)
- 처음 켤 때 이미 진행 중인 신호는 "신규 진입 비추천"으로 한 번 정리해서 보냅니다.

근거 일치도는 근거 5개 중 신호 방향과 맞는 개수 × 2 입니다. 백테스트에서 이 점수가 높다고 결과가 좋아지지는 않았습니다.
신호의 모양을 보여 주는 값으로만 보세요. 익절 참고가에서 정리하는 것도 백테스트상 추적 손절보다 수익이 작았습니다.

텔레그램 설정은 위 ② 와 같습니다 (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). 잔고는 `BOT_BALANCE_USDT` 환경변수로도 넣을 수 있습니다.
토큰은 환경변수에만 넣고 코드·채팅·깃에 남기지 마세요.

## ③ 차트

```bash
python -m smc.chart                              # → reports/chart.html
python -m smc.chart --resample 4h --out reports/chart_4h.html
python -m smc.chart --source upbit --symbol KRW-BTC --count 2000
```

만들어진 HTML을 브라우저로 열면 OB·FVG 박스, 거짓 돌파 라인, 백테스트 진입·청산 표시와 결과 표가 나옵니다.
드래그로 이동, 휠로 확대, "다음 거래" 버튼으로 거래를 하나씩 넘겨 보며 복기할 수 있습니다.

## 강의안 그대로의 오더블럭 검증

```bash
python -m smc.ob_lecture
```

`smc/ob_lecture.py`는 강의 1장 규칙을 그대로 옮긴 버전입니다. 2캔들·3캔들형, 몸통 존,
꼬리 끝 손절과 봉 마감 손절, 파동 고점 1/2 익절 + 본절 스탑, 반대 OB 출현 시 종료를 반영했습니다.
신뢰도 조건(유동성 흡수, FVG 동반, BOS 동반, 상위 타임프레임 존과 겹침)별로 2017–18년(학습)과
2019년(검증)을 나눠 Bybit 수수료(지정가 0.02%, 시장가 0.055%)로 집계합니다.

## $1,000 잔고 시뮬레이션

```bash
python -m smc.money
```

거래당 잔고의 1%(또는 2%)를 걸고, 손절·익절 규칙대로 복리로 굴렸을 때 잔고가 어떻게 끝나는지 보여 줍니다.
레버리지는 3배를 넘지 않게 수량을 줄이고, 수수료는 Bybit 기준입니다.

## 규칙을 바꿔 보고 싶다면

`smc/detectors.py` 맨 위 `Params`와 `smc/backtest.py`의 `BTConfig`에 기준이 모여 있습니다.
강의에서 "경험에 따른 판단"이라고 한 부분(캔들 크기 배수 등)을 여기 숫자로 정했습니다.

| 설정 | 기본값 | 뜻 |
|---|---|---|
| `ob_body_ratio` | 2.0 | 오더블럭: 둘째 캔들 몸통이 첫 캔들의 몇 배 이상 |
| `fvg_body_ratio` | 2.0 | FVG: 가운데 캔들 몸통이 앞뒤의 몇 배 이상 (강의: 2~3배) |
| `sweep_lookback` | 24 | 유동성 흡수 판정 시 비교할 직전 캔들 수 |
| `pivot_k` | 5 | 스윙 고·저점 판정 폭 (좌우 캔들 수) |
| `reclaim_within` | 5 | 거짓 돌파: 이탈 후 몇 캔들 안에 복귀해야 하나 |
| `max_wait` | 48 | 존 생성 후 이 캔들 수 안에 안 닿으면 포기 |
| `fee` | 0.0005 | 한쪽 수수료 |

## 파일 구성

```
smc/data.py        시세 불러오기 (CSV, 업비트, 바이낸스), 타임프레임 묶기
smc/detectors.py   오더블럭·FVG·스윙·거짓 돌파 탐지
smc/backtest.py    백테스트와 통계, 무작위 진입 대조군
smc/alert.py       알림 봇 (텔레그램)
smc/system.py      BTC·ETH 롱·숏 통합 전략 (백테스트 + 지금 상태)
smc/signal_bot.py  통합 전략 신호 알림 봇
smc/chart.py       차트 HTML 생성 (+ chart_template.html)
tests/             규칙 테스트  →  python -m unittest
data/              BTC/USD 1시간봉 (Coinbase, 출처 CryptoDataDownload)
reports/           생성된 차트
```
