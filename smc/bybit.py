"""Bybit v5 USDT 무기한 선물 주문 클라이언트 (자동매매용, 필요한 기능만).

키는 환경변수로만 받는다: BYBIT_API_KEY, BYBIT_API_SECRET (출금 권한 없이, 계약 거래 권한만, 서버 IP 고정 권장)
BYBIT_DEMO=1 이면 데모 트레이딩(api-demo.bybit.com: 실제 시세, 가짜 돈), BYBIT_TESTNET=1 이면 테스트넷(api-testnet.bybit.com).
양방향(헤지) 모드를 쓴다: 롱은 positionIdx 1, 숏은 positionIdx 2 → 같은 코인에 롱·숏을 따로 둘 수 있다.
손절은 거래소에 '조건부 시장가 청산 주문'(Mark Price 기준)으로 걸어 둔다 → 봇이 꺼져 있어도 손절은 거래소가 실행한다.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import time
from decimal import Decimal

import requests

MAINNET, TESTNET, DEMO = "https://api.bybit.com", "https://api-testnet.bybit.com", "https://api-demo.bybit.com"
TAKER = 0.00055
IDX = {1: 1, -1: 2}                                   # 방향 → positionIdx (헤지 모드)
OK_CODES = {0, 110025, 110043}                        # 0 성공, 110025 모드 이미 같음, 110043 레버리지 이미 같음


class BybitError(RuntimeError):
    pass


class Bybit:
    def __init__(self, key: str | None = None, secret: str | None = None, testnet: bool | None = None,
                 account_type: str | None = None, recv_window: int = 5000):
        self.key = key or os.environ.get("BYBIT_API_KEY", "")
        self.secret = secret or os.environ.get("BYBIT_API_SECRET", "")
        testnet = os.environ.get("BYBIT_TESTNET", "0") == "1" if testnet is None else testnet
        demo = os.environ.get("BYBIT_DEMO", "0") == "1"
        self.base = DEMO if demo else TESTNET if testnet else MAINNET
        self.mode = "데모" if demo else "테스트넷" if testnet else "실전"
        self.account_type = account_type or os.environ.get("BYBIT_ACCOUNT_TYPE", "UNIFIED")
        self.recv = str(recv_window)
        self._info: dict[str, dict] = {}

    # ---------------------------------------------------------------- 요청
    def _call(self, method: str, path: str, params: dict | None = None, auth: bool = True) -> dict:
        params = params or {}
        ts = str(int(time.time() * 1000))
        if method == "GET":
            payload = "&".join(f"{k}={v}" for k, v in params.items())
            url, body = f"{self.base}{path}" + (f"?{payload}" if payload else ""), None
        else:
            payload = json.dumps(params, separators=(",", ":"))
            url, body = f"{self.base}{path}", payload
        headers = {"Content-Type": "application/json"}
        if auth:
            if not (self.key and self.secret):
                raise BybitError("BYBIT_API_KEY / BYBIT_API_SECRET 환경변수가 없습니다")
            sign = hmac.new(self.secret.encode(), (ts + self.key + self.recv + payload).encode(), hashlib.sha256).hexdigest()
            headers.update({"X-BAPI-API-KEY": self.key, "X-BAPI-TIMESTAMP": ts, "X-BAPI-RECV-WINDOW": self.recv, "X-BAPI-SIGN": sign})
        r = requests.request(method, url, data=body, headers=headers, timeout=15)
        r.raise_for_status()
        j = r.json()
        if j.get("retCode") not in OK_CODES:
            raise BybitError(f"{path} {j.get('retCode')}: {j.get('retMsg')}")
        return j.get("result") or {}

    # ---------------------------------------------------------------- 시세·계정
    def server_time(self) -> int:
        return int(self._call("GET", "/v5/market/time", auth=False)["timeSecond"])

    def last_price(self, symbol: str) -> float:
        return float(self._call("GET", "/v5/market/tickers", {"category": "linear", "symbol": symbol}, auth=False)["list"][0]["lastPrice"])

    def instrument(self, symbol: str) -> dict:
        if symbol not in self._info:
            it = self._call("GET", "/v5/market/instruments-info", {"category": "linear", "symbol": symbol}, auth=False)["list"][0]
            self._info[symbol] = {"qty_step": float(it["lotSizeFilter"]["qtyStep"]), "min_qty": float(it["lotSizeFilter"]["minOrderQty"]),
                                  "tick": float(it["priceFilter"]["tickSize"])}
        return self._info[symbol]

    def equity(self) -> float:
        acc = self._call("GET", "/v5/account/wallet-balance", {"accountType": self.account_type})["list"][0]
        return float(acc.get("totalEquity") or acc.get("totalWalletBalance") or 0)

    def position_size(self, symbol: str, side: int) -> float:
        for p in self._call("GET", "/v5/position/list", {"category": "linear", "symbol": symbol})["list"]:
            if int(p.get("positionIdx", 0)) == IDX[side]:
                return float(p.get("size") or 0)
        return 0.0

    # ---------------------------------------------------------------- 준비
    def setup(self, symbol: str, leverage: int = 3):
        self._call("POST", "/v5/position/switch-mode", {"category": "linear", "symbol": symbol, "mode": 3})
        self._call("POST", "/v5/position/set-leverage", {"category": "linear", "symbol": symbol,
                                                          "buyLeverage": str(leverage), "sellLeverage": str(leverage)})

    # ---------------------------------------------------------------- 주문
    def round_qty(self, symbol: str, qty: float) -> float:
        step = self.instrument(symbol)["qty_step"]
        return math.floor(qty / step + 1e-9) * step

    def _fmt(self, x: float, step: float) -> str:
        d = Decimal(str(step)).normalize()
        places = max(0, -d.as_tuple().exponent)
        return f"{x:.{places}f}"

    def market(self, symbol: str, side: int, qty: float, reduce_only: bool = False, pos_side: int | None = None) -> str:
        """side: 1 매수, -1 매도. pos_side: 어느 포지션(롱 1 / 숏 −1)에 대한 주문인지 (청산이면 반대 방향 매매)."""
        info = self.instrument(symbol)
        res = self._call("POST", "/v5/order/create", {
            "category": "linear", "symbol": symbol, "side": "Buy" if side > 0 else "Sell", "orderType": "Market",
            "qty": self._fmt(qty, info["qty_step"]), "positionIdx": IDX[pos_side if pos_side else side], "reduceOnly": reduce_only})
        return res["orderId"]

    def stop(self, symbol: str, pos_side: int, qty: float, trigger: float) -> str:
        """포지션(pos_side) 손절용 조건부 시장가 청산 주문. Mark Price 가 trigger 를 넘으면 실행."""
        info = self.instrument(symbol)
        res = self._call("POST", "/v5/order/create", {
            "category": "linear", "symbol": symbol, "side": "Sell" if pos_side > 0 else "Buy", "orderType": "Market",
            "qty": self._fmt(qty, info["qty_step"]), "triggerPrice": self._fmt(trigger, info["tick"]),
            "triggerDirection": 2 if pos_side > 0 else 1, "triggerBy": "MarkPrice", "reduceOnly": True, "closeOnTrigger": True,
            "positionIdx": IDX[pos_side]})
        return res["orderId"]

    def amend_stop(self, symbol: str, order_id: str, trigger: float):
        self._call("POST", "/v5/order/amend", {"category": "linear", "symbol": symbol, "orderId": order_id,
                                               "triggerPrice": self._fmt(trigger, self.instrument(symbol)["tick"])})

    def cancel(self, symbol: str, order_id: str):
        try:
            self._call("POST", "/v5/order/cancel", {"category": "linear", "symbol": symbol, "orderId": order_id})
        except BybitError:
            pass                                          # 이미 체결·취소된 주문

    def order_status(self, symbol: str, order_id: str) -> tuple[str, float]:
        """(상태, 평균 체결가). 상태: Untriggered, Triggered, New, Filled, Cancelled, Deactivated, Rejected ..."""
        for path in ("/v5/order/realtime", "/v5/order/history"):
            lst = self._call("GET", path, {"category": "linear", "symbol": symbol, "orderId": order_id}).get("list", [])
            if lst:
                o = lst[0]
                return o.get("orderStatus", ""), float(o.get("avgPrice") or 0)
        return "Unknown", 0.0


class DryRun:
    """주문을 보내지 않는 가짜 거래소 (모의 실행·시험용). 가격은 밖에서 넣어 준다.
    손절 주문은 check_triggers 에 넣어 준 가격 범위(최근 1시간봉 고가·저가)로 실행 여부를 정하고,
    체결마다 수수료(0.055%)와 손익을 잔고에 반영한다. dump/load 로 상태를 저장해 재시작해도 이어진다."""

    mode = "모의 실행"

    def __init__(self, equity: float = 1000.0):
        self.eq, self.prices, self.orders, self.positions, self.avg, self.log, self._n = equity, {}, {}, {}, {}, [], 0
        self.steps = {"BTCUSDT": (0.001, 0.001, 0.1), "ETHUSDT": (0.01, 0.01, 0.01)}

    def dump(self) -> dict:
        return {"eq": self.eq, "orders": self.orders, "n": self._n,
                "positions": [[s, d, q] for (s, d), q in self.positions.items()],
                "avg": [[s, d, p] for (s, d), p in self.avg.items()]}

    def load(self, d: dict):
        self.eq, self.orders, self._n = d["eq"], d["orders"], d["n"]
        self.positions = {(s, dd): q for s, dd, q in d["positions"]}
        self.avg = {(s, dd): p for s, dd, p in d["avg"]}

    def _id(self):
        self._n += 1
        return f"dry-{self._n}"

    def last_price(self, symbol):
        return self.prices[symbol]

    def instrument(self, symbol):
        s, m, t = self.steps.get(symbol, (0.001, 0.001, 0.01))
        return {"qty_step": s, "min_qty": m, "tick": t}

    def equity(self):
        return self.eq

    def position_size(self, symbol, side):
        return self.positions.get((symbol, side), 0.0)

    def setup(self, symbol, leverage=3):
        self.log.append(("setup", symbol, leverage))

    def round_qty(self, symbol, qty):
        step = self.instrument(symbol)["qty_step"]
        return math.floor(qty / step + 1e-9) * step

    def _fill(self, symbol, pos_side, qty, px, reduce):
        key = (symbol, pos_side)
        held = self.positions.get(key, 0.0)
        self.eq -= qty * px * TAKER
        if reduce:
            qty = min(qty, held)
            self.eq += pos_side * (px - self.avg.get(key, px)) * qty
            self.positions[key] = round(held - qty, 10)
        else:
            self.avg[key] = (self.avg.get(key, 0.0) * held + px * qty) / (held + qty)
            self.positions[key] = round(held + qty, 10)

    def market(self, symbol, side, qty, reduce_only=False, pos_side=None):
        ps = pos_side if pos_side else side
        self._fill(symbol, ps, qty, self.prices.get(symbol, 0.0), reduce_only)
        self.log.append(("market", symbol, side, qty, reduce_only))
        return self._id()

    def stop(self, symbol, pos_side, qty, trigger):
        oid = self._id()
        self.orders[oid] = {"symbol": symbol, "side": pos_side, "qty": qty, "trigger": trigger, "status": "Untriggered", "fill": 0.0}
        self.log.append(("stop", symbol, pos_side, qty, trigger))
        return oid

    def amend_stop(self, symbol, order_id, trigger):
        self.orders[order_id]["trigger"] = trigger
        self.log.append(("amend", symbol, order_id, trigger))

    def cancel(self, symbol, order_id):
        if order_id in self.orders and self.orders[order_id]["status"] == "Untriggered":
            self.orders[order_id]["status"] = "Cancelled"
        self.log.append(("cancel", symbol, order_id))

    def order_status(self, symbol, order_id):
        o = self.orders.get(order_id)
        return (o["status"], o["fill"]) if o else ("Unknown", 0.0)

    def check_triggers(self, ranges: dict):
        """ranges: {심볼: (저가, 고가)} 지난 확인 이후 가격 범위. 손절가에 닿은 주문을 손절가에 체결."""
        for oid, o in self.orders.items():
            if o["status"] != "Untriggered" or o["symbol"] not in ranges:
                continue
            lo, hi = ranges[o["symbol"]]
            if (lo <= o["trigger"]) if o["side"] > 0 else (hi >= o["trigger"]):
                self.fill_stop(oid)

    def fill_stop(self, order_id):
        o = self.orders[order_id]
        o["status"], o["fill"] = "Filled", o["trigger"]
        self._fill(o["symbol"], o["side"], o["qty"], o["trigger"], True)
