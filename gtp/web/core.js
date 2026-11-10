// Core: API client, shared state, formatting and DOM helpers for the dashboard.

export const state = {
  apiKey: null,
  meta: null,            // /v1/meta
  me: null,              // /v1/me
  plans: [],
  demo: true,
  watchlist: [],
};

// ---- storage (per-viewer convenience only; always guarded) -----------------
export const store = {
  get(k, fallback = null) {
    try { const v = localStorage.getItem(k); return v === null ? fallback : JSON.parse(v); }
    catch { return fallback; }
  },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
};

// ---- DOM helpers -----------------------------------------------------------
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k === 'text') node.textContent = v;
    else if (k === 'dataset') Object.assign(node.dataset, v);
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null || c === false) continue;
    node.append(c.nodeType ? c : document.createTextNode(c));
  }
  return node;
}

export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

// ---- icons (inline SVG, currentColor) --------------------------------------
const ICONS = {
  terminal: 'M4 5h16v14H4z|M7 9l3 3-3 3|M13 15h4',
  markets: 'M4 19V5|M4 19h16|M8 16l3-4 3 2 4-6',
  chart: 'M4 19V5|M4 19h16|M7 15v-3|M11 15V9|M15 15v-5|M19 15V7',
  screener: 'M4 6h16|M7 12h10|M10 18h4',
  lab: 'M9 3h6|M10 3v5l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3',
  options: 'M4 7h16|M4 12h16|M4 17h16|M9 4v16',
  funds: 'M12 3v18|M5 8h9a3 3 0 0 1 0 6H7|M5 14h9a3 3 0 0 1 0 6',
  news: 'M4 5h13v14H6a2 2 0 0 1-2-2zM17 8h3v9a2 2 0 0 1-2 2|M7 8h7M7 11h7M7 14h5',
  api: 'M8 7l-5 5 5 5|M16 7l5 5-5 5|M13 5l-2 14',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4',
  sun: 'M12 6a6 6 0 1 0 0 12 6 6 0 0 0 0-12|M12 1v2|M12 21v2|M4 4l1.5 1.5|M18.5 18.5L20 20|M1 12h2|M21 12h2|M4 20l1.5-1.5|M18.5 5.5L20 4',
  moon: 'M20 14a8 8 0 1 1-9.8-10 7 7 0 0 0 9.8 10z',
  close: 'M6 6l12 12|M18 6L6 18',
  plus: 'M12 5v14|M5 12h14',
  bolt: 'M13 2L4 14h7l-2 8 9-12h-7z',
  star: 'M12 3l2.9 5.9 6.5.9-4.7 4.6 1.1 6.5L12 18.3 6.2 21l1.1-6.5L2.6 9.8l6.5-.9z',
  arrow: 'M5 12h14|M13 6l6 6-6 6',
  dot: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z',
  external: 'M14 5h5v5|M19 5l-8 8|M18 14v4a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h4',
  filter: 'M4 5h16l-6 8v5l-4 2v-7z',
  refresh: 'M4 12a8 8 0 0 1 14-5l2 2M20 5v4h-4|M20 12a8 8 0 0 1-14 5l-2-2M4 19v-4h4',
};
export function icon(name, size = 18) {
  const paths = (ICONS[name] || '').split('|').map((d) =>
    `<path d="${d}" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>`).join('');
  return `<svg viewBox="0 0 24 24" width="${size}" height="${size}" aria-hidden="true" class="icon">${paths}</svg>`;
}

// ---- formatting ------------------------------------------------------------
const INR0 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });
const INR2 = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function num(v, dp = 2) {
  if (v == null || v === '' || Number.isNaN(Number(v))) return '–';
  return (dp === 0 ? INR0 : INR2).format(Number(v));
}
export function signed(v, dp = 2, suffix = '') {
  if (v == null || Number.isNaN(Number(v))) return '–';
  const n = Number(v);
  return `${n > 0 ? '+' : n < 0 ? '−' : ''}${num(Math.abs(n), dp)}${suffix}`;
}
export function pct(v, dp = 2) { return signed(v, dp, '%'); }
export const cls = (v) => (v > 0 ? 'up' : v < 0 ? 'down' : 'flat');
export const arrow = (v) => (v > 0 ? '▲' : v < 0 ? '▼' : '·');

// Compact Indian money. `value` and market caps from the API are in rupees unless noted.
export function money(v, { crore = false } = {}) {
  if (v == null || Number.isNaN(Number(v))) return '–';
  let n = Number(v);
  if (crore) n *= 1e7;                       // ratios.market_cap is already in crore
  const abs = Math.abs(n);
  if (abs >= 1e7) return `₹${num(n / 1e7, abs >= 1e9 ? 0 : 2)} Cr`;
  if (abs >= 1e5) return `₹${num(n / 1e5, 2)} L`;
  if (abs >= 1e3) return `₹${num(n / 1e3, 1)} K`;
  return `₹${num(n, 0)}`;
}
export function qty(v) {
  if (v == null || Number.isNaN(Number(v))) return '–';
  const n = Number(v);
  if (n >= 1e7) return `${num(n / 1e7, 2)} Cr`;
  if (n >= 1e5) return `${num(n / 1e5, 2)} L`;
  if (n >= 1e3) return `${num(n / 1e3, 1)} K`;
  return num(n, 0);
}

export function timeAgo(iso) {
  if (!iso) return '';
  const t = typeof iso === 'number' ? iso * 1000 : Date.parse(iso.replace(' ', 'T'));
  if (Number.isNaN(t)) return '';
  const s = (Date.now() - t) / 1000;
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
export function clock(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

// ---- NSE session clock (IST), from /v1/meta -------------------------------
export function sessionStatus() {
  const s = state.meta?.session;
  if (!s) return { open: false, label: '—' };
  const now = new Date();
  const ist = new Date(now.getTime() + (330 + now.getTimezoneOffset()) * 60000);
  const day = ist.getDay(); // 0 Sun .. 6 Sat
  const mins = ist.getHours() * 60 + ist.getMinutes();
  const [oh, om] = s.open.split(':').map(Number);
  const [ch, cm] = s.close.split(':').map(Number);
  const open = (s.weekdays || [1, 2, 3, 4, 5]).includes(day) && mins >= oh * 60 + om && mins < ch * 60 + cm;
  return { open, label: open ? 'Market open' : 'Market closed', ist };
}

// ---- API client ------------------------------------------------------------
export class ApiError extends Error {
  constructor(status, detail) { super(detail || `HTTP ${status}`); this.status = status; this.detail = detail; }
}

export async function api(path, { method = 'GET', body = null, key = undefined } = {}) {
  const headers = { 'Accept': 'application/json' };
  const apiKey = key === undefined ? state.apiKey : key;
  if (apiKey) headers['X-API-Key'] = apiKey;
  if (body != null) headers['Content-Type'] = 'application/json';
  const res = await fetch(path, { method, headers, body: body != null ? JSON.stringify(body) : null });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const detail = (data && typeof data === 'object' && data.detail) || (typeof data === 'string' ? data : null);
    throw new ApiError(res.status, detail);
  }
  return data;
}

// ---- toast -----------------------------------------------------------------
let toastHost;
export function toast(msg, kind = 'info', ms = 4200) {
  if (!toastHost) { toastHost = el('div', { class: 'toasts', role: 'status', 'aria-live': 'polite' }); document.body.append(toastHost); }
  const t = el('div', { class: `toast ${kind}`, html: `<span>${esc(msg)}</span>` });
  toastHost.append(t);
  requestAnimationFrame(() => t.classList.add('in'));
  const kill = () => { t.classList.remove('in'); setTimeout(() => t.remove(), 220); };
  t.addEventListener('click', kill);
  if (ms) setTimeout(kill, ms);
}

// ---- small reactive helpers ------------------------------------------------
export function debounce(fn, ms = 250) {
  let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); };
}
export function throttleRAF(fn) {
  let queued = false, lastArgs;
  return (...a) => { lastArgs = a; if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; fn(...lastArgs); }); };
}
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Resolve a readable company name/sector for a symbol from whatever we have cached.
export function sentimentChipClass(label) {
  const l = (label || '').toLowerCase();
  if (l.includes('bull') || l === 'positive') return 'pos';
  if (l.includes('bear') || l === 'negative') return 'neg';
  return 'neu';
}
