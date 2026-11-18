import { fetchCandles, subscribeLive } from './data.js';
import { sma, ema, bollinger, rsi, macd, heikinAshi, crosses } from './indicators.js';

const LC = window.LightweightCharts;

const COLORS = {
  up: '#26a69a',
  down: '#ef5350',
  ma20: '#f0b90b',
  ma60: '#ab47bc',
  ema12: '#29b6f6',
  ema26: '#ff7043',
  bb: '#5c6bc0',
  line: '#2962ff',
};

const state = {
  symbol: 'BTCUSDT',
  interval: '1d',
  chartType: 'candle',
  ind: {},
  candles: [],
  source: '',
};

// ---------- 차트 생성 ----------
const baseOptions = {
  autoSize: true,
  layout: { background: { color: '#0f1217' }, textColor: '#b2b5be', fontSize: 11 },
  grid: { vertLines: { color: '#1b1f28' }, horzLines: { color: '#1b1f28' } },
  rightPriceScale: { borderColor: '#2a2f3a', minimumWidth: 80 },
  timeScale: { borderColor: '#2a2f3a', timeVisible: true, secondsVisible: false },
  crosshair: { mode: LC.CrosshairMode.Normal },
  localization: { locale: 'ko-KR' },
};

const panes = {
  main: document.getElementById('mainPane'),
  rsi: document.getElementById('rsiPane'),
  macd: document.getElementById('macdPane'),
};

const charts = {
  main: LC.createChart(panes.main, baseOptions),
  rsi: LC.createChart(panes.rsi, baseOptions),
  macd: LC.createChart(panes.macd, baseOptions),
};

// 세 차트의 시간축(스크롤/줌)을 하나처럼 움직이게 동기화
let syncing = false;
for (const [name, chart] of Object.entries(charts)) {
  chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
    if (syncing || !range) return;
    syncing = true;
    for (const [other, c] of Object.entries(charts)) {
      if (other !== name) c.timeScale().setVisibleLogicalRange(range);
    }
    syncing = false;
  });
}

let series = { main: [], rsi: [], macd: [] };
let priceSeries = null;

function clearSeries() {
  for (const key of Object.keys(series)) {
    for (const s of series[key]) charts[key].removeSeries(s);
    series[key] = [];
  }
  priceSeries = null;
}

function add(chartKey, type, options) {
  const s = charts[chartKey][`add${type}Series`](options);
  series[chartKey].push(s);
  return s;
}

// null 값은 whitespace 데이터로 넣어서 모든 차트의 봉 개수(인덱스)를 맞춘다
function toLine(times, values) {
  return values.map((v, i) => (v === null ? { time: times[i] } : { time: times[i], value: v }));
}

const lineOpts = (color, extra = {}) => ({
  color,
  lineWidth: 1,
  priceLineVisible: false,
  lastValueVisible: false,
  crosshairMarkerVisible: false,
  ...extra,
});

// ---------- 그리기 ----------
function render({ keepRange = false } = {}) {
  const range = keepRange ? charts.main.timeScale().getVisibleLogicalRange() : null;
  const { candles, ind } = state;
  if (!candles.length) return;

  clearSeries();
  const times = candles.map((c) => c.time);
  const closes = candles.map((c) => c.close);

  // 가격 차트
  if (state.chartType === 'line') {
    priceSeries = add('main', 'Line', { color: COLORS.line, lineWidth: 2 });
    priceSeries.setData(candles.map((c) => ({ time: c.time, value: c.close })));
  } else {
    priceSeries = add('main', 'Candlestick', {
      upColor: COLORS.up,
      downColor: COLORS.down,
      borderVisible: false,
      wickUpColor: COLORS.up,
      wickDownColor: COLORS.down,
    });
    priceSeries.setData(state.chartType === 'heikin' ? heikinAshi(candles) : candles);
  }

  // 거래량 (가격 차트 아래쪽 20% 영역)
  if (ind.volume) {
    const vol = add('main', 'Histogram', { priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
    charts.main.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    vol.setData(candles.map((c) => ({
      time: c.time,
      value: c.volume,
      color: c.close >= c.open ? 'rgba(38,166,154,0.4)' : 'rgba(239,83,80,0.4)',
    })));
  }
  charts.main.priceScale('right').applyOptions({ scaleMargins: { top: 0.08, bottom: ind.volume ? 0.22 : 0.05 } });

  // 이동평균선
  const ma20 = sma(closes, 20);
  const ma60 = sma(closes, 60);
  if (ind.ma) {
    add('main', 'Line', lineOpts(COLORS.ma20)).setData(toLine(times, ma20));
    add('main', 'Line', lineOpts(COLORS.ma60)).setData(toLine(times, ma60));
  }
  if (ind.ema) {
    add('main', 'Line', lineOpts(COLORS.ema12)).setData(toLine(times, ema(closes, 12)));
    add('main', 'Line', lineOpts(COLORS.ema26)).setData(toLine(times, ema(closes, 26)));
  }
  if (ind.bb) {
    const b = bollinger(closes, 20, 2);
    add('main', 'Line', lineOpts(COLORS.bb)).setData(toLine(times, b.upper));
    add('main', 'Line', lineOpts(COLORS.bb, { lineStyle: LC.LineStyle.Dashed })).setData(toLine(times, b.mid));
    add('main', 'Line', lineOpts(COLORS.bb)).setData(toLine(times, b.lower));
  }

  // 골든크로스 / 데드크로스 표시 (20일선 vs 60일선)
  if (ind.cross) {
    priceSeries.setMarkers(crosses(ma20, ma60).map(({ index, type }) => (
      type === 'golden'
        ? { time: times[index], position: 'belowBar', color: COLORS.up, shape: 'arrowUp', text: 'GC' }
        : { time: times[index], position: 'aboveBar', color: COLORS.down, shape: 'arrowDown', text: 'DC' }
    )));
  }

  // RSI
  panes.rsi.classList.toggle('hidden', !ind.rsi);
  if (ind.rsi) {
    const r = add('rsi', 'Line', { color: '#7e57c2', lineWidth: 1.5, priceLineVisible: false });
    r.setData(toLine(times, rsi(closes, 14)));
    r.createPriceLine({ price: 70, color: '#ef535080', lineStyle: LC.LineStyle.Dashed, axisLabelVisible: true, title: '' });
    r.createPriceLine({ price: 30, color: '#26a69a80', lineStyle: LC.LineStyle.Dashed, axisLabelVisible: true, title: '' });
    r.applyOptions({ autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) });
  }

  // MACD
  panes.macd.classList.toggle('hidden', !ind.macd);
  if (ind.macd) {
    const m = macd(closes);
    add('macd', 'Histogram', { priceLineVisible: false, lastValueVisible: false }).setData(
      m.hist.map((v, i) => (v === null ? { time: times[i] } : { time: times[i], value: v, color: v >= 0 ? 'rgba(38,166,154,0.6)' : 'rgba(239,83,80,0.6)' })),
    );
    add('macd', 'Line', lineOpts('#2962ff', { lastValueVisible: true })).setData(toLine(times, m.line));
    add('macd', 'Line', lineOpts('#ff6d00', { lastValueVisible: true })).setData(toLine(times, m.signal));
  }

  if (range) {
    charts.main.timeScale().setVisibleLogicalRange(range);
  } else {
    // 처음에는 최근 150개 봉 정도만 보여준다
    const n = candles.length;
    charts.main.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 150), to: n + 3 });
  }
  updateLegend();
}

// ---------- 상단 정보 표시 ----------
const legendEl = document.getElementById('legend');
const fmt = (v) => (v === null || v === undefined ? '-' : v.toLocaleString('ko-KR', { maximumFractionDigits: v < 1 ? 6 : 2 }));

function updateLegend(index) {
  const { candles } = state;
  if (!candles.length) return;
  const i = index ?? candles.length - 1;
  const c = candles[i];
  const prev = candles[i - 1];
  const chg = prev ? ((c.close - prev.close) / prev.close) * 100 : 0;
  const cls = chg >= 0 ? 'up' : 'down';
  const closes = candles.slice(0, i + 1).map((x) => x.close);
  const last = (arr) => arr[arr.length - 1];

  let html = `<b>${state.symbol} · ${state.interval}</b>`;
  html += `<span>시 ${fmt(c.open)}</span><span>고 ${fmt(c.high)}</span><span>저 ${fmt(c.low)}</span>`;
  html += `<span class="${cls}">종 ${fmt(c.close)} (${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%)</span>`;
  if (state.ind.ma) {
    html += `<span style="color:${COLORS.ma20}">MA20 ${fmt(last(sma(closes, 20)))}</span>`;
    html += `<span style="color:${COLORS.ma60}">MA60 ${fmt(last(sma(closes, 60)))}</span>`;
  }
  if (state.ind.rsi) html += `<span style="color:#7e57c2">RSI ${fmt(last(rsi(closes, 14)))}</span>`;
  legendEl.innerHTML = html;
}

charts.main.subscribeCrosshairMove((param) => {
  if (!param.time) return updateLegend();
  const idx = state.candles.findIndex((c) => c.time === param.time);
  updateLegend(idx >= 0 ? idx : undefined);
});

// ---------- 데이터 불러오기 ----------
const statusEl = document.getElementById('status');
let unsubscribe = () => {};
let loadId = 0;

async function load() {
  const id = ++loadId;
  unsubscribe();
  statusEl.className = 'status';
  statusEl.textContent = '불러오는 중…';

  const { source, candles } = await fetchCandles(state.symbol, state.interval);
  if (id !== loadId) return; // 그 사이 다른 종목/주기를 고른 경우
  state.candles = candles;
  state.source = source;
  render();

  if (source === 'live') {
    statusEl.className = 'status live';
    statusEl.textContent = '실시간 (Binance)';
    unsubscribe = subscribeLive(state.symbol, state.interval, onLiveCandle);
  } else {
    statusEl.className = 'status sample';
    statusEl.textContent = '샘플 데이터 (시세 서버에 연결할 수 없음)';
  }
}

let renderQueued = false;
function onLiveCandle(c) {
  const arr = state.candles;
  const lastCandle = arr[arr.length - 1];
  if (lastCandle && lastCandle.time === c.time) arr[arr.length - 1] = c;
  else if (!lastCandle || c.time > lastCandle.time) arr.push(c);
  else return;
  // 틱마다 다시 그리지 않고 프레임당 한 번만 갱신
  if (!renderQueued) {
    renderQueued = true;
    requestAnimationFrame(() => {
      renderQueued = false;
      render({ keepRange: true });
    });
  }
}

// ---------- 화면 조작 ----------
const symbolEl = document.getElementById('symbol');
symbolEl.addEventListener('change', () => {
  const v = symbolEl.value.trim().toUpperCase();
  if (!v || v === state.symbol) return;
  state.symbol = v;
  symbolEl.value = v;
  load();
});
symbolEl.addEventListener('keydown', (e) => { if (e.key === 'Enter') symbolEl.blur(); });

document.querySelectorAll('#intervals button').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('#intervals button').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    state.interval = btn.dataset.interval;
    load();
  });
});

document.getElementById('chartType').addEventListener('change', (e) => {
  state.chartType = e.target.value;
  render({ keepRange: true });
});

document.querySelectorAll('[data-ind]').forEach((box) => {
  state.ind[box.dataset.ind] = box.checked;
  box.addEventListener('change', () => {
    state.ind[box.dataset.ind] = box.checked;
    render({ keepRange: true });
  });
});

load();
