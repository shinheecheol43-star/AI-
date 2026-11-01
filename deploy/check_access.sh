#!/usr/bin/env bash
# 서버에서 필요한 주소에 접속되는지 확인 (자동매매 전에 먼저 실행)
for u in "https://api.bybit.com/v5/market/time" "https://api-testnet.bybit.com/v5/market/time" \
         "https://api.binance.com/api/v3/time" "https://data-api.binance.vision/api/v3/time" \
         "https://data.binance.vision/" "https://api.telegram.org/"; do
  code=$(curl -s -m 15 -o /tmp/access_check.out -w "%{http_code}" "$u")
  printf "%-50s %s %s\n" "$u" "$code" "$(head -c 120 /tmp/access_check.out | tr -d '\n')"
done
