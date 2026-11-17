"""키움 연결 점검 (주문은 안 냄): 토큰 → 잔고 → 예수금 → 현재가 → 오늘 일봉.  python check_api.py"""
from broker import DryBroker, make_broker
from common import config

cfg = config()
br = make_broker(cfg)
if isinstance(br, DryBroker):
    raise SystemExit("MODE=DRY 입니다. config.env 에서 MODE=MOCK 으로 바꾸고 다시 실행하세요.")
print(f"[{br.mode}] {br.host}")
print("1) 토큰:", "OK" if br.token() else "실패")
a = br.account()
print(f"2) 주문가능금액 {a['cash']:,.0f}원 · 추정예탁자산 {a['total']:,.0f}원 · 보유 {a['hold']}")
print("3) 삼성전자 현재가:", br.price("005930"))
print("4) KODEX 200 오늘 일봉:", br.today_bar("069500"), "(장 시작 전이면 None)")
print("\n모두 값이 나오면 연결 OK. 오류가 나면 README '문제 해결' 참고.")
