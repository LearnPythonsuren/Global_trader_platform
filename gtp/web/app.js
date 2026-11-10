// Entry: boot, shell, router, command palette, symbol drawer and the live tape.
import { $, $$, el, esc, api, state, store, toast, icon, num, pct, signed, cls, arrow, debounce, sessionStatus } from './core.js';
import { VIEWS, renderCompany } from './views.js';

const app = $('#app');
const boot = $('#boot');
let leaveHooks = [];
let tapeTimer = null;

// ---- context passed to views ----------------------------------------------
const ctx = {
  params: {},
  $: (s) => $(s, $('#view')),
  navigate,
  onLeave: (fn) => leaveHooks.push(fn),
  openSymbol,
  closeDrawer,
  toast,
  watchlist: () => state.watchlist,
  toggleWatch,
  editWatchlist,
  changeKey,
};

// ---- boot ------------------------------------------------------------------
async function init() {
  applyTheme(store.get('gtp.theme') || 'dark');
  state.watchlist = store.get('gtp.watchlist') || ['RELIANCE', 'HDFCBANK', 'INFY', 'TCS', 'ICICIBANK', 'SBIN', 'BHARTIARTL', 'LT'];
  try {
    state.meta = await api('/v1/meta', { key: null });
    state.demo = state.meta.mode === 'demo';
  } catch (e) {
    boot.innerHTML = `<div class="boot-text down">Cannot reach the API: ${esc(e.message)}</div>`;
    return;
  }
  // choose key
  state.apiKey = store.get('gtp.key') || (state.demo ? state.meta.demo_key : null);
  if (!state.apiKey) { boot.remove(); app.hidden = false; buildShell(); return promptKey(); }
  await loadAccount();
  boot.remove(); app.hidden = false;
  buildShell();
  window.addEventListener('hashchange', route);
  route();
  startTape();
}

async function loadAccount() {
  try {
    [state.me, state.plans] = await Promise.all([api('/v1/me'), api('/v1/plans')]);
  } catch (e) {
    if (e.status === 401) { store.set('gtp.key', null); state.apiKey = null; }
  }
}

// ---- shell -----------------------------------------------------------------
function buildShell() {
  // mode badge
  const badge = $('#mode-badge');
  const sess = sessionStatus();
  badge.textContent = state.demo ? 'DEMO' : 'LIVE';
  badge.className = 'badge' + (state.demo ? '' : ' live');
  badge.title = state.demo ? 'Synthetic demo data' : 'Live market data';

  // rail
  const rail = $('#rail');
  rail.innerHTML = '';
  for (const [id, v] of Object.entries(VIEWS)) {
    rail.append(el('button', { class: 'rail-item', dataset: { view: id }, onclick: () => navigate(id) }, [
      el('span', { class: 'icon', html: icon(v.icon, 19) }),
      el('span', { class: 'rail-label' }, v.label),
    ]));
  }
  rail.append(el('div', { class: 'rail-foot' }, [
    el('div', {}, sess.label),
    el('div', { style: 'margin-top:3px' }, state.demo ? 'Demo data — not real quotes' : 'Live via Global Datafeeds'),
  ]));

  // top actions
  const cmdIco = $('#cmd-trigger .cmd-ico');
  cmdIco.style.webkitMask = cmdIco.style.mask = `center/contain no-repeat url("data:image/svg+xml,${encodeURIComponent(icon('search', 15))}")`;
  $('#cmd-trigger').onclick = openPalette;
  $('#theme-toggle').onclick = () => applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark', true);
  updateThemeIcon();
  const acct = $('#account-btn');
  acct.innerHTML = '';
  acct.append(el('span', { class: 'plan-dot' }), el('span', { class: 'account-name' }, state.me?.plan?.name || 'Account'));
  acct.onclick = () => navigate('account');

  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); openPalette(); }
    if (e.key === 'Escape') { closePalette(); closeDrawer(); }
  });
}

// ---- router ----------------------------------------------------------------
function parseHash() {
  const raw = location.hash.replace(/^#\/?/, '');
  const [view, ...rest] = raw.split('/');
  const params = {};
  if (rest[0]) params.symbol = decodeURIComponent(rest[0]);
  return { view: VIEWS[view] ? view : 'overview', params };
}
function navigate(view, params = {}) {
  const sym = params.symbol ? '/' + encodeURIComponent(params.symbol) : '';
  const next = `#${view}${sym}`;
  if (location.hash === next) route(); else location.hash = next;
}
let routeEpoch = 0;
async function route() {
  const epoch = ++routeEpoch;                       // supersede any earlier in-flight render
  const { view, params } = parseHash();
  ctx.params = params;
  for (const fn of leaveHooks) { try { fn(); } catch {} }
  leaveHooks = [];
  $$('.rail-item').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  const host = $('#view');
  // Render into a fresh container and swap it in. A view that resolves late then appends to its
  // own now-detached container instead of leaking into whatever view is current.
  const page = el('div', { class: 'view-page' });
  host.replaceChildren(page);
  host.scrollTop = 0; window.scrollTo(0, 0);
  try { await VIEWS[view].render(page, ctx); }
  catch (e) {
    if (epoch === routeEpoch) { page.replaceChildren(el('div', { class: 'empty down' }, `View error: ${esc(e.message)}`)); }
    console.error(e);
  }
  if (epoch === routeEpoch) host.focus({ preventScroll: true });
}

// ---- theme -----------------------------------------------------------------
function applyTheme(theme, persist) {
  document.documentElement.dataset.theme = theme;
  if (persist) { store.set('gtp.theme', theme); updateThemeIcon(); startTape(); }
}
function updateThemeIcon() {
  const dark = document.documentElement.dataset.theme === 'dark';
  $('#theme-toggle').innerHTML = icon(dark ? 'sun' : 'moon', 17);
}

// ---- live tape -------------------------------------------------------------
async function startTape() {
  if (tapeTimer) clearInterval(tapeTimer);
  const tape = $('#tape');
  async function tick() {
    try {
      const idx = state.meta.indices || [];
      const wl = state.watchlist.slice(0, 8);
      const [iq, sq] = await Promise.all([
        idx.length ? api(`/v1/quotes?symbols=${idx.map(encodeURIComponent).join(',')}&exchange=${encodeURIComponent(state.meta.index_exchange)}`) : [],
        wl.length ? api(`/v1/quotes?symbols=${wl.map(encodeURIComponent).join(',')}`) : [],
      ]);
      const items = [...iq, ...sq].filter((q) => q && q.ltp != null);
      if (!items.length) return;
      const make = () => el('div', { class: 'tape-track' }, items.concat(items).map((q) => el('div', { class: 'tape-item' }, [
        el('span', { class: 'tape-sym' }, q.symbol),
        el('span', { class: 'tape-val mono' }, num(q.ltp)),
        el('span', { class: `tape-chg mono ${cls(q.change_pct)}` }, `${arrow(q.change_pct)}${pct(q.change_pct)}`),
      ])));
      tape.innerHTML = ''; tape.append(make());
    } catch { /* keep last tape */ }
  }
  tick();
  tapeTimer = setInterval(tick, 6000);
}

// ---- drawer ----------------------------------------------------------------
let drawerEls = null;
function ensureDrawer() {
  if (drawerEls) return drawerEls;
  const scrim = el('div', { class: 'scrim', onclick: closeDrawer });
  const body = el('div', { class: 'drawer-body' });
  const title = el('div', { class: 'row', style: 'gap:8px;font-weight:600' }, 'Company');
  const drawer = el('div', { class: 'drawer', role: 'dialog', 'aria-label': 'Company details' }, [
    el('div', { class: 'drawer-head' }, [title, el('button', { class: 'icon-btn', onclick: closeDrawer, 'aria-label': 'Close', html: icon('close', 16) })]),
    body,
  ]);
  document.body.append(scrim, drawer);
  drawerEls = { scrim, drawer, body, title };
  return drawerEls;
}
function openSymbol(symbol) {
  symbol = (symbol || '').toUpperCase();
  if (!symbol) return;
  const { scrim, drawer, body, title } = ensureDrawer();
  title.textContent = symbol;
  requestAnimationFrame(() => { scrim.classList.add('in'); drawer.classList.add('in'); });
  renderCompany(body, symbol, ctx);
}
function closeDrawer() {
  if (!drawerEls) return;
  drawerEls.scrim.classList.remove('in'); drawerEls.drawer.classList.remove('in');
}

// ---- command palette -------------------------------------------------------
let paletteEls = null, paletteItems = [], paletteIdx = 0;
function openPalette() {
  if (!paletteEls) buildPalette();
  paletteEls.scrim.hidden = false;
  requestAnimationFrame(() => paletteEls.scrim.classList.add('in'));
  paletteEls.input.value = ''; paletteEls.input.focus();
  renderPalette('');
}
function closePalette() {
  if (!paletteEls || paletteEls.scrim.hidden) return;
  paletteEls.scrim.classList.remove('in');
  setTimeout(() => { paletteEls.scrim.hidden = true; }, 160);
}
function buildPalette() {
  const input = el('input', { placeholder: 'Search symbols, jump to a view…', autocomplete: 'off', spellcheck: 'false' });
  const list = el('div', { class: 'palette-list' });
  const palette = el('div', { class: 'palette' }, [
    el('div', { class: 'palette-input' }, [el('span', { class: 'ico', html: icon('search', 18) }), input, el('kbd', {}, 'esc')]),
    list,
  ]);
  const scrim = el('div', { class: 'palette-scrim', hidden: true, onclick: (e) => { if (e.target === scrim) closePalette(); } }, palette);
  document.body.append(scrim);
  paletteEls = { scrim, input, list };
  input.addEventListener('input', debounce(() => renderPalette(input.value), 160));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); paletteIdx = Math.min(paletteItems.length - 1, paletteIdx + 1); highlight(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); paletteIdx = Math.max(0, paletteIdx - 1); highlight(); }
    else if (e.key === 'Enter') { e.preventDefault(); paletteItems[paletteIdx]?.action(); }
  });
}
function highlight() {
  $$('.palette-item', paletteEls.list).forEach((n, i) => n.classList.toggle('active', i === paletteIdx));
  $$('.palette-item', paletteEls.list)[paletteIdx]?.scrollIntoView({ block: 'nearest' });
}
async function renderPalette(q) {
  const list = paletteEls.list;
  paletteItems = []; paletteIdx = 0;
  const views = Object.entries(VIEWS).filter(([id, v]) => !q || v.label.toLowerCase().includes(q.toLowerCase()) || id.includes(q.toLowerCase()));
  const groups = [];
  if (views.length) groups.push(['Views', views.map(([id, v]) => ({
    icon: v.icon, label: v.label, sub: 'view', action: () => { closePalette(); navigate(id); },
  }))]);

  render(groups);   // show views instantly
  if (q && q.trim().length >= 1) {
    try {
      const res = await api(`/v1/search?q=${encodeURIComponent(q.trim())}`);
      const syms = res.slice(0, 8).map((r) => ({
        icon: 'dot', label: r.Identifier, sub: r.Name || r.Sector || '', action: () => { closePalette(); openSymbol(r.Identifier); },
      }));
      const g = [...groups];
      if (syms.length) g.unshift(['Symbols', syms]);
      render(g);
    } catch { /* keep views */ }
  }

  function render(gs) {
    list.innerHTML = '';
    paletteItems = [];
    if (!gs.length) { list.append(el('div', { class: 'empty' }, 'No matches')); return; }
    for (const [name, items] of gs) {
      list.append(el('div', { class: 'palette-group' }, name));
      for (const it of items) {
        const node = el('div', { class: 'palette-item', onclick: it.action, onmouseenter: () => { paletteIdx = paletteItems.indexOf(it); highlight(); } }, [
          el('span', { class: 'pi-ico', html: icon(it.icon, 16) }),
          el('span', {}, it.label),
          it.sub ? el('span', { class: 'pi-sub' }, it.sub) : null,
        ]);
        list.append(node); paletteItems.push(it);
        it._node = node;
      }
    }
    // reattach nodes to items for highlight()
    const nodes = $$('.palette-item', list);
    paletteItems.forEach((it, i) => { it._node = nodes[i]; });
    highlight();
  }
}

// ---- watchlist & key -------------------------------------------------------
function toggleWatch(symbol) {
  symbol = symbol.toUpperCase();
  const i = state.watchlist.indexOf(symbol);
  if (i >= 0) state.watchlist.splice(i, 1); else state.watchlist.unshift(symbol);
  store.set('gtp.watchlist', state.watchlist);
}
function editWatchlist() {
  const v = prompt('Watchlist symbols (comma-separated):', state.watchlist.join(', '));
  if (v == null) return;
  state.watchlist = v.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean).slice(0, 12);
  store.set('gtp.watchlist', state.watchlist);
  if (parseHash().view === 'overview') route();
  startTape();
}
function changeKey() {
  const v = prompt('API key:', state.apiKey || '');
  if (!v) return;
  store.set('gtp.key', v.trim()); state.apiKey = v.trim();
  location.reload();
}
async function promptKey() {
  const host = $('#view');
  $('#rail').innerHTML = '';
  host.innerHTML = '';
  host.append(el('div', { class: 'card', style: 'max-width:460px;margin:60px auto' }, [
    el('h3', {}, 'Enter your API key'),
    el('div', { class: 'mini muted', style: 'margin-bottom:12px' }, 'This server runs in live mode. Paste a customer API key to continue.'),
    (() => {
      const input = el('input', { class: 'input mono', style: 'width:100%', placeholder: 'gtp_…' });
      const btn = el('button', { class: 'btn primary', style: 'margin-top:10px', onclick: () => { if (input.value.trim()) { store.set('gtp.key', input.value.trim()); location.reload(); } } }, 'Continue');
      return el('div', {}, [input, btn]);
    })(),
  ]));
}

init();
