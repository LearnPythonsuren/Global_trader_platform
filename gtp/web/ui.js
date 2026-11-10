// Reusable UI builders shared across views.
import { el, esc, num, pct, signed, cls, arrow, money, timeAgo, sentimentChipClass, icon } from './core.js';
import { sparkline } from './charts.js';

// ---- sparkline cells -------------------------------------------------------
const SPARKS = new WeakMap();
export function spark(values, opts = {}) {
  const c = el('canvas', { class: 'spark' });
  SPARKS.set(c, { values, opts });
  return c;
}
// Draw every pending sparkline under `root` once it is attached and sized.
export function realizeSparks(root) {
  requestAnimationFrame(() => {
    for (const c of root.querySelectorAll('canvas.spark')) {
      const s = SPARKS.get(c);
      if (s) sparkline(c, s.values, s.opts);
    }
  });
}

// ---- table -----------------------------------------------------------------
// columns: [{ head, cell(row)->node|string, cls, num }]
export function table(columns, rows, { onRow } = {}) {
  const thead = el('tr', {}, columns.map((c) => el('th', { class: c.cls || '' }, c.head)));
  const body = rows.map((row) => {
    const tr = el('tr', onRow ? { class: 'clickable', onclick: () => onRow(row) } : {},
      columns.map((c) => {
        const v = c.cell(row);
        return el('td', { class: c.cls || '' }, v && v.nodeType ? v : (v == null ? '–' : String(v)));
      }));
    return tr;
  });
  const wrap = el('div', { class: 'tbl-wrap' }, [
    el('table', { class: 'tbl' }, [el('thead', {}, thead), el('tbody', {}, body.length ? body : el('tr', {}, el('td', { colspan: columns.length, class: 'empty' }, 'No rows')))]),
  ]);
  return wrap;
}

// change pill
export function changePill(v) {
  if (v == null) return el('span', { class: 'muted' }, '–');
  return el('span', { class: `pct-pill ${cls(v)}` }, pct(v));
}
export function symCell(symbol, name) {
  return el('div', { class: 'sym-cell' }, [
    el('b', { class: 'mono' }, symbol),
    name ? el('span', { class: 'sym-name' }, name) : null,
  ]);
}

// ---- stat tile -------------------------------------------------------------
export function stat(k, v, d, dCls) {
  return el('div', { class: 'stat' }, [
    el('div', { class: 'k' }, k),
    el('div', { class: 'v' }, v),
    d != null ? el('div', { class: `d ${dCls || ''}` }, d) : null,
  ]);
}

// ---- async section ---------------------------------------------------------
// Renders a spinner, awaits loader(), then paints via render(data, host) or shows the error.
export async function fill(host, loader, render) {
  host.innerHTML = '<div class="empty"><span class="spinner"></span></div>';
  try {
    const data = await loader();
    host.innerHTML = '';
    render(data, host);
    realizeSparks(host);
  } catch (e) {
    host.innerHTML = '';
    host.append(el('div', { class: 'empty' }, [
      el('div', { class: 'down', style: 'margin-bottom:6px' }, 'Could not load'),
      el('div', { class: 'mini muted' }, e.detail || e.message || String(e)),
    ]));
  }
}

// ---- signals ---------------------------------------------------------------
export function signalRow(s) {
  return el('div', { class: `signal ${s.tone}` }, [
    el('span', { class: 'dot' }),
    el('div', {}, [
      el('span', {}, s.text),
      el('span', { class: 'faint mini', style: 'margin-left:6px;text-transform:capitalize' }, s.type),
    ]),
  ]);
}

// ---- news ------------------------------------------------------------------
export function articleRow(a, { flash = false } = {}) {
  const chip = el('span', { class: `chip ${sentimentChipClass(a.sentiment)}` }, a.sentiment || 'neutral');
  const head = el('div', { class: 'a-head' }, [chip, el('span', { class: 'chip' }, a.article_type || 'News')]);
  const title = a.link
    ? el('a', { class: 'a-title', href: a.link, target: '_blank', rel: 'noopener noreferrer' }, a.specific_title || a.title)
    : el('div', { class: 'a-title' }, a.specific_title || a.title);
  const meta = el('div', { class: 'a-meta' }, [
    a.symbol ? el('b', { class: 'mono' }, a.symbol) : (a.company && a.company !== 'N/A' ? a.company : null),
    el('span', {}, a.source || ''),
    el('span', {}, timeAgo(a.date)),
  ]);
  return el('div', { class: `article ${flash ? 'flash' : ''}` }, [head, title,
    a.summary ? el('div', { class: 'mini muted', style: 'margin-top:3px' }, a.summary.replace(/^\[DEMO\]\s*/, '')) : null, meta]);
}

export function sentimentBar(s) {
  if (!s || !s.articles) return el('div', { class: 'mini muted' }, 'No coverage');
  const total = s.articles;
  const seg = (n, c) => n ? el('span', { style: `flex:${n};background:${c}` }) : null;
  const bar = el('div', { class: 'row', style: 'height:7px;border-radius:4px;overflow:hidden;gap:0' }, [
    seg(s.positive, 'var(--up)'), seg(s.neutral, 'var(--faint)'), seg(s.negative, 'var(--down)'),
  ]);
  return el('div', { class: 'stack' }, [
    el('div', { class: 'row spread' }, [
      el('span', { class: `chip ${sentimentChipClass(s.label)}` }, `${s.label} · ${signed(s.net_score)}`),
      el('span', { class: 'mini muted mono' }, `${s.positive}↑ ${s.negative}↓ of ${total}`),
    ]),
    bar,
  ]);
}

// ---- horizontal bar (label · bar · value) ----------------------------------
export function labelledBar(label, widthPct, color, display) {
  return el('div', { style: 'display:grid;grid-template-columns:minmax(90px,140px) 1fr auto;gap:10px;align-items:center;margin-bottom:7px' }, [
    el('span', { class: 'mini', style: 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap' }, label),
    el('div', { class: 'hbar-track' }, el('div', { class: 'hbar', style: `width:${Math.max(1, Math.min(100, widthPct))}%;background:${color || 'var(--accent)'}` })),
    el('span', { class: 'mono mini', style: 'min-width:58px;text-align:right' }, display),
  ]);
}

export { el, esc, num, pct, signed, cls, arrow, money, icon };
