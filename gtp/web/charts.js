// Canvas chart engine: candlesticks with volume + indicator panels, plus sparkline and donut helpers.
// No external libraries, so the page runs under a strict 'self'-only content security policy.

const css = (name, fallback = '') =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;

function colors() {
  return {
    up: css('--up', '#26d07c'), down: css('--down', '#ff5c6c'), flat: css('--dim', '#8b98a9'),
    grid: css('--chart-grid', 'rgba(255,255,255,.06)'), axis: css('--faint', '#5c6a7d'),
    text: css('--dim', '#8b98a9'), accent: css('--accent', '#3dd6c4'), accent2: css('--accent-2', '#f5a623'),
    violet: css('--violet', '#9d7bff'), crosshair: css('--text', '#e6edf3'),
    panel: css('--panel', '#0f1520'), bb: css('--chart-band', 'rgba(61,214,196,.10)'),
  };
}

function setupCanvas(canvas, h) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = canvas.clientWidth || canvas.parentElement.clientWidth;
  const height = h || canvas.clientHeight || 260;
  canvas.width = Math.round(w * dpr); canvas.height = Math.round(height * dpr);
  canvas.style.height = height + 'px';
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h: height };
}

const fmt = (v) => {
  const a = Math.abs(v);
  if (a >= 1e7) return (v / 1e7).toFixed(2) + 'Cr';
  if (a >= 1e5) return (v / 1e5).toFixed(1) + 'L';
  if (a >= 1e3) return (v / 1e3).toFixed(1) + 'K';
  return a >= 100 ? v.toFixed(0) : v.toFixed(2);
};
const niceStep = (range, ticks) => {
  const raw = range / ticks, mag = Math.pow(10, Math.floor(Math.log10(raw))), n = raw / mag;
  return (n >= 5 ? 5 : n >= 2 ? 2 : 1) * mag;
};

// ---------- main price / equity chart ---------------------------------------
export class Chart {
  constructor(canvas) {
    this.canvas = canvas;
    this.candles = [];
    this.overlays = [];      // [{values, color, width}]
    this.lower = null;       // {type:'rsi'|'macd', ...}
    this.showVolume = true;
    this.type = 'candine';   // 'candle' | 'line' | 'area'
    this.hover = null;
    this.onHover = null;
    this._bind();
  }

  _bind() {
    const move = (e) => {
      const r = this.canvas.getBoundingClientRect();
      const x = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
      this.hover = this._xToIndex(x);
      this.draw();
      if (this.onHover) this.onHover(this.hover == null ? null : this.candles[this.hover], this.hover);
    };
    const leave = () => { this.hover = null; this.draw(); if (this.onHover) this.onHover(null, null); };
    this.canvas.addEventListener('mousemove', move);
    this.canvas.addEventListener('mouseleave', leave);
    this.canvas.addEventListener('touchmove', (e) => { move(e); }, { passive: true });
    this.canvas.addEventListener('touchend', leave);
    this._ro = new ResizeObserver(() => this.draw());
    this._ro.observe(this.canvas.parentElement);
  }

  set(data) {
    this.candles = data.candles || [];
    this.overlays = data.overlays || [];
    this.lower = data.lower || null;
    this.showVolume = data.showVolume !== false && this.candles.some((c) => c.v);
    this.type = data.type || 'candle';
    this.hover = null;
    this.draw();
    return this;
  }

  _layout(w, h) {
    const padL = 6, padR = 58, padT = 8;
    const lowerH = this.lower ? 76 : 0;
    const volH = this.showVolume ? Math.min(70, h * 0.22) : 0;
    const axisH = 20;
    const priceH = h - padT - volH - lowerH - axisH;
    return { padL, padR, padT, priceH, volH, lowerH, axisH, plotW: w - padL - padR };
  }

  _xToIndex(x) {
    const { w } = this._dims || {};
    if (!w || !this.candles.length) return null;
    const L = this._layout(w, this._dims.h);
    const i = Math.round(((x - L.padL) / L.plotW) * (this.candles.length - 1));
    return i >= 0 && i < this.candles.length ? i : null;
  }

  draw() {
    if (!this.canvas.clientWidth) return;
    const { ctx, w, h } = setupCanvas(this.canvas);
    this._dims = { w, h };
    const C = colors();
    ctx.clearRect(0, 0, w, h);
    if (!this.candles.length) {
      ctx.fillStyle = C.text; ctx.font = '12px ui-monospace, monospace'; ctx.textAlign = 'center';
      ctx.fillText('No data', w / 2, h / 2); return;
    }
    const L = this._layout(w, h);
    const n = this.candles.length;
    const xs = (i) => L.padL + (n === 1 ? L.plotW / 2 : (i / (n - 1)) * L.plotW);

    // price range across candles + overlays
    let lo = Infinity, hi = -Infinity;
    for (const c of this.candles) { lo = Math.min(lo, c.l ?? c.c); hi = Math.max(hi, c.h ?? c.c); }
    for (const o of this.overlays) for (const v of o.values) if (v != null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    if (lo === hi) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
    const yTop = L.padT, yBot = L.padT + L.priceH;
    const ys = (v) => yBot - ((v - lo) / (hi - lo)) * L.priceH;

    // grid + price axis
    ctx.font = '10px ui-monospace, "IBM Plex Mono", monospace'; ctx.textBaseline = 'middle';
    const step = niceStep(hi - lo, 5);
    ctx.strokeStyle = C.grid; ctx.fillStyle = C.axis; ctx.lineWidth = 1; ctx.textAlign = 'left';
    for (let v = Math.ceil(lo / step) * step; v < hi; v += step) {
      const y = Math.round(ys(v)) + 0.5;
      ctx.beginPath(); ctx.moveTo(L.padL, y); ctx.lineTo(L.padL + L.plotW, y); ctx.stroke();
      ctx.fillText(fmt(v), L.padL + L.plotW + 6, y);
    }

    // time axis labels
    const intraday = n > 1 && (this.candles[n - 1].t - this.candles[0].t) < 5 * 86400;
    ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
    const labelAt = new Set();
    const nLabels = Math.max(2, Math.min(7, Math.floor(L.plotW / 90)));
    for (let k = 0; k <= nLabels; k++) labelAt.add(Math.round((k / nLabels) * (n - 1)));
    for (const i of labelAt) {
      const d = new Date(this.candles[i].t * 1000);
      const ist = new Date(d.getTime() + (330 + d.getTimezoneOffset()) * 60000);
      const lab = intraday
        ? ist.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })
        : ist.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
      ctx.fillStyle = C.axis; ctx.fillText(lab, Math.max(14, Math.min(w - L.padR, xs(i))), h - 6);
    }

    // volume
    if (this.showVolume) {
      const vTop = yBot + 6, vMax = Math.max(...this.candles.map((c) => c.v || 0)) || 1;
      const bw = Math.max(1, (L.plotW / n) * 0.7);
      for (let i = 0; i < n; i++) {
        const c = this.candles[i], up = (c.c ?? 0) >= (c.o ?? c.c);
        const bh = ((c.v || 0) / vMax) * (L.volH - 6);
        ctx.fillStyle = up ? C.up : C.down; ctx.globalAlpha = 0.38;
        ctx.fillRect(xs(i) - bw / 2, vTop + (L.volH - 6 - bh), bw, bh);
      }
      ctx.globalAlpha = 1;
    }

    // price series
    if (this.type === 'line' || this.type === 'area') {
      ctx.beginPath();
      this.candles.forEach((c, i) => { const x = xs(i), y = ys(c.c); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      if (this.type === 'area') {
        const g = ctx.createLinearGradient(0, yTop, 0, yBot);
        g.addColorStop(0, C.accent + '55'); g.addColorStop(1, C.accent + '00');
        ctx.lineTo(xs(n - 1), yBot); ctx.lineTo(xs(0), yBot); ctx.closePath();
        ctx.fillStyle = g; ctx.fill();
        ctx.beginPath(); this.candles.forEach((c, i) => { const x = xs(i), y = ys(c.c); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      }
      ctx.strokeStyle = C.accent; ctx.lineWidth = 1.6; ctx.lineJoin = 'round'; ctx.stroke();
    } else {
      const bw = Math.max(1, Math.min(13, (L.plotW / n) * 0.64));
      for (let i = 0; i < n; i++) {
        const c = this.candles[i], up = (c.c ?? 0) >= (c.o ?? c.c);
        const x = xs(i), col = up ? C.up : C.down;
        ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(Math.round(x) + 0.5, ys(c.h)); ctx.lineTo(Math.round(x) + 0.5, ys(c.l)); ctx.stroke();
        const yo = ys(c.o), yc = ys(c.c), top = Math.min(yo, yc), bh = Math.max(1, Math.abs(yc - yo));
        if (bw >= 3) ctx.fillRect(x - bw / 2, top, bw, bh);
        else { ctx.beginPath(); ctx.moveTo(x, yo); ctx.lineTo(x, yc); ctx.stroke(); }
      }
    }

    // overlays (SMA/EMA/Bollinger)
    for (const o of this.overlays) {
      ctx.beginPath(); let started = false;
      o.values.forEach((v, i) => {
        if (v == null) { started = false; return; }
        const x = xs(i), y = ys(v);
        if (started) ctx.lineTo(x, y); else { ctx.moveTo(x, y); started = true; }
      });
      ctx.strokeStyle = o.color; ctx.lineWidth = o.width || 1.3; ctx.setLineDash(o.dash || []);
      ctx.lineJoin = 'round'; ctx.stroke(); ctx.setLineDash([]);
    }

    // lower panel
    if (this.lower) this._drawLower(ctx, C, L, xs, w, h);

    // crosshair
    if (this.hover != null) {
      const x = Math.round(xs(this.hover)) + 0.5, c = this.candles[this.hover];
      ctx.strokeStyle = C.crosshair; ctx.globalAlpha = 0.28; ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(x, yTop); ctx.lineTo(x, h - L.axisH); ctx.stroke();
      const y = Math.round(ys(c.c)) + 0.5;
      ctx.beginPath(); ctx.moveTo(L.padL, y); ctx.lineTo(L.padL + L.plotW, y); ctx.stroke();
      ctx.setLineDash([]); ctx.globalAlpha = 1;
      ctx.fillStyle = C.crosshair; ctx.fillRect(L.padL + L.plotW, y - 8, L.padR, 16);
      ctx.fillStyle = C.panel; ctx.font = '10px ui-monospace, monospace'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
      ctx.fillText(fmt(c.c), L.padL + L.plotW + 6, y);
    }
  }

  _drawLower(ctx, C, L, xs, w, h) {
    const top = L.padT + L.priceH + L.volH + 10, bot = top + L.lowerH - 14, n = this.candles.length;
    const lw = this.lower;
    ctx.font = '9px ui-monospace, monospace'; ctx.textBaseline = 'middle';
    if (lw.type === 'rsi') {
      const ys = (v) => bot - (v / 100) * (bot - top);
      ctx.strokeStyle = C.grid; ctx.fillStyle = C.axis; ctx.textAlign = 'left';
      for (const g of [30, 50, 70]) {
        const y = Math.round(ys(g)) + 0.5;
        ctx.setLineDash(g === 50 ? [] : [2, 3]); ctx.beginPath(); ctx.moveTo(L.padL, y); ctx.lineTo(L.padL + L.plotW, y); ctx.stroke();
        ctx.fillText(String(g), L.padL + L.plotW + 6, y);
      }
      ctx.setLineDash([]);
      ctx.beginPath(); let s = false;
      lw.values.forEach((v, i) => { if (v == null) { s = false; return; } const x = xs(i), y = ys(v); s ? ctx.lineTo(x, y) : (ctx.moveTo(x, y), s = true); });
      ctx.strokeStyle = C.violet; ctx.lineWidth = 1.3; ctx.stroke();
      ctx.fillStyle = C.violet; ctx.textAlign = 'left'; ctx.fillText('RSI 14', L.padL + 2, top + 2);
    } else if (lw.type === 'macd') {
      const all = [...lw.macd, ...lw.signal, ...lw.hist].filter((v) => v != null);
      let lo = Math.min(...all), hi = Math.max(...all); if (lo === hi) { lo -= 1; hi += 1; }
      const ys = (v) => bot - ((v - lo) / (hi - lo)) * (bot - top);
      const zero = Math.round(ys(0)) + 0.5;
      ctx.strokeStyle = C.grid; ctx.beginPath(); ctx.moveTo(L.padL, zero); ctx.lineTo(L.padL + L.plotW, zero); ctx.stroke();
      const bw = Math.max(1, (L.plotW / n) * 0.6);
      lw.hist.forEach((v, i) => { if (v == null) return; ctx.fillStyle = v >= 0 ? C.up : C.down; ctx.globalAlpha = 0.5; const y = ys(v); ctx.fillRect(xs(i) - bw / 2, Math.min(y, zero), bw, Math.abs(y - zero)); });
      ctx.globalAlpha = 1;
      const line = (vals, col) => { ctx.beginPath(); let s = false; vals.forEach((v, i) => { if (v == null) { s = false; return; } const x = xs(i), y = ys(v); s ? ctx.lineTo(x, y) : (ctx.moveTo(x, y), s = true); }); ctx.strokeStyle = col; ctx.lineWidth = 1.2; ctx.stroke(); };
      line(lw.macd, C.accent); line(lw.signal, C.accent2);
      ctx.fillStyle = C.axis; ctx.textAlign = 'left'; ctx.fillText('MACD 12,26,9', L.padL + 2, top + 2);
    }
  }

  destroy() { this._ro?.disconnect(); }
}

// ---------- sparkline -------------------------------------------------------
export function sparkline(canvas, values, { color, fill = true, height = 34 } = {}) {
  if (!canvas || !values || values.length < 2) return;
  const { ctx, w, h } = setupCanvas(canvas, height);
  const C = colors();
  const first = values[0], last = values[values.length - 1];
  const col = color || (last >= first ? C.up : C.down);
  let lo = Math.min(...values), hi = Math.max(...values); if (lo === hi) { lo -= 1; hi += 1; }
  const pad = 3, xs = (i) => (i / (values.length - 1)) * (w - 2) + 1, ys = (v) => h - pad - ((v - lo) / (hi - lo)) * (h - pad * 2);
  ctx.clearRect(0, 0, w, h);
  if (fill) {
    const g = ctx.createLinearGradient(0, 0, 0, h);
    g.addColorStop(0, col + '40'); g.addColorStop(1, col + '00');
    ctx.beginPath(); values.forEach((v, i) => { const x = xs(i), y = ys(v); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.lineTo(xs(values.length - 1), h); ctx.lineTo(xs(0), h); ctx.closePath(); ctx.fillStyle = g; ctx.fill();
  }
  ctx.beginPath(); values.forEach((v, i) => { const x = xs(i), y = ys(v); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  ctx.strokeStyle = col; ctx.lineWidth = 1.4; ctx.lineJoin = 'round'; ctx.stroke();
}

// ---------- donut -----------------------------------------------------------
export function donut(canvas, slices, { size = 150, thickness = 20 } = {}) {
  if (!canvas) return;
  const { ctx } = setupCanvas(canvas, size);
  const cx = canvas.clientWidth / 2, cy = size / 2, r = size / 2 - 4;
  const total = slices.reduce((s, x) => s + x.value, 0) || 1;
  let a = -Math.PI / 2;
  ctx.clearRect(0, 0, canvas.clientWidth, size);
  for (const s of slices) {
    const a2 = a + (s.value / total) * Math.PI * 2;
    ctx.beginPath(); ctx.arc(cx, cy, r, a, a2); ctx.arc(cx, cy, r - thickness, a2, a, true); ctx.closePath();
    ctx.fillStyle = s.color; ctx.fill(); a = a2;
  }
}

// A palette for categorical series (sectors, allocations). Harmonised across themes.
export function palette(i) {
  const list = ['--c1', '--c2', '--c3', '--c4', '--c5', '--c6', '--c7', '--c8'];
  return css(list[i % list.length], '#3dd6c4');
}
