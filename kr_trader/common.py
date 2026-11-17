"""설정·상태 파일·알림."""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).parent
STATE = HERE / "state.json"
LOG = HERE / "logs"


def config() -> dict:
    f = HERE / "config.env"
    if not f.exists():
        raise SystemExit("config.env 가 없습니다. config.example.env 를 복사해 config.env 로 이름을 바꾸고 채워 주세요.")
    cfg = {}
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


@contextmanager
def lock(timeout=120):
    f = HERE / "state.lock"
    t0 = time.time()
    while True:
        try:
            fd = os.open(f, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.time() - f.stat().st_mtime > 600:      # 10분 넘은 잠금은 죽은 것
                f.unlink(missing_ok=True)
            elif time.time() - t0 > timeout:
                raise SystemExit("state.lock 이 풀리지 않습니다 (다른 프로그램이 돌고 있나요?)")
            time.sleep(1)
    try:
        yield
    finally:
        os.close(fd)
        f.unlink(missing_ok=True)


def load_state(cfg) -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"mode": cfg.get("MODE", "DRY"), "cash": float(cfg.get("START_CAPITAL", 10_000_000)),
            "start_capital": float(cfg.get("START_CAPITAL", 10_000_000)), "positions": [], "last_exit": {}, "last_run": ""}


def save_state(st: dict):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(STATE)


def log(msg: str, cfg: dict | None = None, notify=False):
    LOG.mkdir(exist_ok=True)
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    with open(LOG / f"{datetime.now():%Y-%m}.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")
    if notify and cfg and cfg.get("TELEGRAM_TOKEN") and cfg.get("TELEGRAM_CHAT_ID"):
        try:
            requests.post(f"https://api.telegram.org/bot{cfg['TELEGRAM_TOKEN']}/sendMessage",
                          json={"chat_id": cfg["TELEGRAM_CHAT_ID"], "text": msg}, timeout=10)
        except Exception:
            pass


def trade_record(row: dict):
    import csv
    f = HERE / "trades.csv"
    new = not f.exists()
    with open(f, "a", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["date", "side", "kind", "code", "name", "qty", "price", "amount", "why", "order_no"])
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in w.fieldnames})
