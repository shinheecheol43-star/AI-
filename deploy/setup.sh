#!/usr/bin/env bash
# 우분투 서버(오라클 클라우드 무료 VM 등)에 신호 알림 봇을 설치한다. 저장소 폴더 안에서 실행:
#   bash deploy/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=$(pwd)
ENV_FILE="$HOME/.signal-bot.env"

sudo apt-get update -y
sudo apt-get install -y python3-venv python3-pip git

# 메모리 1GB 서버 대비 스왑 2GB (이미 있으면 건너뜀)
if ! sudo swapon --show | grep -q /swapfile; then
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

# 비밀값 파일: 나만 읽을 수 있게 (토큰은 여기에만 넣는다)
if [ ! -f "$ENV_FILE" ]; then
  cat > "$ENV_FILE" <<'CONF'
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
BOT_BALANCE_USDT=
BYBIT_API_KEY=
BYBIT_API_SECRET=
BYBIT_TESTNET=1
BYBIT_DEMO=0
RISK_SCALE=1
CONF
fi
chmod 600 "$ENV_FILE"

sed -e "s#__REPO__#$REPO#g" -e "s#__USER__#$USER#g" -e "s#__ENV__#$ENV_FILE#g" deploy/signal-bot.service \
  | sudo tee /etc/systemd/system/signal-bot.service >/dev/null
for mode in dry live; do
  args=$([ "$mode" = live ] && echo "--live" || echo "")
  sed -e "s#__REPO__#$REPO#g" -e "s#__USER__#$USER#g" -e "s#__ENV__#$ENV_FILE#g" -e "s#__ARGS__#$args#g" deploy/trader.service \
    | sudo tee /etc/systemd/system/trader-$mode.service >/dev/null
done
sudo systemctl daemon-reload

echo
echo "설치 끝. 다음 순서로 진행하세요."
echo "  1) nano $ENV_FILE        # 텔레그램 토큰·채팅 ID·잔고 입력 후 저장"
echo "  2) .venv/bin/python -m smc.signal_bot --once     # 한 번 시험 (텔레그램으로 시작 메시지가 오는지)"
echo "  3) sudo systemctl enable --now signal-bot        # 계속 켜 두기 (서버 재시작 때도 자동 실행)"
echo "  상태 확인: systemctl status signal-bot   /   로그: journalctl -u signal-bot -f"
echo
echo "자동매매 (순서대로): bash deploy/check_access.sh → sudo systemctl start trader-dry (모의)"
echo "  → BYBIT_TESTNET=1 로 sudo systemctl start trader-live (테스트넷) → 충분히 본 뒤 BYBIT_TESTNET=0 (실전)"
