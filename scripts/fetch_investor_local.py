"""[로컬 PC 실행용] 상한가 이벤트 종목의 투자자별(개인·외국인·기관) 순매수 수집

KRX 정보데이터시스템은 로그인이 필요합니다.
1) https://data.krx.co.kr 에서 무료 회원가입
2) 터미널에서 환경 변수 설정 후 실행
   Windows (PowerShell):  $env:KRX_ID="아이디"; $env:KRX_PW="비밀번호"
   macOS/Linux:           export KRX_ID=아이디 KRX_PW=비밀번호
3) pip install pykrx pandas
4) python scripts/fetch_investor_local.py
   -> data/investor_flows.csv 생성. 이 파일을 저장소에 올리거나 대화에 첨부하면 분석을 이어갑니다.

상한가 이벤트(data/limit_up_events.csv)마다 D-10 ~ D+5 구간의 일별 순매수 금액을 받습니다.
종목별로 한 번에 받아 요청 수를 줄이고, 요청 사이에 쉬어 KRX 서버에 부담을 주지 않습니다.
"""
import os
import time

import pandas as pd
from pykrx import stock

ROOT = os.path.join(os.path.dirname(__file__), "..", "data")


def main():
    ev = pd.read_csv(os.path.join(ROOT, "limit_up_events.csv"))
    ev = ev[ev.share_class == "보통주"]
    ev["code"] = ev.symbol.str[:6]
    out_path = os.path.join(ROOT, "investor_flows.csv")
    done = set(pd.read_csv(out_path).code.astype(str).str.zfill(6)) if os.path.exists(out_path) else set()
    codes = sorted(set(ev.code) - done)
    print(f"{len(codes)}개 종목 수집 시작")
    for i, code in enumerate(codes):
        dates = pd.to_datetime(ev[ev.code == code].date)
        start = (dates.min() - pd.Timedelta(days=20)).strftime("%Y%m%d")
        end = (dates.max() + pd.Timedelta(days=10)).strftime("%Y%m%d")
        try:
            df = stock.get_market_trading_value_by_date(start, end, code)  # 순매수 금액(원)
        except Exception as e:  # noqa: BLE001
            print(code, "실패:", e)
            time.sleep(2)
            continue
        if df is None or df.empty:
            continue
        df = df.reset_index().rename(columns={"날짜": "date"})
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df.insert(0, "code", code)
        df.to_csv(out_path, mode="a", header=not os.path.exists(out_path), index=False,
                  encoding="utf-8-sig")
        if i % 50 == 0:
            print(f"{i}/{len(codes)}")
        time.sleep(0.5)
    print("완료:", out_path)


if __name__ == "__main__":
    main()
