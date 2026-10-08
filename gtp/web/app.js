/* Global Trader Platform dashboard: plain JS, talks to the /v1 API. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // d may be a table row when num is used as a column formatter; fall back to 2 places.
  const num = (v, d) => (d = typeof d === "number" ? d : 2, v === null || v === undefined || v === "" || isNaN(v)) ? "–" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: d, minimumFractionDigits: 0 });
  const pct = (v) => (v === null || v === undefined) ? "–" : `<span class="${v >= 0 ? "up" : "down"}">${v >= 0 ? "+" : ""}${num(v)}%</span>`;
  const crore = (v) => v === null || v === undefined ? "–" : `₹${num(v, 0)} Cr`;
  const date = (t) => t ? new Date(t * 1000).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "2-digit" }) : "–";
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
  };
  let apiKey = store.get("gtp_key") || "";
  let mode = "live";

  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.hidden = false;
    clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 6000);
  }

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      ...opts,
      headers: { "Content-Type": "application/json", ...(apiKey ? { "X-API-Key": apiKey } : {}), ...(opts.headers || {}) },
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || `HTTP ${res.status}`);
    return body;
  }

  // Wrap a form's submit handler with a busy state and error toast.
  function onSubmit(form, fn) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = $("button:not([type=button])", form);
      if (btn) btn.disabled = true;
      try { await fn(Object.fromEntries(new FormData(form))); }
      catch (err) { toast(err.message); }
      finally { if (btn) btn.disabled = false; }
    });
  }

  function table(rows, cols) {
    if (!rows.length) return `<p class="muted">No rows.</p>`;
    return `<div class="tablewrap"><table><thead><tr>${cols.map((c) => `<th class="${c.l ? "l" : ""}">${esc(c.h)}</th>`).join("")}</tr></thead>
      <tbody>${rows.map((r) => `<tr>${cols.map((c) => `<td class="${c.l ? "l" : ""}">${c.f ? c.f(r[c.k], r) : esc(r[c.k])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  const sectionErr = (s) => s && s.error ? `<p class="err">${esc(s.error)}</p>` : "";

  // ---- tabs -----------------------------------------------------------------
  $$(".tabs button").forEach((b) => b.addEventListener("click", () => {
    $$(".tabs button").forEach((x) => x.classList.toggle("active", x === b));
    $$(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${b.dataset.tab}`));
    store.set("gtp_tab", b.dataset.tab);
  }));
  const savedTab = store.get("gtp_tab");
  if (savedTab) $(`.tabs button[data-tab="${savedTab}"]`)?.click();

  // ---- key & plan -------------------------------------------------------------
  async function loadMe() {
    if (!apiKey) { $("#planinfo").textContent = "No key set"; return; }
    try {
      const me = await api("/v1/me");
      $("#planinfo").textContent = `${me.customer.name} · ${me.plan.name} plan`;
    } catch (e) { $("#planinfo").textContent = e.message; }
  }
  $("#apikey").value = apiKey;
  $("#savekey").addEventListener("click", () => { apiKey = $("#apikey").value.trim(); store.set("gtp_key", apiKey); loadMe(); });

  // ---- charts ---------------------------------------------------------------------
  const charts = {};
  function draw(id, config) {
    charts[id]?.destroy();
    charts[id] = new Chart($(`#${id}`), config);
  }
  const axisOpts = () => ({
    responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: "index", intersect: false },
    plugins: { legend: { labels: { color: css("--muted"), boxWidth: 12 } } },
    scales: {
      x: { ticks: { color: css("--muted"), maxTicksLimit: 8 }, grid: { color: css("--border") } },
      y: { ticks: { color: css("--muted") }, grid: { color: css("--border") } },
    },
  });
  const line = (label, data, color, extra = {}) => ({ label, data, borderColor: color, backgroundColor: color, borderWidth: 1.5, pointRadius: 0, spanGaps: true, ...extra });

  // ---- markets --------------------------------------------------------------------
  onSubmit($("#chartform"), async (f) => {
    const qs = new URLSearchParams({ symbol: f.symbol, exchange: f.exchange, periodicity: f.periodicity, bars: f.bars, indicators: "sma:20,sma:50,bollinger:20,rsi:14" });
    const [h, q] = await Promise.all([api(`/v1/history?${qs}`), api(`/v1/quote?symbol=${encodeURIComponent(f.symbol)}&exchange=${f.exchange}`).catch(() => null)]);
    if (q) {
      $("#quotebar").innerHTML = `<span class="ltp">${num(q.ltp)}</span> ${pct(q.change_pct)}
        <span class="muted">O ${num(q.open)} · H ${num(q.high)} · L ${num(q.low)} · Prev ${num(q.prev_close)} · Vol ${num(q.volume, 0)}</span>`;
    }
    const intraday = ["HOUR", "MINUTE"].includes(f.periodicity);
    const labels = h.candles.map((c) => intraday ? new Date(c.t * 1000).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }) : date(c.t));
    const ind = h.indicators;
    draw("pricechart", {
      type: "line",
      data: { labels, datasets: [
        line(`${h.symbol} close`, h.candles.map((c) => c.c), css("--accent"), { borderWidth: 2 }),
        line("SMA 20", ind["sma:20"], css("--warn")),
        line("SMA 50", ind["sma:50"], css("--up")),
        line("BB upper", ind["bollinger:20"].upper, css("--muted"), { borderDash: [4, 4], borderWidth: 1 }),
        line("BB lower", ind["bollinger:20"].lower, css("--muted"), { borderDash: [4, 4], borderWidth: 1 }),
      ] },
      options: axisOpts(),
    });
    const ro = axisOpts(); ro.scales.y.min = 0; ro.scales.y.max = 100; ro.plugins.legend.display = true;
    draw("rsichart", { type: "line", data: { labels, datasets: [line("RSI 14", ind["rsi:14"], css("--down"))] }, options: ro });
  });

  onSubmit($("#wlform"), async (f) => {
    const p = await api(`/v1/market/pulse?watchlist=${encodeURIComponent(f.watchlist)}`);
    const s = p.sections;
    const idx = (s.indices.data || []).map((q) => `<div class="card price-card"><div class="muted">${esc(q.symbol)}</div><div class="big">${num(q.ltp)}</div>${pct(q.change_pct)}</div>`).join("");
    const senti = Object.fromEntries((s.watchlist_news?.data || []).map((r) => [r.symbol, r]));
    $("#pulse").innerHTML = `<div class="grid3">${idx}</div>${sectionErr(s.indices)}
      ${table(s.watchlist?.data || [], [
        { h: "Symbol", k: "symbol", l: 1 }, { h: "LTP", k: "ltp", f: num }, { h: "Chg %", k: "change_pct", f: pct },
        { h: "Volume", k: "volume", f: (v) => num(v, 0) },
        { h: "News", k: "symbol", f: (v) => senti[v] ? `<span class="chip ${senti[v].label}">${esc(senti[v].label)} ${num(senti[v].net_score)}</span>` : "–" },
      ])}${sectionErr(s.watchlist)}
      ${s.market_sentiment ? `<p class="muted small">Market news mood: <b>${esc(s.market_sentiment.data.label)}</b> (${s.market_sentiment.data.positive}+ / ${s.market_sentiment.data.negative}−)</p>` : ""}`;
  });

  // ---- company 360 -------------------------------------------------------------------
  onSubmit($("#c360form"), async (f) => {
    const r = await api(`/v1/company/${encodeURIComponent(f.symbol)}`);
    const s = r.sections, q = s.quote.data || {}, t = s.technicals.data || {}, x = s.ratios.data || {};
    const p = s.profile.data || {}, sec = s.sector.data || {}, ns = s.news_sentiment.data || {};
    const shp = Array.isArray(s.shareholding.data) ? s.shareholding.data : [];
    const kv = (pairs) => `<div class="kv">${pairs.map(([k, v]) => `<div><span>${esc(k)}</span><b>${v}</b></div>`).join("")}</div>`;
    $("#c360").innerHTML = `
      <div class="card"><h3>${esc(p.CompanyName || r.symbol)} <span class="muted">${esc(r.symbol)} · ${esc(sec.Sector || "")} · ${esc(sec.Industry || "")}</span></h3>
        <div class="quotebar"><span class="ltp">${num(q.ltp)}</span> ${pct(q.change_pct)} <span class="muted">ISIN ${esc(p.ISIN || "–")}</span></div>
        <div class="chips">${(s.signals.data || []).map((g) => `<span class="chip ${g.tone}">${esc(g.text)}</span>`).join("") || '<span class="muted">No signals</span>'}</div>
        ${sectionErr(s.quote)}</div>
      <div class="row">
        <div class="card grow"><h3>Valuation &amp; financials</h3>${kv([
          ["P/E", num(x.pe)], ["P/B", num(x.pb)], ["EPS", num(x.eps)], ["Market cap", crore(x.market_cap)],
          ["Book value", num(x.book_value)], ["Dividend yield", num(x.dividend_yield)], ["Debt", num(x.debt, 0)],
          ["Interest cover", num(x.interest_coverage)], ["Price / sales", num(x.price_sales)],
        ])}${sectionErr(s.ratios)}</div>
        <div class="card grow"><h3>Technicals</h3>${kv([
          ["Trend", esc(t.trend || "–")], ["RSI 14", num(t.rsi14)], ["SMA 50", num(t.sma50)], ["SMA 200", num(t.sma200)],
          ["1M", pct(t.change_1m_pct)], ["3M", pct(t.change_3m_pct)], ["1Y", pct(t.change_1y_pct)],
          ["52W high", num(t.high_52w)], ["From 52W high", pct(t.pct_from_52w_high)], ["Volatility 1Y", t.volatility_1y_pct ? num(t.volatility_1y_pct) + "%" : "–"],
        ])}${sectionErr(s.technicals)}</div>
      </div>
      <div class="row">
        <div class="card grow"><h3>Shareholding</h3>${shp.length ? shp.map((h) => `<div>${esc(h.Category)} <span class="muted">${num(h.Percentage)}%</span><div class="bar" style="width:${Math.min(100, Number(h.Percentage) || 0)}%"></div></div>`).join("") : `<pre>${esc(JSON.stringify(s.shareholding.data ?? "", null, 1)).slice(0, 1500)}</pre>`}${sectionErr(s.shareholding)}</div>
        <div class="card grow"><h3>Corporate filings</h3>${table(s.announcements.data || [], [{ h: "Date", k: "FillingDate", l: 1 }, { h: "Headline", k: "HeadLine", l: 1 }])}${sectionErr(s.announcements)}</div>
      </div>
      <div class="card"><h3>News · <span class="chip ${ns.label}">${esc(ns.label || "")} ${num(ns.net_score)}</span> <span class="muted small">${ns.positive || 0}+ / ${ns.negative || 0}− / ${ns.neutral || 0}=</span></h3>
        ${articles(s.news.data || [])}${sectionErr(s.news)}</div>`;
  });

  function articles(list) {
    if (!list.length) return `<p class="muted">No articles.</p>`;
    return list.map((a) => `<div class="article">
      <div><span class="chip ${a.sentiment === "positive" ? "bullish" : a.sentiment === "negative" ? "bearish" : ""}">${esc(a.sentiment || "n/a")}</span>
      ${a.link ? `<a href="${esc(a.link)}" target="_blank" rel="noopener noreferrer">${esc(a.specific_title || a.title)}</a>` : `<b>${esc(a.specific_title || a.title)}</b>`}</div>
      <div class="meta">${esc(a.symbol || a.company || "")} · ${esc(a.article_type || "")} · ${esc(a.source || "")} · ${esc((a.date || "").replace("T", " ").slice(0, 16))}</div>
      <div>${esc(a.summary || "")}</div></div>`).join("");
  }

  // ---- screener ----------------------------------------------------------------------
  let screenMeta = { fields: [], operators: [] };
  function addFilter(field = "pe", op = "<", value = "25") {
    const div = document.createElement("div");
    div.className = "filter";
    div.innerHTML = `<select class="f">${screenMeta.fields.map((x) => `<option ${x === field ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
      <select class="o">${screenMeta.operators.map((x) => `<option ${x === op ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
      <input class="v" value="${esc(value)}" aria-label="Value"><button type="button" class="ghost">✕</button>`;
    $("button", div).addEventListener("click", () => div.remove());
    $("#filters").append(div);
  }
  const parseVal = (v) => { if (v === "true") return true; if (v === "false") return false; if (v.startsWith("[")) { try { return JSON.parse(v); } catch { return v; } } return isNaN(v) || v === "" ? v : Number(v); };
  $("#addfilter").addEventListener("click", () => addFilter());
  $("#presets").addEventListener("change", () => { $("#filters").innerHTML = ""; });
  onSubmit($("#screenform"), async (f) => {
    const filters = $$("#filters .filter").map((d) => ({ field: $(".f", d).value, op: $(".o", d).value, value: parseVal($(".v", d).value) }));
    const r = await api("/v1/screener", { method: "POST", body: JSON.stringify({ preset: f.preset || null, sort: f.sort || null, filters }) });
    $("#screenres").innerHTML = `<p class="muted">${r.matched} of ${r.universe_size} matched${r.failed.length ? ` · ${r.failed.length} symbols had missing data` : ""}</p>` + table(r.results, [
      { h: "Symbol", k: "symbol", l: 1 }, { h: "Sector", k: "sector", l: 1 }, { h: "Close", k: "close", f: num },
      { h: "P/E", k: "pe", f: num }, { h: "P/B", k: "pb", f: num }, { h: "RSI", k: "rsi14", f: num },
      { h: "1M", k: "change_1m_pct", f: pct }, { h: "3M", k: "change_3m_pct", f: pct }, { h: "From 52W hi", k: "pct_from_52w_high", f: pct },
      { h: "Trend", k: "trend" }, { h: "MCap", k: "market_cap", f: crore },
    ]);
  });

  // ---- backtest ------------------------------------------------------------------------
  onSubmit($("#btform"), async (f) => {
    let params = {};
    if (f.params.trim()) { try { params = JSON.parse(f.params); } catch { throw new Error("Params must be valid JSON"); } }
    const r = await api("/v1/backtest", { method: "POST", body: JSON.stringify({ symbol: f.symbol, strategy: f.strategy, params, bars: Number(f.bars), cost_bps: Number(f.cost_bps) }) });
    const m = r.metrics, b = r.benchmark;
    const rows = [["Total return %", "total_return_pct"], ["CAGR %", "cagr_pct"], ["Volatility %", "volatility_pct"], ["Sharpe", "sharpe"], ["Sortino", "sortino"], ["Max drawdown %", "max_drawdown_pct"], ["Calmar", "calmar"]]
      .map(([h, k]) => ({ metric: h, s: m[k], b: b[k] }));
    $("#btres").innerHTML = `<div class="card"><h3>${esc(r.symbol)} · ${esc(r.strategy)} <span class="muted small">${esc(JSON.stringify(r.params))} · ${r.bars} bars</span></h3>
      <div class="chartwrap tall"><canvas id="eqchart"></canvas></div></div>
      <div class="row"><div class="card grow"><h3>Performance</h3>${table(rows, [{ h: "Metric", k: "metric", l: 1 }, { h: "Strategy", k: "s", f: num }, { h: "Buy & hold", k: "b", f: num }])}</div>
      <div class="card grow"><h3>Trading</h3><div class="kv">
        <div><span>Trades</span><b>${m.trades}</b></div><div><span>Win rate</span><b>${num(m.win_rate_pct)}%</b></div>
        <div><span>Avg trade</span><b>${pct(m.avg_trade_pct)}</b></div><div><span>Time in market</span><b>${num(m.exposure_pct)}%</b></div>
        <div><span>Final equity</span><b>₹${num(m.final_equity, 0)}</b></div></div></div></div>
      <div class="card"><h3>Trades</h3>${table(r.trades.slice(-25).reverse(), [{ h: "Entry", k: "entry_time", l: 1, f: date }, { h: "Exit", k: "exit_time", f: date }, { h: "Side", k: "side" }, { h: "Entry ₹", k: "entry_price", f: num }, { h: "Exit ₹", k: "exit_price", f: num }, { h: "Return", k: "return_pct", f: pct }])}</div>`;
    draw("eqchart", { type: "line", data: { labels: r.equity.map((e) => date(e.t)), datasets: [line("Strategy", r.equity.map((e) => e.equity), css("--accent"), { borderWidth: 2 }), line("Buy & hold", r.equity.map((e) => e.benchmark), css("--muted"))] }, options: axisOpts() });
  });

  // ---- options -----------------------------------------------------------------------
  onSubmit($("#ocform"), async (f) => {
    const r = await api(`/v1/options/chain?product=${encodeURIComponent(f.product)}${f.expiry ? `&expiry=${encodeURIComponent(f.expiry)}` : ""}`);
    const s = r.summary;
    const byStrike = {};
    r.rows.forEach((x) => { (byStrike[x.strike] ??= { strike: x.strike })[x.option_type] = x; });
    const rows = Object.values(byStrike).sort((a, b) => a.strike - b.strike);
    $("#ocres").innerHTML = `<div class="kv"><div><span>PCR (OI)</span><b>${num(s.pcr_oi, 3)}</b></div><div><span>Max pain</span><b>${num(s.max_pain)}</b></div>
      <div><span>Resistance (call OI)</span><b>${s.resistance.map((v) => num(v)).join(", ")}</b></div><div><span>Support (put OI)</span><b>${s.support.map((v) => num(v)).join(", ")}</b></div></div><br>` +
      table(rows, [
        { h: "CE OI", k: "CE", f: (v) => num(v?.open_interest, 0) }, { h: "CE ΔOI", k: "CE", f: (v) => num(v?.oi_change, 0) }, { h: "CE LTP", k: "CE", f: (v) => num(v?.ltp) },
        { h: "Strike", k: "strike", f: (v) => `<b>${num(v)}</b>` },
        { h: "PE LTP", k: "PE", f: (v) => num(v?.ltp) }, { h: "PE ΔOI", k: "PE", f: (v) => num(v?.oi_change, 0) }, { h: "PE OI", k: "PE", f: (v) => num(v?.open_interest, 0) },
      ]);
  });

  // ---- mutual funds ----------------------------------------------------------------
  onSubmit($("#mfsearch"), async (f) => {
    const rows = await api(`/v1/mf/schemes?name=${encodeURIComponent(f.name)}`);
    $("#mflist").innerHTML = table(rows.slice(0, 50), [
      { h: "Code", k: "Code", l: 1 }, { h: "Scheme", k: "Name", l: 1 }, { h: "Category", k: "Category", l: 1 }, { h: "Sub-category", k: "SubCategory", l: 1 },
      { h: "", k: "Code", f: (v) => `<button type="button" class="ghost" data-mf="${esc(v)}">Analyse</button>` },
    ]);
    $$("#mflist [data-mf]").forEach((b) => b.addEventListener("click", () => fundDetail(b.dataset.mf).catch((e) => toast(e.message))));
  });

  async function fundDetail(code) {
    const [r, h] = await Promise.all([api(`/v1/mf/${code}/returns`), api(`/v1/mf/${code}/holdings`)]);
    const ret = Object.entries(r.returns).map(([k, v]) => ({ period: k, abs: v?.absolute_pct, cagr: v?.cagr_pct }));
    $("#mfdetail").innerHTML = `<div class="card"><h3>${esc(r.name)} <span class="muted small">NAV ${num(r.nav, 4)} · ${esc(r.date)}</span></h3>
      <div class="row"><div class="grow">${table(ret, [{ h: "Period", k: "period", l: 1 }, { h: "Absolute", k: "abs", f: pct }, { h: "CAGR", k: "cagr", f: pct }])}</div>
      <div class="grow"><h3>Sector exposure</h3>${h.exposure.by_sector.slice(0, 8).map((s) => `<div>${esc(s.name)} <span class="muted">${num(s.weight)}%</span><div class="bar" style="width:${Math.min(100, s.weight)}%"></div></div>`).join("")}
      <p class="muted small">Top 10 holdings: ${num(h.exposure.top10_weight)}% of assets</p></div></div>
      <h3>Holdings</h3>${table(h.holdings.slice(0, 25), [{ h: "Instrument", k: "instrument", l: 1 }, { h: "Sector", k: "sector", l: 1 }, { h: "Weight %", k: "weight", f: num }, { h: "Size", k: "size" }])}</div>`;
  }

  onSubmit($("#mfoverlap"), async (f) => {
    const r = await api(`/v1/mf/overlap?a=${encodeURIComponent(f.a)}&b=${encodeURIComponent(f.b)}`);
    $("#mfov").innerHTML = `<p><b>${num(r.overlap_pct)}%</b> portfolio overlap · ${r.common_holdings} common holdings (${r.holdings_a} vs ${r.holdings_b})</p>` +
      table(r.common, [{ h: "Instrument", k: "instrument", l: 1 }, { h: "Weight A", k: "weight_a", f: num }, { h: "Weight B", k: "weight_b", f: num }, { h: "Overlap", k: "overlap_weight", f: num }]);
  });

  // ---- news --------------------------------------------------------------------------------
  onSubmit($("#newsform"), async (f) => {
    const r = await api(`/v1/news/multi?symbols=${encodeURIComponent(f.symbols)}&limit=60`);
    $("#newssent").innerHTML = table(r.by_symbol, [
      { h: "Symbol", k: "symbol", l: 1 }, { h: "Mood", k: "label", f: (v) => `<span class="chip ${v}">${esc(v)}</span>` }, { h: "Net score", k: "net_score", f: num },
      { h: "Positive", k: "positive" }, { h: "Negative", k: "negative" }, { h: "Neutral", k: "neutral" },
    ]);
    $("#newslist").innerHTML = `<div class="card">${articles(r.articles)}</div>`;
  });

  let es = null;
  $("#streambtn").addEventListener("click", () => {
    if (es) { es.close(); es = null; $("#streambtn").textContent = "Start live stream"; return; }
    const syms = $("#newsform [name=symbols]").value;
    es = new EventSource(`/v1/news/stream?symbols=${encodeURIComponent(syms)}&api_key=${encodeURIComponent(apiKey)}`);
    $("#streambtn").textContent = "Stop live stream";
    let box = $("#livebox");
    if (!box) { box = document.createElement("div"); box.id = "livebox"; box.className = "card"; box.innerHTML = "<h3>Live</h3><div></div>"; $("#newslist").before(box); }
    es.addEventListener("article", (ev) => { $("div", box).insertAdjacentHTML("afterbegin", articles([JSON.parse(ev.data)])); });
    es.onerror = () => { toast("Live stream disconnected (your plan may not include streaming)"); es.close(); es = null; $("#streambtn").textContent = "Start live stream"; };
  });

  // ---- plans ---------------------------------------------------------------------------
  async function loadPlans() {
    const plans = await api("/v1/plans");
    $("#planlist").innerHTML = plans.map((p) => `<div class="card"><h3>${esc(p.name)}</h3>
      <div class="big">${p.price_inr_month ? `₹${num(p.price_inr_month, 0)}<span class="muted small">/month</span>` : "Free"}</div>
      <p class="muted">${esc(p.description)}</p><p class="small">${num(p.requests_per_minute, 0)} req/min · ${num(p.requests_per_day, 0)} req/day · ${p.max_symbols_per_request} symbols/request</p>
      <div class="chips">${p.features.map((f) => `<span class="chip">${esc(f)}</span>`).join("")}</div></div>`).join("");
    $("#snippet").textContent = `curl -H "X-API-Key: $GTP_KEY" "${location.origin}/v1/company/TCS"

# Python
import requests
s = requests.Session(); s.headers["X-API-Key"] = "<your key>"
print(s.get("${location.origin}/v1/quote", params={"symbol": "RELIANCE"}).json())
print(s.post("${location.origin}/v1/backtest", json={"symbol": "INFY", "strategy": "sma_cross",
             "params": {"fast": 20, "slow": 50}}).json()["metrics"])`;
  }

  // ---- boot ----------------------------------------------------------------------------
  (async () => {
    try {
      const h = await api("/health");
      mode = h.mode;
      const badge = $("#mode");
      badge.textContent = mode === "demo" ? "DEMO DATA" : "LIVE";
      badge.classList.toggle("demo", mode === "demo");
      if (mode === "demo") {
        $("#demonote").textContent = "Demo mode: all numbers are synthetic.";
        if (!apiKey) { apiKey = "demo-algo-key"; $("#apikey").value = apiKey; store.set("gtp_key", apiKey); }
      }
    } catch (e) { toast(e.message); }
    loadMe();
    loadPlans().catch((e) => toast(e.message));
    try {
      const meta = await api("/v1/screener/presets");
      screenMeta = meta;
      $("#fieldlist").textContent = meta.fields.join(", ");
      Object.entries(meta.presets).forEach(([k, v]) => $("#presets").insertAdjacentHTML("beforeend", `<option value="${esc(k)}">${esc(k)}: ${esc(v.description)}</option>`));
      addFilter();
    } catch (e) { toast(e.message); }
    try {
      const st = await api("/v1/backtest/strategies");
      $("#strategies").innerHTML = Object.keys(st).map((k) => `<option>${esc(k)}</option>`).join("");
    } catch (e) { toast(e.message); }
    if (apiKey) { $("#chartform").requestSubmit(); $("#wlform").requestSubmit(); }
  })();
})();
