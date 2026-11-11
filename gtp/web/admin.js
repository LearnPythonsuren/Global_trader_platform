// GTP Admin console — issue and manage customer API keys.
// Gated by the admin token (X-Admin-Token); the token lives only in this tab's
// sessionStorage and is cleared on Lock. No inline scripts (CSP script-src 'self').

const TOKEN_KEY = 'gtp.admin';
const root = document.getElementById('admin');
const toastHost = document.getElementById('toast');

let token = sget(TOKEN_KEY);
let plans = [];

// ---- tiny DOM + storage helpers -------------------------------------------
function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === 'class') node.className = v;
    else if (k === 'html') node.innerHTML = v;
    else if (k === 'text') node.textContent = v;
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null || c === false) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}
function sget(k) { try { const v = sessionStorage.getItem(k); return v == null ? null : JSON.parse(v); } catch { return null; } }
function sset(k, v) { try { v == null ? sessionStorage.removeItem(k) : sessionStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } }
function lget(k) { try { const v = localStorage.getItem(k); return v == null ? null : JSON.parse(v); } catch { return null; } }

function toast(msg, kind = 'good') {
  const t = el('div', { class: kind === 'bad' ? 'bad' : 'good' }, msg);
  toastHost.append(t);
  setTimeout(() => t.remove(), kind === 'bad' ? 6000 : 3500);
}
function fmtDate(ts) { try { return new Date(ts * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }); } catch { return '–'; } }

async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast('Copied to clipboard'); }
  catch { toast('Select the key and copy it manually', 'bad'); }
}

// ---- admin API client ------------------------------------------------------
async function adminFetch(path, { method = 'GET', body = null } = {}) {
  const headers = { 'X-Admin-Token': token || '' };
  if (body != null) headers['Content-Type'] = 'application/json';
  const res = await fetch(path, { method, headers, body: body != null ? JSON.stringify(body) : null });
  let data = null;
  try { data = await res.json(); } catch { /* no body */ }
  if (!res.ok) throw { status: res.status, detail: (data && (data.detail || data.message)) || `HTTP ${res.status}` };
  return data;
}

// ---- theme (follow the dashboard's saved preference) -----------------------
function applyTheme() {
  const t = lget('gtp.theme') || 'dark';
  document.documentElement.dataset.theme = t === 'light' ? 'light' : 'dark';
}
function toggleTheme() {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('gtp.theme', JSON.stringify(next)); } catch { /* ignore */ }
}

// ---- gate (enter the admin token) ------------------------------------------
function renderGate(message) {
  root.replaceChildren(el('div', { class: 'adm-gate' }, [
    el('div', { class: 'adm-brand', style: 'justify-content:center;margin-bottom:18px;font-size:18px' },
      [el('span', { class: 'mk' }, '▲'), 'Global Trader ', el('small', {}, 'Admin')]),
    el('div', { class: 'card' }, [
      el('h3', { style: 'margin:0 0 4px' }, 'Admin access'),
      el('p', { class: 'mini faint', style: 'margin:0 0 14px' }, 'Enter the admin token (GTP_ADMIN_TOKEN) to manage customer keys.'),
      message ? el('div', { class: 'empty down', style: 'margin-bottom:12px' }, message) : null,
      (() => {
        const input = el('input', { class: 'input mono', type: 'password', style: 'width:100%', placeholder: 'admin token', autocomplete: 'off' });
        const submit = () => { const v = input.value.trim(); if (!v) return; token = v; sset(TOKEN_KEY, v); boot(); };
        const form = el('form', { onsubmit: (e) => { e.preventDefault(); submit(); } }, [
          input,
          el('button', { class: 'btn primary', type: 'submit', style: 'margin-top:12px;width:100%' }, 'Unlock'),
        ]);
        setTimeout(() => input.focus(), 30);
        return form;
      })(),
    ]),
  ]));
}

// ---- console ---------------------------------------------------------------
function header() {
  return el('div', { class: 'adm-top' }, [
    el('div', { class: 'adm-brand' }, [el('span', { class: 'mk' }, '▲'), 'Global Trader ', el('small', {}, 'Admin · Customer Keys')]),
    el('div', { class: 'row', style: 'gap:8px' }, [
      el('a', { class: 'btn', href: '/', title: 'Open the dashboard' }, 'Dashboard'),
      el('button', { class: 'btn', onclick: toggleTheme }, 'Theme'),
      el('button', { class: 'btn', onclick: () => { token = null; sset(TOKEN_KEY, null); renderGate(null); } }, 'Lock'),
    ]),
  ]);
}

function revealKey(label, key) {
  return el('div', { class: 'keybox' }, [
    el('div', { class: 'mini faint', style: 'margin-bottom:6px' }, `${label} — shown once. Store it now; it cannot be retrieved later.`),
    el('div', { class: 'row spread', style: 'gap:10px;align-items:center;flex-wrap:wrap' }, [
      el('span', { class: 'k' }, key),
      el('button', { class: 'btn primary', onclick: () => copy(key) }, 'Copy'),
    ]),
  ]);
}

function planSelect(current, onChange) {
  const sel = el('select', { class: 'input', onchange: onChange ? (e) => onChange(e.target.value) : null },
    plans.map((p) => el('option', { value: p.id, selected: p.id === current || null }, `${p.name} · ₹${p.price_inr_month}/mo`)));
  return sel;
}

async function createCustomer(card, name, email, plan) {
  try {
    const out = await adminFetch('/admin/customers', { method: 'POST', body: { name, email, plan } });
    const existing = card.querySelector('.keybox'); if (existing) existing.remove();
    card.append(revealKey(`New key for ${out.customer.name}`, out.api_key));
    toast(`Created ${out.customer.name} (${out.customer.plan})`);
    loadCustomers();
  } catch (e) { toast(e.detail || 'Could not create customer', 'bad'); if (e.status === 401) renderGate('Session expired — re-enter the admin token.'); }
}

function createCard() {
  const name = el('input', { class: 'input', placeholder: 'Acme Capital' });
  const email = el('input', { class: 'input', type: 'email', placeholder: 'ops@acme.com' });
  const planHost = el('div', { class: 'field' }, [el('label', {}, 'Plan'), planSelect('pro')]);
  const card = el('div', { class: 'card' }, [
    el('h3', { style: 'margin:0 0 12px' }, 'Issue a new customer key'),
    el('form', { class: 'create-row', onsubmit: (e) => {
      e.preventDefault();
      const n = name.value.trim(), em = email.value.trim();
      if (!n || !em) { toast('Name and email are required', 'bad'); return; }
      createCustomer(card, n, em, planHost.querySelector('select').value);
      name.value = ''; email.value = '';
    } }, [
      el('div', { class: 'field' }, [el('label', {}, 'Name'), name]),
      el('div', { class: 'field' }, [el('label', {}, 'Email'), email]),
      planHost,
      el('button', { class: 'btn primary', type: 'submit' }, 'Create key'),
    ]),
  ]);
  return card;
}

async function rotate(c, detailHost) {
  if (!confirm(`Rotate the API key for ${c.name}? Their current key stops working immediately.`)) return;
  try {
    const out = await adminFetch(`/admin/customers/${c.id}/rotate-key`, { method: 'POST' });
    detailHost.replaceChildren(revealKey(`Rotated key for ${c.name}`, out.api_key));
    toast(`Rotated key for ${c.name}`);
    loadCustomers();
  } catch (e) { toast(e.detail || 'Rotate failed', 'bad'); }
}

async function setPlan(c, plan) {
  try { await adminFetch(`/admin/customers/${c.id}`, { method: 'PATCH', body: { plan } }); toast(`${c.name} → ${plan}`); }
  catch (e) { toast(e.detail || 'Update failed', 'bad'); loadCustomers(); }
}

async function toggleActive(c) {
  try { await adminFetch(`/admin/customers/${c.id}`, { method: 'PATCH', body: { active: !c.active } }); toast(`${c.name} ${c.active ? 'deactivated' : 'activated'}`); loadCustomers(); }
  catch (e) { toast(e.detail || 'Update failed', 'bad'); }
}

async function showUsage(c, detailHost) {
  detailHost.replaceChildren(el('div', { class: 'card' }, el('div', { class: 'empty' }, [el('span', { class: 'spinner' })])));
  try {
    const rows = await adminFetch(`/admin/customers/${c.id}/usage?days=30`);
    const total = rows.reduce((s, r) => s + (r.count || 0), 0);
    const byEndpoint = {};
    for (const r of rows) byEndpoint[r.endpoint] = (byEndpoint[r.endpoint] || 0) + r.count;
    const top = Object.entries(byEndpoint).sort((a, b) => b[1] - a[1]).slice(0, 12);
    detailHost.replaceChildren(el('div', { class: 'card' }, [
      el('div', { class: 'row spread', style: 'align-items:center;flex-wrap:wrap;gap:8px' }, [
        el('h3', { style: 'margin:0' }, [`Usage · ${c.name} `, el('span', { class: 'mini faint' }, 'last 30 days')]),
        el('span', { class: 'chip mono' }, `${total.toLocaleString()} requests`),
      ]),
      top.length
        ? el('table', { class: 'tbl', style: 'margin-top:12px' }, [
            el('thead', {}, el('tr', {}, [el('th', {}, 'Endpoint'), el('th', {}, 'Requests')])),
            el('tbody', {}, top.map(([ep, n]) => el('tr', {}, [el('td', { class: 'mono mini' }, ep), el('td', { class: 'mono' }, n.toLocaleString())]))),
          ])
        : el('div', { class: 'empty', style: 'margin-top:10px' }, 'No requests recorded yet.'),
    ]));
  } catch (e) { detailHost.replaceChildren(el('div', { class: 'card' }, el('div', { class: 'empty down' }, e.detail || 'Could not load usage'))); }
}

function customerRow(c, detailHost) {
  const prefix = c.key_prefix ? `${c.key_prefix}…` : '—';
  return el('tr', {}, [
    el('td', { class: 'mono mini muted' }, c.id),
    el('td', {}, [el('div', {}, c.name), el('div', { class: 'mini faint' }, c.email)]),
    el('td', {}, planSelect(c.plan, (v) => setPlan(c, v))),
    el('td', { class: 'mono mini' }, prefix),
    el('td', {}, el('button', { class: `pill ${c.active ? 'on' : 'off'}`, onclick: () => toggleActive(c), title: 'Toggle active' }, c.active ? 'Active' : 'Inactive')),
    el('td', { class: 'mini muted' }, fmtDate(c.created_at)),
    el('td', {}, el('div', { class: 'inline-actions' }, [
      el('button', { class: 'btn', onclick: () => rotate(c, detailHost) }, 'Rotate'),
      el('button', { class: 'btn', onclick: () => showUsage(c, detailHost) }, 'Usage'),
    ])),
  ]);
}

async function loadCustomers() {
  const listHost = document.getElementById('cust-list');
  if (!listHost) return;
  listHost.replaceChildren(el('div', { class: 'empty' }, el('span', { class: 'spinner' })));
  try {
    const rows = await adminFetch('/admin/customers');
    const detailHost = document.getElementById('cust-detail');
    const countEl = document.getElementById('cust-count');
    if (countEl) countEl.textContent = `${rows.length} customer${rows.length === 1 ? '' : 's'}`;
    if (!rows.length) { listHost.replaceChildren(el('div', { class: 'empty' }, 'No customers yet — issue the first key above.')); return; }
    listHost.replaceChildren(el('table', { class: 'tbl' }, [
      el('thead', {}, el('tr', {}, ['ID', 'Customer', 'Plan', 'Key', 'Status', 'Created', ''].map((h) => el('th', {}, h)))),
      el('tbody', {}, rows.map((c) => customerRow(c, detailHost))),
    ]));
  } catch (e) {
    if (e.status === 401) { renderGate('Session expired — re-enter the admin token.'); return; }
    listHost.replaceChildren(el('div', { class: 'empty down' }, e.detail || 'Could not load customers'));
  }
}

function renderConsole() {
  root.replaceChildren(
    header(),
    createCard(),
    el('div', { class: 'card pad0', style: 'margin-top:16px' }, [
      el('div', { class: 'row spread', style: 'padding:14px 16px;align-items:center;flex-wrap:wrap;gap:8px' }, [
        el('h3', { style: 'margin:0' }, 'Customers'),
        el('div', { class: 'row', style: 'gap:10px;align-items:center' }, [
          el('span', { id: 'cust-count', class: 'mini faint' }, ''),
          el('button', { class: 'btn', onclick: loadCustomers }, 'Refresh'),
        ]),
      ]),
      el('div', { id: 'cust-list' }, el('div', { class: 'empty' }, el('span', { class: 'spinner' }))),
    ]),
    el('div', { id: 'cust-detail', style: 'margin-top:16px' }),
  );
  loadCustomers();
}

// ---- boot ------------------------------------------------------------------
async function boot() {
  applyTheme();
  if (!token) { renderGate(null); return; }
  root.replaceChildren(el('div', { class: 'empty' }, el('span', { class: 'spinner' })));
  try {
    plans = await fetch('/v1/plans').then((r) => r.json());
    if (!Array.isArray(plans)) plans = [];
  } catch { plans = []; }
  try {
    await adminFetch('/admin/customers'); // validates the token
    renderConsole();
  } catch (e) {
    if (e.status === 503) { renderGate('Admin API is disabled. Set GTP_ADMIN_TOKEN in your deployment and redeploy.'); return; }
    if (e.status === 401) { token = null; sset(TOKEN_KEY, null); renderGate('Invalid admin token.'); return; }
    renderGate(e.detail || 'Could not reach the admin API.');
  }
}

boot();
