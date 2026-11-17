"""주문 창구. DRY = 주문 안 냄(기록만) · MOCK = 키움 모의투자 서버 · REAL = 키움 실전 서버.

키움 REST API 값(api-id, 주소, 응답 이름)은 키움 문서(openapi.kiwoom.com)의 값을 옮겨 둔 것이다.
처음 쓰기 전에 check_api.py 로 토큰·잔고·시세가 제대로 오는지 꼭 확인할 것. 다르면 아래 API 표만 고치면 된다.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import requests

HOSTS = {"MOCK": "https://mockapi.kiwoom.com", "REAL": "https://api.kiwoom.com"}
API = {
    "token": ("/oauth2/token", "au10001"),
    "buy": ("/api/dostk/ordr", "kt10000"),
    "sell": ("/api/dostk/ordr", "kt10001"),
    "balance": ("/api/dostk/acnt", "kt00018"),     # 계좌평가잔고내역
    "deposit": ("/api/dostk/acnt", "kt00001"),     # 예수금상세현황
    "quote": ("/api/dostk/stkinfo", "ka10001"),    # 주식기본정보 (현재가)
    "daily": ("/api/dostk/chart", "ka10081"),      # 주식일봉차트
}
# 매매구분(trde_tp): 0 지정가 · 3 시장가 · 81 장마감후 시간외(종가) · 61 장시작전 시간외 · 62 시간외 단일가
TOKEN_FILE = Path(__file__).parent / "token.json"


def num(x) -> float:
    s = str(x).replace(",", "").strip().lstrip("+-")
    return float(s) if s else 0.0


class DryBroker:
    mode = "DRY"

    def __init__(self, cfg):
        self.cfg = cfg

    def account(self):
        return None                      # 잔고는 state.json 의 가상 현금으로 계산

    def price(self, code):
        return None

    def today_bar(self, code):
        return None

    def order(self, side, code, qty, trde_tp):
        return f"DRY-{side}-{code}-{qty}"


class KiwoomBroker:
    def __init__(self, cfg):
        self.mode = cfg["MODE"]
        self.host = HOSTS[self.mode]
        self.key, self.secret = cfg.get("KIWOOM_APPKEY", ""), cfg.get("KIWOOM_SECRETKEY", "")
        if not self.key or not self.secret:
            raise SystemExit("config.env 에 KIWOOM_APPKEY / KIWOOM_SECRETKEY 를 넣어 주세요.")
        if self.mode == "REAL" and cfg.get("REAL_CONFIRM") != "YES":
            raise SystemExit("실전 주문은 config.env 에 REAL_CONFIRM=YES 가 있어야 나갑니다.")
        self._token = None

    # ---------------------------------------------------------- 공통
    def token(self):
        if self._token:
            return self._token
        if TOKEN_FILE.exists():
            t = json.loads(TOKEN_FILE.read_text())
            if t.get("mode") == self.mode and t.get("expires", "") > datetime.now().strftime("%Y%m%d%H%M%S"):
                self._token = t["token"]
                return self._token
        path, _ = API["token"]
        r = requests.post(self.host + path, json={"grant_type": "client_credentials", "appkey": self.key, "secretkey": self.secret},
                          headers={"Content-Type": "application/json;charset=UTF-8"}, timeout=20)
        j = r.json()
        if not j.get("token"):
            raise SystemExit(f"토큰 발급 실패: {j.get('return_msg', j)}")
        self._token = j["token"]
        TOKEN_FILE.write_text(json.dumps({"mode": self.mode, "token": self._token, "expires": j.get("expires_dt", "")}))
        return self._token

    def call(self, name, body, pages=1):
        path, api_id = API[name]
        out, cont, nxt = [], "N", ""
        for _ in range(pages):
            h = {"Content-Type": "application/json;charset=UTF-8", "authorization": f"Bearer {self.token()}",
                 "api-id": api_id, "cont-yn": cont, "next-key": nxt}
            for attempt in range(3):
                r = requests.post(self.host + path, json=body, headers=h, timeout=20)
                if r.status_code == 429:                       # 너무 자주 부름 → 잠깐 쉼
                    time.sleep(1 + attempt)
                    continue
                break
            j = r.json()
            if j.get("return_code", 0) != 0:
                raise RuntimeError(f"{api_id} 실패: {j.get('return_msg')}")
            out.append(j)
            cont, nxt = r.headers.get("cont-yn", "N"), r.headers.get("next-key", "")
            time.sleep(0.25)
            if cont != "Y":
                break
        return out if pages > 1 else out[0]

    # ---------------------------------------------------------- 조회
    def account(self):
        """{'cash': 주문가능금액, 'total': 추정예탁자산, 'hold': {코드: 보유수량}}"""
        b = self.call("balance", {"qry_tp": "1", "dmst_stex_tp": "KRX"})
        d = self.call("deposit", {"qry_tp": "3"})
        hold = {}
        for row in b.get("acnt_evlt_remn_indv_tot", []) or []:
            code = str(row.get("stk_cd", "")).lstrip("A")[:6]
            if code:
                hold[code] = hold.get(code, 0) + int(num(row.get("rmnd_qty", 0)))
        return {"cash": num(d.get("ord_alow_amt", 0)), "total": num(b.get("prsm_dpst_aset_amt", 0)), "hold": hold}

    def price(self, code):
        j = self.call("quote", {"stk_cd": code})
        return num(j.get("cur_prc", 0)) or None

    def today_bar(self, code):
        today = datetime.now().strftime("%Y%m%d")
        j = self.call("daily", {"stk_cd": code, "base_dt": today, "upd_stkpc_tp": "1"})
        rows = j.get("stk_dt_pole_chart_qry", []) or []
        if not rows or rows[0].get("dt") != today:
            return None
        r = rows[0]
        return {"open": num(r["open_pric"]), "high": num(r["high_pric"]), "low": num(r["low_pric"]),
                "close": num(r["cur_prc"]), "volume": num(r.get("trde_qty", 0))}

    # ---------------------------------------------------------- 주문
    def order(self, side, code, qty, trde_tp):
        body = {"dmst_stex_tp": "KRX", "stk_cd": code, "ord_qty": str(int(qty)), "ord_uv": "", "trde_tp": str(trde_tp), "cond_uv": ""}
        j = self.call("buy" if side == "buy" else "sell", body)
        return j.get("ord_no", "?")


def make_broker(cfg):
    mode = cfg.get("MODE", "DRY").upper()
    cfg["MODE"] = mode
    if mode == "DRY":
        return DryBroker(cfg)
    if mode in HOSTS:
        return KiwoomBroker(cfg)
    raise SystemExit(f"MODE 는 DRY · MOCK · REAL 중 하나: {mode}")
