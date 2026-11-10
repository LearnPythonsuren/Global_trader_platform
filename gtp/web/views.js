// The dashboard views. Each exports render(root, ctx); ctx is built in app.js.
import {
  el, esc, num, pct, signed, cls, arrow, money, icon,
  table, changePill, symCell, stat, fill, signalRow, articleRow, sentimentBar, labelledBar, spark, realizeSparks,
} from './ui.js';
import { Chart, sparkline, donut, palette } from './charts.js';
import { api, state, store, toast, debounce, timeAgo, num as _n } from './core.js';

const enc = encodeURIComponent;
const CSV = (a) => a.map(enc).join(',');

function viewHeader(title, sub, actions) {
  return el('div', { class: 'vh' }, [
    el('div', {}, [el('h1', {}, title), sub ? el('div', { class: 'sub' }, sub) : null]),
    actions ? el('div', { class: 'vh-actions' }, actions) : null,
  ]);
}

// ============================================================ OVERVIEW =======
export async function overview(root, ctx) {
  root.append(viewHeader('Terminal', 'Live market overview — indices, your watchlist and the news that moves them',
    [el('button', { class: 'btn', onclick: () => ctx.editWatchlist() }, [rawIcon('star'), 'Watchlist'])]));
  const idxRow = el('div', { class: 'grid cols-4', style: 'margin-bottom:14px' });
  const mainGrid = el('div', { class: 'grid cols-3' });
  const wlCard = el('div', { class: 'card pad0 span-2' });
  const moodCard = el('div', { class: 'card' });
  const moversCard = el('div', { class: 'card span-2' });
  const newsCard = el('div', { class: 'card' });
  mainGrid.append(wlCard, moodCard, moversCard, newsCard);
  root.append(idxRow, mainGrid);

  const watchlist = ctx.watchlist();
  const pulse = await api(`/v1/market/pulse?watchlist=${CSV(watchlist)}`).catch((e) => ({ error: e }));
  if (pulse.error) { idxRow.innerHTML = ''; root.append(el('div', { class: 'empty down' }, pulse.error.detail || 'Failed to load market pulse')); return; }
  const S = pulse.sections;

  // index cards with sparklines
  const indices = (S.indices?.data || []);
  const idxSpark = await api(`/v1/sparklines?symbols=${CSV(indices.map((i) => i.symbol))}&exchange=${enc(state.meta.index_exchange)}&bars=30`).catch(() => ({}));
  idxRow.innerHTML = '';
  for (const q of indices) {
    const series = idxSpark[q.symbol];
    const card = el('div', { class: 'idx-card' }, [
      el('div', { class: 'idx-name' }, q.symbol),
      el('div', { class: 'idx-val' }, num(q.ltp)),
      el('div', { class: `idx-chg ${cls(q.change_pct)}` }, `${arrow(q.change_pct)} ${signed(q.change)} (${pct(q.change_pct)})`),
      series ? (() => { const c = spark(series); c.className = 'spark idx-spark'; return c; })() : null,
    ]);
    idxRow.append(card);
  }
  realizeSparks(idxRow);

  // watchlist table
  const wl = S.watchlist?.data || [];
  const wlNews = Object.fromEntries((S.watchlist_news?.data || []).map((r) => [r.symbol, r]));
  const wlSpark = await api(`/v1/sparklines?symbols=${CSV(wl.map((q) => q.symbol))}&bars=30`).catch(() => ({}));
  wlCard.append(el('div', { class: 'card-head', style: 'padding:16px 16px 0' }, [el('h3', {}, ['Watchlist', el('span', { class: 'muted' }, `· ${wl.length}`)])]));
  wlCard.append(table([
    { head: 'Symbol', cell: (q) => symCell(q.symbol) },
    { head: '30d', cell: (q) => (wlSpark[q.symbol] ? spark(wlSpark[q.symbol]) : '–') },
    { head: 'LTP', cell: (q) => el('span', { class: 'mono' }, num(q.ltp)) },
    { head: 'Chg%', cell: (q) => changePill(q.change_pct) },
    { head: 'Volume', cell: (q) => el('span', { class: 'mono mini muted' }, q.volume ? _n(q.volume, 0) : '–') },
    { head: 'News', cell: (q) => (wlNews[q.symbol] ? el('span', { class: `chip ${wlNews[q.symbol].label.includes('bull') ? 'pos' : wlNews[q.symbol].label.includes('bear') ? 'neg' : 'neu'}` }, wlNews[q.symbol].label) : el('span', { class: 'faint' }, '–')) },
  ], wl, { onRow: (q) => ctx.openSymbol(q.symbol) }));
  realizeSparks(wlCard);

  // market mood
  const mood = S.market_sentiment?.data;
  moodCard.append(el('h3', {}, 'Market mood'));
  moodCard.append(mood ? sentimentBar(mood) : el('div', { class: 'empty' }, 'No news'));
  const breadth = computeBreadth(wl);
  moodCard.append(el('div', { style: 'margin-top:16px' }, [
    el('div', { class: 'row spread mini muted', style: 'margin-bottom:6px' }, [el('span', {}, `${breadth.adv} advancing`), el('span', {}, `${breadth.dec} declining`)]),
    el('div', { class: 'row', style: 'height:8px;border-radius:5px;overflow:hidden;gap:0' }, [
      breadth.adv ? el('span', { style: `flex:${breadth.adv};background:var(--up)` }) : null,
      breadth.dec ? el('span', { style: `flex:${breadth.dec};background:var(--down)` }) : null,
    ]),
  ]));

  // movers
  const movers = S.movers?.data;
  moversCard.append(el('h3', {}, 'Top movers in your watchlist'));
  if (movers) {
    const grid = el('div', { class: 'grid cols-2' });
    grid.append(moverList('Gainers', movers.gainers, ctx), moverList('Losers', movers.losers, ctx));
    moversCard.append(grid);
  } else moversCard.append(el('div', { class: 'empty' }, 'Add symbols to your watchlist'));

  // news
  newsCard.append(el('h3', {}, ['Market news', el('span', { class: 'muted' }, mood ? `· ${mood.label}` : '')]));
  const news = S.general_news?.data || [];
  newsCard.append(el('div', { style: 'max-height:420px;overflow-y:auto' }, news.slice(0, 8).map((a) => articleRow(a))));
}

function moverList(title, rows, ctx) {
  return el('div', {}, [
    el('div', { class: 'faint mini', style: 'text-transform:uppercase;letter-spacing:.4px;margin-bottom:6px' }, title),
    ...(rows || []).map((q) => el('div', { class: 'row spread', style: 'padding:6px 0;border-bottom:1px solid var(--border-soft);cursor:pointer', onclick: () => ctx.openSymbol(q.symbol) }, [
      el('b', { class: 'mono' }, q.symbol),
      el('div', { class: 'row', style: 'gap:10px' }, [el('span', { class: 'mono mini muted' }, num(q.ltp)), changePill(q.change_pct)]),
    ])),
  ]);
}
function computeBreadth(quotes) {
  let adv = 0, dec = 0;
  for (const q of quotes) { if (q.change_pct > 0) adv++; else if (q.change_pct < 0) dec++; }
  return { adv, dec };
}

// ============================================================ MARKETS ========
export async function markets(root, ctx) {
  root.append(viewHeader('Markets', 'Every stock in the universe, sized by market value and coloured by today’s move'));
  const statRow = el('div', { class: 'grid cols-4', style: 'margin-bottom:14px' });
  const heatCard = el('div', { class: 'card' });
  const botGrid = el('div', { class: 'grid cols-2', style: 'margin-top:14px' });
  root.append(statRow, heatCard, botGrid);
  heatCard.innerHTML = '<div class="empty"><span class="spinner"></span> building market map…</div>';

  const h = await api('/v1/market/heatmap').catch((e) => ({ error: e }));
  if (h.error) { heatCard.innerHTML = ''; heatCard.append(el('div', { class: 'empty down' }, h.error.detail || 'Failed')); return; }

  const b = h.breadth;
  statRow.append(
    stat('Advancing', String(b.advancers), `${Math.round(b.advancers / (b.advancers + b.decliners + b.unchanged) * 100)}% of ${h.stocks.length}`, 'up'),
    stat('Declining', String(b.decliners), null, 'down'),
    stat('Top sector', h.sectors[0]?.sector || '–', h.sectors[0] ? pct(h.sectors[0].change_pct) : null, h.sectors[0] && cls(h.sectors[0].change_pct)),
    stat('Weakest sector', h.sectors[h.sectors.length - 1]?.sector || '–', h.sectors.length ? pct(h.sectors[h.sectors.length - 1].change_pct) : null, h.sectors.length && cls(h.sectors[h.sectors.length - 1].change_pct)),
  );

  // heatmap grouped by sector, cells sized by sqrt(market cap)
  heatCard.innerHTML = '';
  heatCard.append(el('div', { class: 'card-head' }, [el('h3', {}, 'Market map'), el('span', { class: 'mini muted' }, 'cell size ∝ market cap · colour = day change')]));
  const bySector = {};
  for (const s of h.stocks) (bySector[s.sector] ||= []).push(s);
  const sectorsOrder = h.sectors.map((s) => s.sector).filter((n) => bySector[n]);
  const heat = el('div', { class: 'heat' });
  for (const name of sectorsOrder) {
    const members = bySector[name].sort((a, b2) => (b2.market_cap || 0) - (a.market_cap || 0));
    const cells = el('div', { class: 'heat-cells' });
    for (const s of members) {
      const size = Math.max(58, Math.min(150, 46 + Math.sqrt((s.market_cap || 0) / 1e4) * 4));
      cells.append(el('div', {
        class: 'heat-cell', title: `${s.name || s.symbol} · ${pct(s.change_pct)}`,
        style: `flex:1 1 ${size}px;max-width:${size * 1.5}px;background:${heatColor(s.change_pct)}`,
        onclick: () => ctx.openSymbol(s.symbol),
      }, [el('b', {}, s.symbol), el('span', { class: 'hc-chg' }, pct(s.change_pct))]));
    }
    heat.append(el('div', { class: 'heat-sector', style: 'flex:1 1 100%' }, [el('div', { class: 'heat-sector-label' }, name), cells]));
  }
  heatCard.append(heat);

  // sector performance + leaders/laggards
  const sectorCard = el('div', { class: 'card' });
  sectorCard.append(el('h3', {}, 'Sector performance'));
  const maxAbs = Math.max(...h.sectors.map((s) => Math.abs(s.change_pct || 0)), 0.1);
  for (const s of h.sectors) {
    const wpct = (Math.abs(s.change_pct || 0) / maxAbs) * 100;
    sectorCard.append(el('div', { style: 'display:grid;grid-template-columns:minmax(120px,180px) 1fr auto;gap:10px;align-items:center;margin-bottom:8px' }, [
      el('span', { class: 'mini', style: 'white-space:nowrap;overflow:hidden;text-overflow:ellipsis' }, s.sector),
      el('div', { class: 'hbar-track' }, el('div', { class: 'hbar', style: `width:${Math.max(2, wpct)}%;background:${s.change_pct >= 0 ? 'var(--up)' : 'var(--down)'}` })),
      el('span', { class: `mono mini ${cls(s.change_pct)}`, style: 'min-width:56px;text-align:right' }, pct(s.change_pct)),
    ]));
  }
  const leadCard = el('div', { class: 'card' });
  leadCard.append(el('h3', {}, 'Leaders & laggards'));
  const lg = el('div', { class: 'grid cols-2' });
  lg.append(moverList('Top gainers', h.gainers, ctx), moverList('Top losers', h.losers, ctx));
  leadCard.append(lg);
  botGrid.append(sectorCard, leadCard);
}
function heatColor(v) {
  const t = Math.max(-1, Math.min(1, (v || 0) / 3));
  if (t >= 0) return `color-mix(in srgb, var(--up) ${18 + t * 62}%, var(--panel-2))`;
  return `color-mix(in srgb, var(--down) ${18 + -t * 62}%, var(--panel-2))`;
}

// ============================================================ CHART ==========
const TIMEFRAMES = [
  ['1m', { periodicity: 'MINUTE', period: 1, bars: 375 }], ['5m', { periodicity: 'MINUTE', period: 5, bars: 375 }],
  ['15m', { periodicity: 'MINUTE', period: 15, bars: 400 }], ['1H', { periodicity: 'HOUR', period: 1, bars: 300 }],
  ['1D', { periodicity: 'DAY', period: 1, bars: 260 }], ['1W', { periodicity: 'WEEK', period: 1, bars: 200 }],
  ['1M', { periodicity: 'MONTH', period: 1, bars: 120 }],
];
export async function chartView(root, ctx) {
  const symbol = (ctx.params.symbol || store.get('gtp.lastSymbol') || 'RELIANCE').toUpperCase();
  let tf = store.get('gtp.tf', '1D');
  const indicators = store.get('gtp.indicators', { sma20: true, sma50: true, boll: false, rsi: false, macd: false });

  const symInput = el('input', { class: 'input mono', style: 'width:150px', value: symbol });
  const tfSeg = el('div', { class: 'seg' }, TIMEFRAMES.map(([k]) =>
    el('button', { class: k === tf ? 'active' : '', onclick: () => { tf = k; store.set('gtp.tf', k); paint(); syncSeg(); } }, k)));
  const syncSeg = () => [...tfSeg.children].forEach((b, i) => b.classList.toggle('active', TIMEFRAMES[i][0] === tf));
  const indBar = el('div', { class: 'row wrap', style: 'gap:6px' }, [
    indToggle('SMA 20', 'sma20'), indToggle('SMA 50', 'sma50'), indToggle('Bollinger', 'boll'),
    indToggle('RSI', 'rsi'), indToggle('MACD', 'macd'),
  ]);
  function indToggle(label, key) {
    const b = el('button', { class: `btn ghost ${indicators[key] ? 'primary' : ''}`, style: 'height:30px;padding:0 11px;font-size:12px',
      onclick: () => { indicators[key] = !indicators[key]; store.set('gtp.indicators', indicators); b.classList.toggle('primary', indicators[key]); paint(); } }, label);
    return b;
  }
  root.append(viewHeader('Chart', null, [
    el('form', { class: 'row', onsubmit: (e) => { e.preventDefault(); ctx.navigate('chart', { symbol: symInput.value.trim().toUpperCase() }); } }, [
      symInput, el('button', { class: 'btn', type: 'submit' }, rawIcon('search')),
    ]),
    el('button', { class: 'btn', onclick: () => ctx.openSymbol(symInput.value.trim().toUpperCase()) }, '360° view'),
  ]));

  const head = el('div', { class: 'card-head' }, [el('div', { id: 'chart-title', class: 'row', style: 'gap:12px' }), tfSeg]);
  const readout = el('div', { class: 'chart-readout', hidden: true });
  const canvas = el('canvas', { style: 'height:460px' });
  const chartCard = el('div', { class: 'card' }, [head, el('div', { style: 'margin-bottom:10px' }, indBar), el('div', { class: 'chart-shell' }, [readout, canvas])]);
  const techCard = el('div', { class: 'card' });
  root.append(chartCard, el('div', { class: 'grid', style: 'margin-top:14px' }, techCard));

  const chart = new Chart(canvas);
  ctx.onLeave(() => chart.destroy());
  chart.onHover = (c) => {
    if (!c) { readout.hidden = true; return; }
    readout.hidden = false;
    readout.innerHTML = `O <b>${num(c.o)}</b> H <b>${num(c.h)}</b> L <b>${num(c.l)}</b> C <b class="${cls(c.c - c.o)}">${num(c.c)}</b>${c.v ? ` V <b>${_n(c.v, 0)}</b>` : ''}`;
  };

  async function paint() {
    store.set('gtp.lastSymbol', symInput.value.trim().toUpperCase());
    const sym = symInput.value.trim().toUpperCase();
    const want = [];
    if (indicators.sma20) want.push('sma:20'); if (indicators.sma50) want.push('sma:50');
    if (indicators.boll) want.push('bollinger:20'); if (indicators.rsi) want.push('rsi:14'); if (indicators.macd) want.push('macd');
    const opt = Object.fromEntries(TIMEFRAMES)[tf];
    canvas.style.opacity = '.5';
    try {
      const ex = state.meta.index_exchange && (sym.includes('NIFTY') || sym.includes('VIX') || sym === 'SENSEX') ? state.meta.index_exchange : state.meta.price_exchange;
      const h = await api(`/v1/history?symbol=${enc(sym)}&exchange=${enc(ex)}&periodicity=${opt.periodicity}&period=${opt.period}&bars=${opt.bars}&indicators=${enc(want.join(','))}`);
      const ind = h.indicators || {};
      const overlays = [];
      if (ind['sma:20']) overlays.push({ values: ind['sma:20'], color: palette(1), width: 1.2 });
      if (ind['sma:50']) overlays.push({ values: ind['sma:50'], color: palette(3), width: 1.2 });
      if (ind['bollinger:20']) { overlays.push({ values: ind['bollinger:20'].upper, color: 'var(--faint)', width: 1, dash: [3, 3] }); overlays.push({ values: ind['bollinger:20'].lower, color: 'var(--faint)', width: 1, dash: [3, 3] }); }
      let lower = null;
      if (indicators.rsi && ind['rsi:14']) lower = { type: 'rsi', values: ind['rsi:14'] };
      else if (indicators.macd && ind['macd']) lower = { type: 'macd', ...ind['macd'] };
      chart.set({ candles: h.candles, overlays, lower, type: ['1W', '1M'].includes(tf) ? 'candle' : 'candle' });
      const last = h.candles[h.candles.length - 1], first = h.candles[0];
      const chg = last && first ? (last.c / h.candles[Math.max(0, h.candles.length - 2)].c - 1) * 100 : 0;
      ctx.$('#chart-title').replaceChildren(
        el('b', { class: 'mono', style: 'font-size:18px' }, sym),
        el('span', { class: 'mono', style: 'font-size:18px' }, num(last?.c)),
        changePill(chg),
        el('span', { class: 'mini muted' }, `${h.candles.length} bars`),
      );
    } catch (e) { toast(e.detail || e.message, 'error'); }
    canvas.style.opacity = '1';
  }
  syncSeg(); paint();

  // technicals
  fill(techCard, () => api(`/v1/technicals?symbol=${enc(symInput.value.trim().toUpperCase())}`), (t, host) => {
    host.append(el('h3', {}, 'Technical snapshot'));
    const kv = el('div', { class: 'kv' });
    const items = [
      ['Trend', t.trend || '–'], ['RSI 14', num(t.rsi14)], ['SMA 50', num(t.sma50)], ['SMA 200', num(t.sma200)],
      ['1 week', pct(t.change_1w_pct)], ['1 month', pct(t.change_1m_pct)], ['3 months', pct(t.change_3m_pct)], ['1 year', pct(t.change_1y_pct)],
      ['52w high', num(t.high_52w)], ['from high', pct(t.pct_from_52w_high)], ['ATR 14', num(t.atr14)], ['Volatility', t.volatility_1y_pct != null ? num(t.volatility_1y_pct) + '%' : '–'],
    ];
    for (const [k, v] of items) kv.append(el('div', {}, [el('div', { class: 'k' }, k), el('div', { class: `v ${typeof v === 'string' && v.includes('%') ? cls(parseFloat(v)) : ''}` }, v)]));
    host.append(kv);
  });
}

// ============================================================ SCREENER =======
export async function screener(root, ctx) {
  const meta = await api('/v1/screener/presets').catch(() => null);
  root.append(viewHeader('Screener', meta ? `Scan ${meta.universe_size} stocks on fundamentals and technicals together` : 'Stock screener'));
  if (!meta) { root.append(el('div', { class: 'empty down' }, 'Could not load screener')); return; }

  const filters = [];
  const filtersBox = el('div', { class: 'stack', style: 'gap:8px' });
  const resultBox = el('div', { class: 'card pad0', style: 'margin-top:14px' });
  const numericFields = meta.fields.filter((f) => !['symbol', 'name', 'sector', 'industry', 'trend', 'above_sma200'].includes(f));

  function addFilter(f = { field: 'pe', op: '<', value: 25 }) {
    const field = el('select', { class: 'input' }, numericFields.map((n) => el('option', { value: n, selected: n === f.field }, n)));
    const op = el('select', { class: 'input', style: 'width:72px' }, ['<', '<=', '>', '>=', '==', 'between'].map((o) => el('option', { value: o, selected: o === f.op }, o)));
    const val = el('input', { class: 'input mono', style: 'width:120px', value: Array.isArray(f.value) ? f.value.join(',') : f.value, placeholder: 'value' });
    field.style.cssText = 'flex:1;min-width:120px'; val.style.width = '110px';
    const rowEl = el('div', { class: 'row wrap', style: 'gap:6px' }, [field, op, val,
      el('button', { class: 'icon-btn', onclick: () => { rowEl.remove(); const i = filters.indexOf(rec); if (i >= 0) filters.splice(i, 1); } }, rawIcon('close', 15))]);
    const rec = { get field() { return field.value; }, get op() { return op.value; }, get value() { const v = val.value.trim(); return op.value === 'between' ? v.split(',').map(Number) : (isNaN(Number(v)) ? v : Number(v)); } };
    filters.push(rec); filtersBox.append(rowEl);
  }

  const presetSel = el('select', { class: 'input', style: 'min-width:160px;width:260px;max-width:100%' }, [el('option', { value: '' }, 'Custom filters'),
    ...Object.entries(meta.presets).map(([k, v]) => el('option', { value: k }, `${k} — ${v.description}`))]);
  const sortInput = el('input', { class: 'input mono', style: 'width:150px', placeholder: 'sort e.g. -change_3m_pct' });

  const controls = el('div', { class: 'card' }, [
    el('div', { class: 'row wrap spread', style: 'margin-bottom:12px' }, [
      el('div', { class: 'row wrap', style: 'gap:8px' }, [presetSel, sortInput]),
      el('div', { class: 'row', style: 'gap:8px' }, [
        el('button', { class: 'btn', onclick: () => addFilter() }, [rawIcon('plus', 15), 'Filter']),
        el('button', { class: 'btn primary', onclick: run }, [rawIcon('filter', 15), 'Run screen']),
      ]),
    ]),
    filtersBox,
    el('div', { class: 'faint tiny', style: 'margin-top:10px' }, `Fields: ${meta.fields.join(', ')}`),
  ]);
  root.append(controls, resultBox);
  presetSel.onchange = () => { filtersBox.innerHTML = ''; filters.length = 0; if (presetSel.value) { sortInput.value = meta.presets[presetSel.value].sort || ''; } };
  addFilter();

  async function run() {
    resultBox.innerHTML = '<div class="empty"><span class="spinner"></span> scanning…</div>';
    const body = { preset: presetSel.value || null, sort: sortInput.value.trim() || null, filters: filters.map((f) => ({ field: f.field, op: f.op, value: f.value })) };
    try {
      const r = await api('/v1/screener', { method: 'POST', body });
      resultBox.innerHTML = '';
      resultBox.append(el('div', { class: 'card-head', style: 'padding:14px 16px' }, [
        el('h3', {}, [`${r.matched} matches`, el('span', { class: 'muted' }, ` of ${r.universe_size}`)]),
        r.failed?.length ? el('span', { class: 'mini faint' }, `${r.failed.length} skipped`) : null,
      ]));
      resultBox.append(table([
        { head: 'Symbol', cell: (x) => symCell(x.symbol, x.sector) },
        { head: 'Close', cell: (x) => el('span', { class: 'mono' }, num(x.close)) },
        { head: '1M %', cell: (x) => changePill(x.change_1m_pct) },
        { head: 'P/E', cell: (x) => el('span', { class: 'mono' }, num(x.pe)) },
        { head: 'P/B', cell: (x) => el('span', { class: 'mono' }, num(x.pb)) },
        { head: 'RSI', cell: (x) => el('span', { class: 'mono' }, num(x.rsi14, 0)) },
        { head: '3M', cell: (x) => changePill(x.change_3m_pct) },
        { head: 'Trend', cell: (x) => el('span', { class: 'mini muted' }, x.trend || '–') },
        { head: 'M.Cap', cell: (x) => el('span', { class: 'mono mini' }, money(x.market_cap, { crore: true })) },
      ], r.results, { onRow: (x) => ctx.openSymbol(x.symbol) }));
    } catch (e) { resultBox.innerHTML = ''; resultBox.append(el('div', { class: 'empty down' }, e.detail || e.message)); }
  }
  run();
}

// ============================================================ LAB ============
export async function lab(root, ctx) {
  const strat = await api('/v1/backtest/strategies').catch(() => ({}));
  const names = Object.keys(strat);
  root.append(viewHeader('Strategy Lab', 'Backtest a strategy or compare them all — with costs, drawdown and trade stats'));

  const symInput = el('input', { class: 'input mono', style: 'width:130px', value: 'INFY' });
  const stratSel = el('select', { class: 'input' }, names.map((n) => el('option', { value: n }, n)));
  const paramsInput = el('input', { class: 'input mono', style: 'width:220px', placeholder: 'params e.g. {"fast":10,"slow":40}' });
  const barsInput = el('input', { class: 'input mono', style: 'width:90px', value: '1000', type: 'number' });
  const costInput = el('input', { class: 'input mono', style: 'width:80px', value: '10', type: 'number' });

  const controls = el('div', { class: 'card' }, [el('div', { class: 'row wrap', style: 'gap:10px;align-items:flex-end' }, [
    field('Symbol', symInput), field('Strategy', stratSel), field('Params (JSON)', paramsInput), field('Bars', barsInput), field('Cost bps', costInput),
    el('button', { class: 'btn primary', onclick: single }, 'Run backtest'),
    el('button', { class: 'btn', onclick: compare }, 'Compare all'),
  ])]);
  const out = el('div', { style: 'margin-top:14px' });
  root.append(controls, out);

  function field(label, input) { return el('label', { class: 'field' }, [label, input]); }

  async function single() {
    out.innerHTML = '<div class="card"><div class="empty"><span class="spinner"></span> running…</div></div>';
    let params = {};
    if (paramsInput.value.trim()) { try { params = JSON.parse(paramsInput.value); } catch { toast('Params must be valid JSON', 'error'); return; } }
    try {
      const r = await api('/v1/backtest', { method: 'POST', body: { symbol: symInput.value.trim().toUpperCase(), strategy: stratSel.value, params, bars: +barsInput.value, cost_bps: +costInput.value } });
      out.innerHTML = '';
      const m = r.metrics, b = r.benchmark;
      out.append(el('div', { class: 'grid cols-4', style: 'margin-bottom:14px' }, [
        stat('Total return', pct(m.total_return_pct), `buy & hold ${pct(b.total_return_pct)}`, cls(m.total_return_pct)),
        stat('CAGR', pct(m.cagr_pct), null, cls(m.cagr_pct)),
        stat('Sharpe', num(m.sharpe), `Sortino ${num(m.sortino)}`),
        stat('Max drawdown', pct(m.max_drawdown_pct), `Calmar ${num(m.calmar)}`, 'down'),
      ]));
      const chartCard = el('div', { class: 'card' }, [el('h3', {}, [`Equity curve · ${esc(r.symbol)} · ${esc(r.strategy)}`, el('span', { class: 'muted mono mini' }, ` ${JSON.stringify(r.params)}`)])]);
      const cv = el('canvas', { style: 'height:300px' });
      chartCard.append(el('div', { class: 'chart-shell' }, cv));
      const tradeCard = el('div', { class: 'card' }, [el('h3', {}, 'Trades')]);
      tradeCard.append(table([
        { head: 'Entry', cell: (t) => el('span', { class: 'mono mini' }, (t.entry_time ? new Date(t.entry_time * 1000).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: '2-digit' }) : '–')) },
        { head: 'Side', cell: (t) => el('span', { class: t.side === 'long' ? 'up' : 'down' }, t.side) },
        { head: 'Entry ₹', cell: (t) => el('span', { class: 'mono' }, num(t.entry_price)) },
        { head: 'Exit ₹', cell: (t) => el('span', { class: 'mono' }, num(t.exit_price)) },
        { head: 'Return', cell: (t) => changePill(t.return_pct) },
      ], r.trades.slice(-14).reverse()));
      const perfCard = el('div', { class: 'card' }, [el('h3', {}, 'Trading'), metricsKv(m)]);
      out.append(el('div', { class: 'grid cols-3' }, [el('div', { class: 'span-2' }, chartCard), perfCard]), el('div', { style: 'margin-top:14px' }, tradeCard));
      drawEquity(cv, r.equity);
    } catch (e) { out.innerHTML = ''; out.append(el('div', { class: 'card' }, el('div', { class: 'empty down' }, e.detail || e.message))); }
  }

  async function compare() {
    out.innerHTML = '<div class="card"><div class="empty"><span class="spinner"></span> comparing strategies…</div></div>';
    try {
      const r = await api('/v1/backtest/compare', { method: 'POST', body: { symbol: symInput.value.trim().toUpperCase(), bars: +barsInput.value, cost_bps: +costInput.value } });
      out.innerHTML = '';
      const rows = [...r.results, { strategy: 'buy & hold (benchmark)', metrics: r.benchmark, bench: true }];
      out.append(el('div', { class: 'card pad0' }, [
        el('div', { class: 'card-head', style: 'padding:14px 16px' }, el('h3', {}, [`Strategy comparison · ${esc(r.symbol)}`, el('span', { class: 'muted' }, ` · ${r.bars} bars`)])),
        table([
          { head: 'Strategy', cell: (x) => el('span', { class: x.bench ? 'muted' : '', style: 'font-weight:500' }, x.strategy) },
          { head: 'Return', cell: (x) => changePill(x.metrics.total_return_pct) },
          { head: 'CAGR', cell: (x) => el('span', { class: `mono ${cls(x.metrics.cagr_pct)}` }, pct(x.metrics.cagr_pct)) },
          { head: 'Sharpe', cell: (x) => el('span', { class: 'mono' }, num(x.metrics.sharpe)) },
          { head: 'Max DD', cell: (x) => el('span', { class: 'mono down' }, pct(x.metrics.max_drawdown_pct)) },
          { head: 'Trades', cell: (x) => el('span', { class: 'mono mini muted' }, x.metrics.trades) },
          { head: 'Win%', cell: (x) => el('span', { class: 'mono mini' }, x.metrics.win_rate_pct != null ? num(x.metrics.win_rate_pct, 0) + '%' : '–') },
        ], rows),
      ]));
    } catch (e) { out.innerHTML = ''; out.append(el('div', { class: 'card' }, el('div', { class: 'empty down' }, e.detail || e.message))); }
  }
  function metricsKv(m) {
    const kv = el('div', { class: 'kv' });
    for (const [k, v] of [['Trades', m.trades], ['Win rate', num(m.win_rate_pct, 0) + '%'], ['Avg trade', pct(m.avg_trade_pct)], ['Exposure', num(m.exposure_pct, 0) + '%'], ['Volatility', num(m.volatility_pct) + '%'], ['Final equity', '₹' + num(m.final_equity, 0)]])
      kv.append(el('div', {}, [el('div', { class: 'k' }, k), el('div', { class: 'v' }, v)]));
    return kv;
  }
  single();
}
function drawEquity(canvas, equity) {
  const c1 = new Chart(canvas);
  c1.set({ type: 'line', showVolume: false, candles: equity.map((e) => ({ t: e.t, c: e.equity, o: e.equity, h: e.equity, l: e.equity })),
    overlays: [{ values: equity.map((e) => e.benchmark), color: 'var(--faint)', width: 1.2, dash: [4, 3] }] });
}

// ============================================================ OPTIONS ========
export async function optionsView(root, ctx) {
  const productInput = el('input', { class: 'input mono', style: 'width:130px', value: 'NIFTY' });
  const expirySel = el('select', { class: 'input', style: 'min-width:140px' }, [el('option', {}, 'nearest')]);
  root.append(viewHeader('Options', 'Live option chain with put-call ratio, max pain and open-interest walls', [
    el('form', { class: 'row', style: 'gap:8px', onsubmit: (e) => { e.preventDefault(); load(); } }, [productInput, expirySel, el('button', { class: 'btn primary', type: 'submit' }, 'Load chain')]),
  ]));
  const statRow = el('div', { class: 'grid cols-4', style: 'margin-bottom:14px' });
  const grid = el('div', { class: 'grid cols-3' });
  const oiCard = el('div', { class: 'card' });
  const chainCard = el('div', { class: 'card pad0 span-2' });
  grid.append(chainCard, oiCard);
  root.append(statRow, grid);

  async function load(expiry) {
    chainCard.innerHTML = '<div class="empty"><span class="spinner"></span></div>'; statRow.innerHTML = ''; oiCard.innerHTML = '';
    try {
      const prod = productInput.value.trim().toUpperCase();
      const r = await api(`/v1/options/chain?product=${enc(prod)}${expiry ? `&expiry=${enc(expiry)}` : ''}`);
      if (r.expiries?.length && expirySel.children.length <= 1) expirySel.replaceChildren(...r.expiries.map((e) => el('option', { value: e, selected: e === r.expiry }, e)));
      const s = r.summary;
      statRow.append(
        stat('PCR (OI)', num(s.pcr_oi, 2), s.pcr_oi > 1 ? 'put-heavy' : 'call-heavy', s.pcr_oi > 1 ? 'up' : 'down'),
        stat('Max pain', num(s.max_pain, 0), `ATM ${num(s.atm_strike, 0)}`),
        stat('Call OI', _n(s.total_call_oi, 0), `resistance ${s.resistance.map((x) => num(x, 0)).join(', ')}`),
        stat('Put OI', _n(s.total_put_oi, 0), `support ${s.support.map((x) => num(x, 0)).join(', ')}`),
      );
      // group by strike
      const byStrike = {};
      for (const row of r.rows) (byStrike[row.strike] ||= { strike: row.strike })[row.option_type] = row;
      const strikes = Object.values(byStrike).sort((a, b) => a.strike - b.strike);
      const maxOi = Math.max(...r.rows.map((x) => x.open_interest || 0), 1);
      chainCard.innerHTML = '';
      chainCard.append(el('div', { class: 'card-head', style: 'padding:14px 16px' }, el('h3', {}, [`${esc(prod)} chain`, el('span', { class: 'muted' }, ` · ${esc(r.expiry || '')}`)])));
      chainCard.append(table([
        { head: 'Call OI', cell: (x) => oiBar(x.CE?.open_interest, maxOi, 'var(--up)') },
        { head: 'Call LTP', cell: (x) => el('span', { class: 'mono' }, x.CE ? num(x.CE.ltp) : '–') },
        { head: 'Strike', cell: (x) => el('b', { class: 'mono', style: x.strike === s.atm_strike ? 'color:var(--accent)' : '' }, num(x.strike, 0)) },
        { head: 'Put LTP', cell: (x) => el('span', { class: 'mono' }, x.PE ? num(x.PE.ltp) : '–') },
        { head: 'Put OI', cell: (x) => oiBar(x.PE?.open_interest, maxOi, 'var(--down)') },
      ], strikes));
      // OI by strike
      oiCard.append(el('h3', {}, 'Open interest by strike'));
      const near = strikes.filter((x) => Math.abs(x.strike - s.atm_strike) <= 6 * (strikes[1].strike - strikes[0].strike));
      for (const x of near) {
        oiCard.append(el('div', { style: 'display:grid;grid-template-columns:1fr 54px 1fr;gap:6px;align-items:center;margin-bottom:5px' }, [
          el('div', { class: 'hbar-track', style: 'display:flex;justify-content:flex-end' }, el('div', { class: 'hbar', style: `width:${(x.CE?.open_interest || 0) / maxOi * 100}%;background:var(--up);border-radius:5px 0 0 5px` })),
          el('span', { class: 'mono tiny center', style: x.strike === s.atm_strike ? 'color:var(--accent)' : 'color:var(--dim)' }, num(x.strike, 0)),
          el('div', { class: 'hbar-track' }, el('div', { class: 'hbar', style: `width:${(x.PE?.open_interest || 0) / maxOi * 100}%;background:var(--down);border-radius:0 5px 5px 0` })),
        ]));
      }
    } catch (e) { chainCard.innerHTML = ''; chainCard.append(el('div', { class: 'empty down' }, e.detail || e.message)); }
  }
  expirySel.onchange = () => load(expirySel.value !== 'nearest' ? expirySel.value : undefined);
  load();
}
function oiBar(oi, max, color) {
  if (oi == null) return el('span', { class: 'faint' }, '–');
  return el('div', { style: 'display:flex;align-items:center;gap:6px;justify-content:flex-end' }, [
    el('span', { class: 'mono mini' }, _n(oi, 0)),
    el('div', { style: `width:${Math.max(2, oi / max * 60)}px;height:8px;border-radius:4px;background:${color};opacity:.5` }),
  ]);
}

// ============================================================ FUNDS ==========
export async function funds(root, ctx) {
  root.append(viewHeader('Mutual Funds', 'Returns, portfolio holdings and overlap across schemes'));
  const searchInput = el('input', { class: 'input', style: 'width:220px', value: 'direct', placeholder: 'scheme name' });
  const listCard = el('div', { class: 'card pad0' });
  const detail = el('div', { style: 'margin-top:14px' });
  root.append(el('div', { class: 'card', style: 'margin-bottom:14px' }, el('div', { class: 'row', style: 'gap:8px' }, [
    searchInput, el('button', { class: 'btn primary', onclick: search }, 'Search'),
    el('span', { class: 'mini faint' }, 'or try a category: Equity, Debt, Hybrid'),
  ])), listCard, detail);

  async function search() {
    listCard.innerHTML = '<div class="empty"><span class="spinner"></span></div>';
    try {
      const q = searchInput.value.trim();
      const rows = await api(`/v1/mf/schemes?name=${enc(q)}`);
      listCard.innerHTML = '';
      listCard.append(table([
        { head: 'Code', cell: (s) => el('span', { class: 'mono mini muted' }, s.Code) },
        { head: 'Scheme', cell: (s) => el('span', {}, s.Name) },
        { head: 'Category', cell: (s) => el('span', { class: 'chip' }, s.SubCategory || s.Category) },
      ], rows.slice(0, 40), { onRow: (s) => openFund(s.Code) }));
    } catch (e) { listCard.innerHTML = ''; listCard.append(el('div', { class: 'empty down' }, e.detail || e.message)); }
  }

  async function openFund(code) {
    detail.innerHTML = '<div class="card"><div class="empty"><span class="spinner"></span></div></div>';
    try {
      const [ret, hold] = await Promise.all([api(`/v1/mf/${enc(code)}/returns`), api(`/v1/mf/${enc(code)}/holdings`)]);
      detail.innerHTML = '';
      const retRow = el('div', { class: 'grid cols-4', style: 'margin-bottom:14px' });
      for (const [k, v] of Object.entries(ret.returns)) {
        if (!v) continue;
        retRow.append(stat(k.toUpperCase(), pct(v.absolute_pct), v.cagr_pct != null ? `CAGR ${pct(v.cagr_pct)}` : 'absolute', cls(v.absolute_pct)));
      }
      detail.append(el('div', { class: 'card' }, [el('h3', {}, [esc(ret.name), el('span', { class: 'muted mono mini' }, ` NAV ${num(ret.nav, 4)} · ${esc(ret.date?.slice(0, 10) || '')}`)]), retRow]));
      // exposure donut + holdings
      const exp = hold.exposure;
      const donutCard = el('div', { class: 'card' }, [el('h3', {}, 'Sector exposure')]);
      const dc = el('canvas', { style: 'width:150px;height:150px;margin:0 auto;display:block' });
      const slices = exp.by_sector.slice(0, 8).map((s, i) => ({ value: s.weight, color: palette(i), label: s.name }));
      donutCard.append(el('div', { class: 'row', style: 'gap:16px;align-items:center;flex-wrap:wrap' }, [
        dc, el('div', { class: 'stack', style: 'flex:1;min-width:140px' }, slices.map((s) => el('div', { class: 'row spread mini' }, [
          el('span', { class: 'row', style: 'gap:6px' }, [el('span', { style: `width:9px;height:9px;border-radius:2px;background:${s.color}` }), s.label]),
          el('span', { class: 'mono' }, num(s.value) + '%'),
        ]))),
      ]));
      donutCard.append(el('div', { class: 'mini faint', style: 'margin-top:10px' }, `Top 10 holdings: ${num(exp.top10_weight)}% of assets`));
      const holdCard = el('div', { class: 'card pad0 span-2' }, [el('div', { class: 'card-head', style: 'padding:14px 16px' }, el('h3', {}, 'Holdings'))]);
      holdCard.append(table([
        { head: 'Instrument', cell: (h) => el('span', {}, h.instrument) },
        { head: 'Sector', cell: (h) => el('span', { class: 'mini muted' }, h.sector || h.industry || '–') },
        { head: 'Size', cell: (h) => el('span', { class: 'chip mini' }, h.size || h.asset_type) },
        { head: 'Weight', cell: (h) => el('span', { class: 'mono' }, num(h.weight) + '%') },
      ], hold.holdings.slice(0, 20)));
      detail.append(el('div', { class: 'grid cols-3' }, [holdCard, donutCard]));
      requestAnimationFrame(() => donut(dc, slices));
    } catch (e) { detail.innerHTML = ''; detail.append(el('div', { class: 'card' }, el('div', { class: 'empty down' }, e.detail || e.message))); }
  }
  search();
}

// ============================================================ NEWS ===========
export async function news(root, ctx) {
  const symInput = el('input', { class: 'input mono', style: 'width:260px', value: ctx.watchlist().slice(0, 6).join(',') });
  let es = null;
  const streamBtn = el('button', { class: 'btn' }, [rawIcon('bolt', 15), 'Go live']);
  root.append(viewHeader('News', 'AI-summarised, sentiment-tagged market news', [
    el('form', { class: 'row', style: 'gap:8px', onsubmit: (e) => { e.preventDefault(); load(); } }, [symInput, el('button', { class: 'btn primary', type: 'submit' }, 'Load')]),
    streamBtn,
  ]));
  const grid = el('div', { class: 'grid cols-3' });
  const feedCard = el('div', { class: 'card span-2' });
  const sideCard = el('div', { class: 'card' });
  const liveCard = el('div', { class: 'card', hidden: true });
  grid.append(feedCard, el('div', { class: 'stack', style: 'gap:14px' }, [sideCard, liveCard]));
  root.append(grid);
  ctx.onLeave(() => es?.close());

  async function load() {
    feedCard.innerHTML = '<div class="empty"><span class="spinner"></span></div>'; sideCard.innerHTML = '';
    try {
      const symbols = symInput.value.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean);
      const [multi, general] = await Promise.all([api(`/v1/news/multi?symbols=${CSV(symbols)}&limit=60`), api('/v1/news/general?limit=10')]);
      feedCard.innerHTML = '';
      feedCard.append(el('h3', {}, 'Company news'));
      feedCard.append(el('div', { style: 'max-height:640px;overflow-y:auto' }, multi.articles.map((a) => articleRow(a))));
      sideCard.append(el('h3', {}, 'By symbol'));
      sideCard.append(table([
        { head: 'Symbol', cell: (r) => el('b', { class: 'mono', style: 'cursor:pointer', onclick: () => ctx.openSymbol(r.symbol) }, r.symbol) },
        { head: 'Mood', cell: (r) => el('span', { class: `chip ${r.label.includes('bull') ? 'pos' : r.label.includes('bear') ? 'neg' : 'neu'}` }, r.label) },
        { head: 'Score', cell: (r) => el('span', { class: `mono ${cls(r.net_score)}` }, signed(r.net_score)) },
      ], multi.by_symbol.slice(0, 12)));
      sideCard.append(el('h3', { style: 'margin-top:16px' }, 'Market'));
      sideCard.append(el('div', { style: 'max-height:260px;overflow-y:auto' }, general.articles.slice(0, 6).map((a) => articleRow(a))));
    } catch (e) { feedCard.innerHTML = ''; feedCard.append(el('div', { class: 'empty down' }, e.detail || e.message)); }
  }

  streamBtn.onclick = () => {
    if (es) { es.close(); es = null; streamBtn.classList.remove('primary'); streamBtn.lastChild.textContent = 'Go live'; liveCard.hidden = true; return; }
    const symbols = symInput.value.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean);
    es = new EventSource(`/v1/news/stream?symbols=${CSV(symbols)}&api_key=${enc(state.apiKey)}`);
    streamBtn.classList.add('primary'); streamBtn.lastChild.textContent = 'Live'; liveCard.hidden = false;
    liveCard.innerHTML = ''; liveCard.append(el('h3', {}, ['Live feed ', el('span', { class: 'chip pos' }, '● streaming')]));
    const feed = el('div', { style: 'max-height:340px;overflow-y:auto' }); liveCard.append(feed);
    es.addEventListener('article', (ev) => { try { feed.prepend(articleRow(JSON.parse(ev.data), { flash: true })); } catch {} });
    es.onerror = () => { toast('Live stream needs the Algo plan', 'error'); es.close(); es = null; streamBtn.classList.remove('primary'); streamBtn.lastChild.textContent = 'Go live'; liveCard.hidden = true; };
  };
  load();
}

// ============================================================ EARNINGS =======
const DOC_LABEL = { transcript: 'Transcript', audio: 'Call audio', presentation: 'Presentation', results: 'Results', call: 'Event' };
export async function earnings(root, ctx) {
  const symInput = el('input', { class: 'input mono', style: 'width:150px', value: (ctx.params.symbol || 'TCS').toUpperCase() });
  root.append(viewHeader('Earnings Calls', 'Upcoming results, concall transcripts and call recordings — read the PDF or transcribe the audio', [
    el('form', { class: 'row', style: 'gap:8px', onsubmit: (e) => { e.preventDefault(); loadCompany(symInput.value.trim().toUpperCase()); } }, [
      symInput, el('button', { class: 'btn', type: 'submit' }, rawIcon('search')),
    ]),
  ]));
  const grid = el('div', { class: 'grid cols-3' });
  const calCard = el('div', { class: 'card' });
  const companyCard = el('div', { class: 'card span-2' });
  grid.append(companyCard, calCard);
  const reader = el('div', { class: 'card', style: 'margin-top:14px', hidden: true });
  root.append(grid, reader);

  let providers = { transcription: false };
  try { providers = await api('/v1/documents/providers'); } catch { /* plan gate handled below */ }

  // calendar
  fill(calCard, () => api('/v1/earnings/calendar?range=Next30days'), (cal, host) => {
    host.append(el('h3', {}, ['Earnings calendar', el('span', { class: 'muted' }, ' · next 30 days')]));
    const rows = cal.upcoming.length ? cal.upcoming : cal.recent;
    if (!rows.length) { host.append(el('div', { class: 'empty' }, 'No scheduled results')); return; }
    host.append(el('div', { class: 'stack', style: 'gap:2px' }, rows.slice(0, 14).map((r) => el('div', {
      class: 'row spread', style: 'padding:7px 0;border-bottom:1px solid var(--border-soft);cursor:pointer',
      onclick: () => { symInput.value = r.symbol; loadCompany(r.symbol); },
    }, [
      el('div', { class: 'stack', style: 'gap:1px' }, [el('b', { class: 'mono' }, r.symbol), el('span', { class: 'tiny faint', style: 'max-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap' }, r.name || '')]),
      el('div', { class: 'stack', style: 'text-align:right;gap:1px' }, [el('span', { class: 'mono mini' }, (r.date || '').slice(0, 10)), r.change_pct != null ? changePill(r.change_pct) : null]),
    ]))));
  });

  async function loadCompany(sym) {
    reader.hidden = true;
    companyCard.innerHTML = '<div class="empty"><span class="spinner"></span></div>';
    let data;
    try { data = await api(`/v1/earnings/${enc(sym)}`); }
    catch (e) {
      companyCard.innerHTML = '';
      companyCard.append(el('div', { class: 'empty' }, [el('div', { class: 'down', style: 'margin-bottom:6px' }, e.status === 403 ? 'Earnings is a Trader Pro feature' : 'Could not load'), el('div', { class: 'mini muted' }, e.detail || e.message)]));
      return;
    }
    companyCard.innerHTML = '';
    const next = data.upcoming?.[0];
    companyCard.append(el('div', { class: 'card-head' }, [
      el('h3', {}, [el('b', { class: 'mono' }, data.symbol), el('span', { class: 'muted', style: 'margin-left:8px' }, 'earnings calls')]),
      next ? el('span', { class: 'chip accent' }, `Next results ${(next.date || '').slice(0, 10)}`) : el('span', { class: 'chip' }, 'No date announced'),
    ]));
    const docs = data.documents.filter((d) => d.url);
    if (!docs.length) { companyCard.append(el('div', { class: 'empty' }, 'No earnings-call documents filed recently')); return; }
    companyCard.append(el('div', { class: 'stack', style: 'gap:2px' }, docs.map((d) => el('div', {
      class: 'row spread', style: 'padding:9px 0;border-bottom:1px solid var(--border-soft)',
    }, [
      el('div', { class: 'row', style: 'gap:10px;min-width:0;flex:1' }, [
        el('span', { class: `chip ${d.is_audio ? 'neu' : 'accent'}`, style: 'min-width:92px;justify-content:center;flex-shrink:0' }, [rawIcon(d.is_audio ? 'mic' : 'doc', 13), DOC_LABEL[d.kind] || d.kind]),
        el('div', { class: 'stack', style: 'gap:1px;min-width:0' }, [
          el('span', { style: 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0' }, d.headline),
          el('span', { class: 'tiny faint' }, (d.date || '').slice(0, 16).replace('T', ' ')),
        ]),
      ]),
      el('button', { class: 'btn', style: 'height:30px;flex-shrink:0', onclick: () => openDoc(d) }, d.is_audio ? [rawIcon('mic', 14), 'Transcribe'] : [rawIcon('doc', 14), 'Read']),
    ]))));
  }

  async function openDoc(d) {
    reader.hidden = false;
    reader.innerHTML = `<div class="card-head"><h3>${esc(d.headline)}</h3></div><div class="empty"><span class="spinner"></span> ${d.is_audio ? 'transcribing audio…' : 'extracting text…'}</div>`;
    reader.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    try {
      const r = await api('/v1/documents/read', { method: 'POST', body: { url: d.url } });
      reader.innerHTML = '';
      const meta = [];
      if (r.kind === 'pdf') meta.push(el('span', { class: 'chip mini' }, `${r.pages} pages`), el('span', { class: 'chip mini' }, `${num(r.chars, 0)} chars`));
      if (r.demo) meta.push(el('span', { class: 'chip neu mini' }, 'demo document'));
      if (r.duration_min) meta.push(el('span', { class: 'chip mini' }, `${r.duration_min} min`));
      reader.append(el('div', { class: 'card-head' }, [
        el('h3', {}, [rawIcon(d.is_audio ? 'mic' : 'doc', 15), d.headline]),
        el('div', { class: 'row', style: 'gap:6px' }, meta),
      ]));
      if (r.kind === 'audio') {
        if (!r.available) {
          reader.append(el('div', { class: 'stack', style: 'gap:10px' }, [
            el('div', { class: 'mini muted' }, r.message),
            el('audio', { controls: '', src: r.source, style: 'width:100%' }),
          ]));
          return;
        }
        if (!String(r.source).includes('demo.gtp.local')) reader.append(el('audio', { controls: '', src: r.source, style: 'width:100%;margin-bottom:10px' }));
      }
      const text = r.kind === 'audio' ? r.transcript : r.text;
      reader.append(el('div', {
        class: 'mono', style: 'white-space:pre-wrap;line-height:1.7;font-size:12.5px;max-height:480px;overflow-y:auto;background:var(--panel-2);border:1px solid var(--border);border-radius:10px;padding:14px',
      }, text || '(no text could be extracted)'));
      if (d.url && !String(d.url).includes('demo.gtp.local')) reader.append(el('a', { class: 'mini', href: d.url, target: '_blank', rel: 'noopener noreferrer', style: 'margin-top:8px;display:inline-block' }, 'Source filing ↗'));
    } catch (e) {
      reader.innerHTML = '';
      reader.append(el('div', { class: 'empty down' }, e.detail || e.message));
    }
  }

  loadCompany(symInput.value.trim().toUpperCase());
}

// ============================================================ API / ACCOUNT ==
export async function account(root, ctx) {
  root.append(viewHeader('API & Account', 'Your plan, usage and the endpoints behind every screen'));
  const me = await api('/v1/me').catch(() => null);
  const plans = state.plans;
  const grid = el('div', { class: 'grid cols-3' });
  root.append(grid);

  // plan + quota
  const planCard = el('div', { class: 'card' });
  if (me) {
    const q = me.quota;
    planCard.append(el('h3', {}, 'Your plan'));
    planCard.append(el('div', { class: 'row spread', style: 'margin-bottom:12px' }, [
      el('div', {}, [el('div', { class: 'stat-v mono', style: 'font-size:20px;font-weight:600' }, me.plan.name), el('div', { class: 'mini muted' }, me.customer.email)]),
      el('span', { class: 'chip accent' }, me.plan.id),
    ]));
    planCard.append(quotaMeter('Per minute', q.minute_used, q.minute_limit));
    planCard.append(quotaMeter('Today', q.day_used, q.day_limit));
    planCard.append(el('div', { class: 'mini faint', style: 'margin-top:10px' }, `API key: ${state.apiKey?.slice(0, 10)}…`));
  } else planCard.append(el('div', { class: 'empty' }, 'Sign in with an API key'));

  // features
  const featCard = el('div', { class: 'card span-2' });
  featCard.append(el('h3', {}, 'Plans'));
  featCard.append(el('div', { class: 'tbl-wrap' }, el('table', { class: 'tbl' }, [
    el('thead', {}, el('tr', {}, [el('th', {}, 'Plan'), el('th', {}, '₹/mo'), el('th', {}, 'Req/min'), el('th', {}, 'Req/day'), el('th', {}, 'Symbols'), el('th', {}, 'Features')])),
    el('tbody', {}, plans.map((p) => el('tr', {}, [
      el('td', {}, el('b', {}, p.name)), el('td', { class: 'mono' }, p.price_inr_month ? num(p.price_inr_month, 0) : 'Free'),
      el('td', { class: 'mono' }, num(p.requests_per_minute, 0)), el('td', { class: 'mono' }, num(p.requests_per_day, 0)),
      el('td', { class: 'mono' }, p.max_symbols_per_request), el('td', { class: 'mini muted' }, `${p.features.length} features`),
    ]))),
  ])));
  grid.append(planCard, featCard);

  // endpoint explorer
  const apiCard = el('div', { class: 'card span-2' });
  apiCard.append(el('h3', {}, ['Use the API', el('a', { class: 'mini', href: '/docs', target: '_blank', style: 'margin-left:auto' }, 'OpenAPI docs ↗')]));
  const origin = location.origin;
  apiCard.append(el('pre', { class: 'code', html:
    `<span class="tok-c"># Every endpoint takes your key in the X-API-Key header</span>\n` +
    `curl -H <span class="tok-s">"X-API-Key: ${esc(state.apiKey || '&lt;key&gt;')}"</span> \\\n     ${esc(origin)}/v1/company/TCS\n\n` +
    `<span class="tok-c"># Python</span>\n` +
    `<span class="tok-k">import</span> requests\n` +
    `s = requests.Session(); s.headers[<span class="tok-s">"X-API-Key"</span>] = <span class="tok-s">"${esc(state.apiKey || '<key>')}"</span>\n` +
    `print(s.get(<span class="tok-s">"${esc(origin)}/v1/market/heatmap"</span>).json())`,
  }));
  const endpoints = [
    ['GET', '/v1/quote?symbol=TCS', 'Live quote'], ['GET', '/v1/history?symbol=TCS&indicators=sma:20,rsi:14', 'OHLC + indicators'],
    ['GET', '/v1/company/TCS', 'Company 360'], ['GET', '/v1/market/heatmap', 'Market map'],
    ['POST', '/v1/screener', 'Run a screen'], ['POST', '/v1/backtest/compare', 'Compare strategies'],
    ['GET', '/v1/options/chain?product=NIFTY', 'Option chain'], ['GET', '/v1/mf/122639/holdings', 'Fund holdings'],
  ];
  apiCard.append(el('div', { style: 'margin-top:12px' }, endpoints.map(([m, p, d]) => el('div', { class: 'row spread', style: 'padding:7px 0;border-bottom:1px solid var(--border-soft)' }, [
    el('div', { class: 'row', style: 'gap:10px;min-width:0' }, [el('span', { class: `chip ${m === 'GET' ? 'accent' : 'neu'} mono`, style: 'min-width:46px;justify-content:center' }, m), el('span', { class: 'mono mini', style: 'overflow:hidden;text-overflow:ellipsis' }, p)]),
    el('span', { class: 'mini muted' }, d),
  ]))));

  grid.append(apiCard);
  const accountCard = el('div', { class: 'card' });
  accountCard.append(el('h3', {}, 'Session'));
  accountCard.append(el('div', { class: 'stack', style: 'gap:8px' }, [
    el('div', { class: 'row spread mini' }, [el('span', { class: 'muted' }, 'Mode'), el('span', { class: 'chip ' + (state.demo ? 'neu' : 'pos') }, state.demo ? 'demo data' : 'live')]),
    el('div', { class: 'row spread mini' }, [el('span', { class: 'muted' }, 'API key'), el('button', { class: 'btn ghost', style: 'height:28px', onclick: () => ctx.changeKey() }, 'Change key')]),
    el('div', { class: 'mini faint', style: 'margin-top:4px' }, state.demo ? 'Demo mode serves synthetic data. Switch GTP_MODE=live with your Global Datafeeds keys for real market data.' : 'Live data from Global Datafeeds.'),
  ]));
  grid.append(accountCard);
}
function quotaMeter(label, used, limit) {
  const p = Math.min(100, (used / limit) * 100);
  return el('div', { style: 'margin-bottom:10px' }, [
    el('div', { class: 'row spread mini muted', style: 'margin-bottom:4px' }, [el('span', {}, label), el('span', { class: 'mono' }, `${num(used, 0)} / ${num(limit, 0)}`)]),
    el('div', { class: 'meter' }, el('span', { style: `width:${p}%;background:${p > 85 ? 'var(--down)' : 'var(--accent)'}` })),
  ]);
}

// ============================================================ COMPANY DRAWER =
export async function renderCompany(host, symbol, ctx) {
  host.innerHTML = '<div class="empty"><span class="spinner"></span> loading ' + esc(symbol) + '…</div>';
  let data;
  try { data = await api(`/v1/company/${enc(symbol)}`); }
  catch (e) { host.innerHTML = ''; host.append(el('div', { class: 'empty down' }, e.detail || e.message)); return; }
  const S = data.sections;
  host.innerHTML = '';
  const q = S.quote.data || {}, prof = S.profile.data || {}, sec = S.sector.data || {}, ratios = S.ratios.data || {}, tech = S.technicals.data || {};
  const bal = S.signal_balance?.data;

  // header
  host.append(el('div', {}, [
    el('div', { class: 'row spread' }, [
      el('div', {}, [el('div', { class: 'row', style: 'gap:10px;align-items:baseline' }, [el('b', { class: 'mono', style: 'font-size:22px' }, data.symbol), el('span', { class: 'mono', style: 'font-size:20px' }, num(q.ltp))]),
        el('div', { class: 'mini muted' }, `${esc(prof.name || sec.name || '')}`)]),
      el('div', { class: 'stack', style: 'text-align:right' }, [changePill(q.change_pct), el('span', { class: 'mini muted mono' }, `${signed(q.change)} today`)]),
    ]),
    el('div', { class: 'row wrap', style: 'gap:6px;margin-top:8px' }, [sec.sector ? el('span', { class: 'chip' }, sec.sector) : null, sec.industry ? el('span', { class: 'chip' }, sec.industry) : null, prof.isin ? el('span', { class: 'chip mono tiny' }, prof.isin) : null]),
  ]));

  // sparkline mini chart
  const miniWrap = el('div', { class: 'card pad0', style: 'padding:4px' });
  const cv = el('canvas', { style: 'height:120px' });
  miniWrap.append(cv); host.append(miniWrap);
  api(`/v1/history?symbol=${enc(symbol)}&exchange=${enc(state.meta.price_exchange)}&bars=90`).then((h) => {
    const c = new Chart(cv); c.set({ type: 'area', showVolume: false, candles: h.candles });
  }).catch(() => {});

  // signals
  if (bal) {
    host.append(el('div', { class: 'card' }, [
      el('div', { class: 'card-head' }, [el('h3', {}, 'Signals'), el('span', { class: `chip ${bal.label.includes('bull') ? 'pos' : bal.label.includes('bear') ? 'neg' : 'neu'}` }, `${bal.label} · ${signed(bal.score)}`)]),
      ...(S.signals.data || []).map(signalRow),
    ]));
  }

  // valuation + technicals
  host.append(el('div', { class: 'grid cols-2' }, [
    el('div', { class: 'card' }, [el('h3', {}, 'Valuation'), kvGrid([['P/E', num(ratios.pe)], ['P/B', num(ratios.pb)], ['EPS', num(ratios.eps)], ['Mkt cap', money(ratios.market_cap, { crore: true })], ['Div yield', ratios.dividend_yield != null ? num(ratios.dividend_yield) + '%' : '–'], ['Debt', ratios.debt === 0 ? 'Nil' : money(ratios.debt)]])]),
    el('div', { class: 'card' }, [el('h3', {}, 'Technicals'), kvGrid([['Trend', tech.trend || '–'], ['RSI 14', num(tech.rsi14, 0)], ['1M', pct(tech.change_1m_pct)], ['1Y', pct(tech.change_1y_pct)], ['52w high', num(tech.high_52w)], ['from high', pct(tech.pct_from_52w_high)]])]),
  ]));

  // shareholding
  const shp = S.shareholding.data;
  if (Array.isArray(shp) && shp.length) {
    const card = el('div', { class: 'card' }, [el('h3', {}, 'Shareholding')]);
    for (const r of shp) card.append(labelledBar(r.entity, r.value, { 'Promoter': 'var(--accent)', 'FII': 'var(--c4)', 'DII': 'var(--c3)', 'Public': 'var(--faint)' }[r.entity] || 'var(--accent)', num(r.value) + '%'));
    host.append(card);
  }

  // news
  const news = S.news.data || [];
  const nsent = S.news_sentiment?.data;
  const nc = el('div', { class: 'card' }, [el('div', { class: 'card-head' }, [el('h3', {}, 'News'), nsent ? el('span', { class: `chip ${nsent.label.includes('bull') ? 'pos' : nsent.label.includes('bear') ? 'neg' : 'neu'}` }, nsent.label) : null])]);
  nc.append(el('div', {}, news.slice(0, 6).map((a) => articleRow(a))));
  host.append(nc);

  // actions
  host.append(el('div', { class: 'row', style: 'gap:8px' }, [
    el('button', { class: 'btn primary', style: 'flex:1', onclick: () => { ctx.closeDrawer(); ctx.navigate('chart', { symbol: data.symbol }); } }, 'Open chart'),
    el('button', { class: 'btn', onclick: () => { ctx.closeDrawer(); ctx.navigate('earnings', { symbol: data.symbol }); } }, 'Earnings'),
    el('button', { class: 'btn', onclick: () => { ctx.toggleWatch(data.symbol); toast(`${data.symbol} watchlist updated`, 'success'); } }, 'Watch'),
  ]));
}
function kvGrid(items) {
  const kv = el('div', { class: 'kv' });
  for (const [k, v] of items) kv.append(el('div', {}, [el('div', { class: 'k' }, k), el('div', { class: `v ${typeof v === 'string' && v.includes('%') ? cls(parseFloat(v)) : ''}` }, v)]));
  return kv;
}

// raw icon html -> node
function rawIcon(name, size = 16) { const s = el('span', { style: 'display:inline-flex', html: icon(name, size) }); return s; }

export const VIEWS = {
  overview: { label: 'Terminal', icon: 'terminal', render: overview },
  markets: { label: 'Markets', icon: 'markets', render: markets },
  chart: { label: 'Chart', icon: 'chart', render: chartView },
  screener: { label: 'Screener', icon: 'screener', render: screener },
  lab: { label: 'Lab', icon: 'lab', render: lab },
  earnings: { label: 'Earnings', icon: 'calendar', render: earnings },
  options: { label: 'Options', icon: 'options', render: optionsView },
  funds: { label: 'Funds', icon: 'funds', render: funds },
  news: { label: 'News', icon: 'news', render: news },
  account: { label: 'API', icon: 'api', render: account },
};
