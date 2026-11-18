// 시세 데이터 가져오기
// 기본은 바이낸스 공개 API(키 필요 없음). 접속이 안 되면 샘플 데이터로 대체한다.

const REST_HOSTS = ['https://api.binance.com', 'https://data-api.binance.vision'];

export async function fetchCandles(symbol, interval, limit = 500) {
  for (const host of REST_HOSTS) {
    try {
      const url = `${host}/api/v3/klines?symbol=${symbol}&interval=${interval}&limit=${limit}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const rows = await res.json();
      return { source: 'live', candles: rows.map(parseKline) };
    } catch (e) {
      console.warn(`${host} 접속 실패:`, e);
    }
  }
  return { source: 'sample', candles: sampleCandles(interval, limit) };
}

function parseKline(k) {
  return {
    time: Math.floor(k[0] / 1000),
    open: +k[1],
    high: +k[2],
    low: +k[3],
    close: +k[4],
    volume: +k[5],
  };
}

// 실시간 캔들 업데이트 (웹소켓). 반환값을 호출하면 연결을 끊는다.
export function subscribeLive(symbol, interval, onCandle) {
  let ws;
  let closed = false;
  try {
    ws = new WebSocket(`wss://stream.binance.com:9443/ws/${symbol.toLowerCase()}@kline_${interval}`);
    ws.onmessage = (ev) => {
      const k = JSON.parse(ev.data).k;
      if (!k || closed) return;
      onCandle({
        time: Math.floor(k.t / 1000),
        open: +k.o,
        high: +k.h,
        low: +k.l,
        close: +k.c,
        volume: +k.v,
      });
    };
  } catch (e) {
    console.warn('웹소켓 연결 실패:', e);
  }
  return () => {
    closed = true;
    if (ws) ws.close();
  };
}

const INTERVAL_SEC = { '15m': 900, '1h': 3600, '4h': 14400, '1d': 86400, '1w': 604800 };

// 인터넷 연결 없이도 화면을 확인할 수 있도록 랜덤워크로 만든 가짜 시세
export function sampleCandles(interval, limit = 500) {
  const step = INTERVAL_SEC[interval] || 86400;
  const now = Math.floor(Date.now() / 1000 / step) * step;
  let seed = 42;
  const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  let price = 50000;
  const out = [];
  for (let i = limit - 1; i >= 0; i--) {
    const drift = Math.sin((limit - i) / 60) * 0.002;
    const change = drift + (rand() - 0.5) * 0.04;
    const open = price;
    const close = open * (1 + change);
    const high = Math.max(open, close) * (1 + rand() * 0.015);
    const low = Math.min(open, close) * (1 - rand() * 0.015);
    out.push({ time: now - i * step, open, high, low, close, volume: 500 + rand() * 1500 });
    price = close;
  }
  return out;
}
