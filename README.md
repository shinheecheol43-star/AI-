# 나만의 차트

브라우저에서 바로 여는 트레이딩 차트 웹사이트예요.

- 차트 종류: 캔들 / 헤이켄 아시 / 라인
- 지표: 이동평균선 20·60, EMA 12·26, 볼린저 밴드, 거래량, RSI 14, MACD 12·26·9
- 20·60 이동평균선의 골든크로스(GC)와 데드크로스(DC) 자동 표시
- 바이낸스 공개 시세 실시간 반영 (API 키 필요 없음). 연결이 안 되면 샘플 데이터로 표시

## 실행 방법

ES 모듈을 쓰기 때문에 파일을 더블클릭하지 말고 간단한 로컬 서버로 열어 주세요.

```bash
python3 -m http.server 8000
```

그다음 브라우저에서 http://localhost:8000 을 열면 돼요.

## 구조

- `index.html` – 화면 구성
- `css/style.css` – 스타일
- `js/app.js` – 차트 그리기, 화면 조작
- `js/indicators.js` – 지표 계산 (SMA, EMA, 볼린저, RSI, MACD, 헤이켄 아시, 크로스)
- `js/data.js` – 바이낸스 시세 / 실시간 웹소켓 / 샘플 데이터
- `lib/` – TradingView Lightweight Charts v4.2.0 (Apache-2.0)

## 대화용 분석 도구

```bash
pip install pandas matplotlib koreanize-matplotlib
python3 analysis/analyze.py BTCUSDT 1d --out chart.png
```

지표 요약(JSON)을 출력하고 차트 이미지(`chart.png`)를 저장해요.
