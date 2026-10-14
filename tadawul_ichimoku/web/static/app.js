/* Tadawul Ichimoku – front-end */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  const POPULAR = window.TADAWUL_POPULAR || [
    ["2222", "Saudi Aramco"], ["1120", "Al Rajhi Bank"], ["2010", "SABIC"], ["7010", "stc"],
    ["1180", "SNB"], ["2082", "ACWA Power"], ["1211", "Ma'aden"], ["1150", "Alinma Bank"],
  ];

  const state = { payload: null, range: 130, market: null, sort: { key: "change_pct", asc: false } };

  // ------------------------------------------------------------ helpers
  const fmt = (v, d = 2) => (v === null || v === undefined || Number.isNaN(v)) ? "—"
    : Number(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
  const fmtInt = v => (v === null || v === undefined) ? "—" : Math.round(v).toLocaleString("en-US");
  const fmtPct = v => (v === null || v === undefined) ? "—" : `${v > 0 ? "+" : ""}${fmt(v)}%`;
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const rgba = (hex, a) => {
    const h = hex.replace("#", "");
    const n = parseInt(h.length === 3 ? h.split("").map(c => c + c).join("") : h, 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  };
  const tone = score => score > 0 ? "bull" : score < 0 ? "bear" : "flat";
  const arrow = score => score > 0 ? "▲" : score < 0 ? "▼" : "■";

  const setHash = h => { try { history.replaceState(null, "", h); } catch { /* sandboxed frame */ } };

  function show(el, on) { if (el) el.hidden = !on; }

  async function getJSON(url, opts) {
    const r = await fetch(url, opts);
    let body = null;
    try { body = await r.json(); } catch { /* ignore */ }
    if (!r.ok) throw new Error(body?.error || `Request failed (${r.status})`);
    return body;
  }

  function params() {
    return new URLSearchParams({
      tenkan: $("#pTenkan").value, kijun: $("#pKijun").value,
      senkou_b: $("#pSenkouB").value, displacement: $("#pShift").value,
    });
  }

  // ------------------------------------------------------------ tabs & theme
  function switchView(view, push = true) {
    $$(".tabs button").forEach(b => b.setAttribute("aria-selected", String(b.dataset.view === view)));
    $$(".view").forEach(v => v.classList.toggle("active", v.id === `view-${view}`));
    if (push && !location.hash.startsWith(`#${view}`)) setHash(`#${view}`);
    if (view === "market") loadMarket();
    if (view === "analysis" && state.payload) Plotly.Plots.resize("chart");
  }

  function initTheme() {
    let saved = null;
    try { saved = localStorage.getItem("theme"); } catch { /* storage unavailable */ }
    if (saved) document.documentElement.dataset.theme = saved;
    $("#themeBtn").addEventListener("click", () => {
      const dark = document.documentElement.dataset.theme
        ? document.documentElement.dataset.theme === "dark"
        : matchMedia("(prefers-color-scheme: dark)").matches;
      const next = dark ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      try { localStorage.setItem("theme", next); } catch { /* ignore */ }
      if (state.payload) renderChart();
    });
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => state.payload && renderChart());
  }

  // ------------------------------------------------------------ analysis
  async function analyzeSymbol(symbol) {
    symbol = (symbol || "").trim().toUpperCase();
    if (!symbol) return;
    $("#symbolInput").value = symbol;
    switchView("analysis", false);
    setHash(`#analysis/${encodeURIComponent(symbol)}`);
    const q = params();
    q.set("days", $("#daysSelect").value);
    q.set("source", $("#sourceSelect").value);
    await runAnalysis(() => getJSON(`/api/analyze/${encodeURIComponent(symbol)}?${q}`), symbol);
  }

  async function analyzeCsv(file) {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("symbol", ($("#symbolInput").value || file.name.replace(/\.csv$/i, "")).toUpperCase());
    await runAnalysis(() => getJSON(`/api/analyze-csv?${params()}`, { method: "POST", body: fd }), file.name);
  }

  async function runAnalysis(fetcher, label) {
    show($("#analysisEmpty"), false);
    show($("#analysisError"), false);
    show($("#analysisLoading"), true);
    try {
      state.payload = await fetcher();
      show($("#analysisResult"), true);
      renderResult();
    } catch (e) {
      show($("#analysisResult"), false);
      const err = $("#analysisError");
      err.innerHTML = `<strong>Could not analyse ${esc(label)}.</strong>\n${esc(e.message)}\n\n` +
        `Tip: check the symbol, try another data source, or upload a CSV of prices.`;
      show(err, true);
    } finally {
      show($("#analysisLoading"), false);
    }
  }

  function summaryText(rep) {
    const by = Object.fromEntries(rep.signals.map(s => [s.name, s]));
    const parts = [];
    const pc = by["Price vs Cloud"];
    if (pc) parts.push(pc.score > 0 ? "Price is trading above the cloud, so the primary trend is up."
      : pc.score < 0 ? "Price is below the cloud, so the primary trend is down."
      : "Price is inside the cloud, so the trend is undecided.");
    const tk = by["Tenkan vs Kijun"];
    if (tk) {
      const cross = (tk.detail.match(/(bullish|bearish) TK cross on ([\d-]+)/) || []);
      parts.push(cross.length ? `A ${cross[1]} Tenkan/Kijun cross happened on ${cross[2]}.`
        : tk.score > 0 ? "Short-term momentum (Tenkan) is above the base line." : tk.score < 0 ? "Short-term momentum (Tenkan) is below the base line." : "");
    }
    const fc = by["Future Cloud"];
    if (fc) parts.push(fc.score > 0 ? "The projected cloud is green, supporting the outlook." : fc.score < 0 ? "The projected cloud is red, a headwind ahead." : "");
    const agree = rep.signals.filter(s => Math.sign(s.score) === Math.sign(rep.score) && s.score !== 0).length;
    if (rep.score !== 0) parts.push(`${agree} of 5 rules agree.`);
    return parts.filter(Boolean).join(" ");
  }

  function renderResult() {
    const p = state.payload, r = p.report;
    $("#rSymbol").textContent = p.symbol;
    $("#rName").textContent = p.name || "";
    $("#rClose").innerHTML = `${fmt(r.close)}<small>SAR</small>`;
    const ch = $("#rChange");
    ch.textContent = r.change_pct === null ? "" : `${arrow(r.change_pct)} ${fmtPct(r.change_pct)} on the day`;
    ch.className = `delta ${r.change_pct > 0 ? "up" : r.change_pct < 0 ? "down" : "muted"}`;
    $("#rMeta").innerHTML = `As of ${esc(r.date)} · ${p.bars} sessions · <span class="source-badge">${esc(p.source)}</span>`;

    const t = tone(r.score);
    const v = $("#rVerdict");
    v.className = `verdict ${t}`;
    v.innerHTML = `<span aria-hidden="true">${arrow(r.score)}</span>${esc(r.verdict)}`;
    $("#rScore").textContent = `${r.score > 0 ? "+" : ""}${r.score}`;
    const fill = $("#rMeterFill");
    const w = Math.abs(r.score) / 5 * 50;
    fill.style.left = r.score >= 0 ? "50%" : `${50 - w}%`;
    fill.style.width = `${w}%`;
    fill.style.background = r.score > 0 ? css("--bull") : r.score < 0 ? css("--bear") : css("--axis");
    $("#rSummary").textContent = summaryText(r);

    $("#sTenkan").innerHTML = fmt(r.tenkan);
    $("#sKijun").innerHTML = fmt(r.kijun);
    $("#sCloud").innerHTML = `${fmt(r.cloud_bottom)} <small>to</small> ${fmt(r.cloud_top)}`;
    $("#s52").innerHTML = `${fmt(r.low_52w)} <small>to</small> ${fmt(r.high_52w)}`;

    $("#rSignals").innerHTML = r.signals.map(s => {
      const k = tone(s.score);
      const label = k === "bull" ? "Bullish" : k === "bear" ? "Bearish" : "Neutral";
      return `<li><span class="sig-icon ${k}" aria-hidden="true">${arrow(s.score)}</span>
        <div><div class="sig-name">${esc(s.name)} <span class="muted">· ${esc(s.value)}</span></div>
        <div class="sig-detail">${esc(s.detail)}</div></div>
        <span class="sig-tag ${k}">${label}</span></li>`;
    }).join("");

    const crosses = p.crosses.slice(-8).reverse();
    $("#crossTable tbody").innerHTML = crosses.map(c =>
      `<tr><td>${esc(c.date)}</td><td><span class="pill ${c.type === "bullish" ? "bull" : "bear"}">${c.type === "bullish" ? "▲ Bullish" : "▼ Bearish"}</span></td><td class="num">${fmt(c.price)}</td></tr>`).join("");
    show($("#crossTable"), crosses.length > 0);
    show($("#crossEmpty"), crosses.length === 0);

    const s = p.series, rows = [];
    const lastIdx = s.dates.indexOf(s.last_actual);
    for (let i = lastIdx; i >= Math.max(0, lastIdx - 29); i--) {
      rows.push(`<tr><td>${s.dates[i]}</td><td class="num">${fmt(s.open[i])}</td><td class="num">${fmt(s.high[i])}</td>
        <td class="num">${fmt(s.low[i])}</td><td class="num">${fmt(s.close[i])}</td><td class="num">${fmtInt(s.volume[i])}</td>
        <td class="num">${fmt(s.tenkan[i])}</td><td class="num">${fmt(s.kijun[i])}</td><td class="num">${fmt(s.senkou_a[i])}</td><td class="num">${fmt(s.senkou_b[i])}</td></tr>`);
    }
    $("#dataTable tbody").innerHTML = rows.join("");
    renderChart();
  }

  function visibleWindow() {
    const s = state.payload.series;
    const n = s.dates.length;
    const lastIdx = s.dates.indexOf(s.last_actual);
    const start = state.range ? Math.max(0, lastIdx - state.range + 1) : 0;
    return [start, n - 1];
  }

  function yRange(s, a, b) {
    let lo = Infinity, hi = -Infinity;
    for (let i = a; i <= b; i++) {
      for (const k of ["low", "high", "senkou_a", "senkou_b", "tenkan", "kijun", "chikou"]) {
        const v = s[k][i];
        if (v !== null && v !== undefined) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
      }
    }
    const pad = (hi - lo) * 0.05 || 1;
    return [lo - pad, hi + pad];
  }

  function renderChart() {
    const s = state.payload.series;
    const x = s.dates;
    const c = {
      ink: css("--ink"), ink2: css("--ink-2"), muted: css("--muted"), grid: css("--grid"), axis: css("--axis"),
      surface: css("--surface"), tenkan: css("--tenkan"), kijun: css("--kijun"), chikou: css("--chikou"),
      bull: css("--bull"), bear: css("--bear"),
    };
    const A = s.senkou_a, B = s.senkou_b;
    const top = A.map((a, i) => (a === null || B[i] === null) ? null : Math.max(a, B[i]));
    const line = (y, color, width, extra = {}) => ({ x, y, type: "scatter", mode: "lines", line: { color, width }, ...extra });

    const traces = [
      // Cloud: green fill between B and max(A,B); red fill between A and max(A,B)
      line(B, rgba(c.bear, 0.9), 1, { name: "Senkou B", hovertemplate: "%{y:.2f}" }),
      line(top, "rgba(0,0,0,0)", 0, { fill: "tonexty", fillcolor: rgba(c.bull, 0.22), hoverinfo: "skip", showlegend: false }),
      line(A, rgba(c.bull, 0.95), 1, { name: "Senkou A", hovertemplate: "%{y:.2f}" }),
      line(top, "rgba(0,0,0,0)", 0, { fill: "tonexty", fillcolor: rgba(c.bear, 0.20), hoverinfo: "skip", showlegend: false }),
      {
        x, open: s.open.map((o, i) => o ?? s.close[i]), high: s.high, low: s.low, close: s.close,
        type: "candlestick", name: "Price",
        increasing: { line: { color: c.ink, width: 1 }, fillcolor: c.surface },
        decreasing: { line: { color: c.ink2, width: 1 }, fillcolor: c.ink2 },
        whiskerwidth: 0, hoverlabel: { bgcolor: c.surface },
      },
      line(s.tenkan, c.tenkan, 1.75, { name: "Tenkan", hovertemplate: "%{y:.2f}" }),
      line(s.kijun, c.kijun, 2, { name: "Kijun", hovertemplate: "%{y:.2f}" }),
      line(s.chikou, c.chikou, 1.5, { name: "Chikou", line: { color: c.chikou, width: 1.5, dash: "dot" }, hovertemplate: "%{y:.2f}" }),
    ];
    for (const [type, sym, color] of [["bullish", "triangle-up", c.bull], ["bearish", "triangle-down", c.bear]]) {
      const pts = state.payload.crosses.filter(k => k.type === type);
      traces.push({
        x: pts.map(k => k.date), y: pts.map(k => k.price), type: "scatter", mode: "markers",
        name: `${type === "bullish" ? "Bullish" : "Bearish"} TK cross`,
        marker: { symbol: sym, size: 11, color, line: { color: c.surface, width: 2 } },
        hovertemplate: `${type} TK cross %{y:.2f}<extra></extra>`,
      });
    }
    const upDown = s.close.map((v, i) => (i > 0 && v !== null && s.close[i - 1] !== null && v < s.close[i - 1]) ? rgba(c.ink2, 0.45) : rgba(c.ink2, 0.25));
    traces.push({ x, y: s.volume, type: "bar", name: "Volume", yaxis: "y2", marker: { color: upDown }, hovertemplate: "%{y:,.0f}" });

    const [a, b] = visibleWindow();
    const axisFont = { color: c.muted, size: 11 };
    const layout = {
      paper_bgcolor: c.surface, plot_bgcolor: c.surface,
      font: { family: "system-ui, -apple-system, Segoe UI, sans-serif", color: c.ink2, size: 12 },
      margin: { l: 8, r: innerWidth < 640 ? 44 : 56, t: 8, b: 32 }, showlegend: false, dragmode: "pan",
      hovermode: "x unified",
      hoverlabel: { bgcolor: c.surface, bordercolor: c.axis, font: { color: c.ink, size: 12 } },
      xaxis: {
        type: "category", range: [a - 0.5, b + 0.5], rangeslider: { visible: false },
        showgrid: false, linecolor: c.axis, tickfont: axisFont, nticks: innerWidth < 640 ? 4 : 8, tickangle: 0,
        showspikes: true, spikemode: "across", spikecolor: c.axis, spikethickness: 1, spikedash: "solid",
      },
      yaxis: { domain: [0.22, 1], side: "right", gridcolor: c.grid, zeroline: false, tickfont: axisFont, range: yRange(s, a, b), tickformat: ",.2f" },
      yaxis2: { domain: [0, 0.16], side: "right", gridcolor: c.grid, zeroline: false, tickfont: axisFont, tickformat: "~s", rangemode: "tozero" },
      shapes: [{
        type: "line", xref: "x", yref: "paper", x0: s.last_actual, x1: s.last_actual, y0: 0.2, y1: 1,
        line: { color: c.axis, width: 1, dash: "dash" },
      }],
      annotations: [{
        xref: "x", yref: "paper", x: s.last_actual, y: 1, xanchor: "left", yanchor: "top",
        text: " projected cloud →", showarrow: false, font: { color: c.muted, size: 11 },
      }],
    };
    Plotly.react("chart", traces, layout, { responsive: true, displaylogo: false, scrollZoom: true,
      modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d", "toggleSpikelines"] });
  }

  function setRange(n) {
    state.range = n;
    $$("#rangeSeg button").forEach(b => b.setAttribute("aria-pressed", String(Number(b.dataset.range) === n)));
    if (!state.payload) return;
    const [a, b] = visibleWindow();
    Plotly.relayout("chart", { "xaxis.range": [a - 0.5, b + 0.5], "yaxis.range": yRange(state.payload.series, a, b) });
  }

  // ------------------------------------------------------------ market
  async function loadMarket(force = false) {
    if (state.market && !force) return renderMarket();
    show($("#marketError"), false);
    show($("#marketLoading"), true);
    try {
      const data = await getJSON("/api/market");
      state.market = data.rows;
      $("#marketMeta").textContent = `Updated ${data.fetched}`;
      fillDatalist();
      renderMarket();
    } catch (e) {
      $("#marketError").innerHTML = `<strong>Could not load market prices.</strong>\n${esc(e.message)}`;
      show($("#marketError"), true);
    } finally {
      show($("#marketLoading"), false);
    }
  }

  function renderMarket() {
    const rows = state.market || [];
    const q = $("#marketFilter").value.trim().toLowerCase();
    const { key, asc } = state.sort;
    const list = rows.filter(r => !q || String(r.symbol).toLowerCase().includes(q) || String(r.name || "").toLowerCase().includes(q))
      .sort((x, y) => {
        const a = x[key], b = y[key];
        if (a === null || a === undefined) return 1;
        if (b === null || b === undefined) return -1;
        const cmp = typeof a === "number" ? a - b : String(a).localeCompare(String(b));
        return asc ? cmp : -cmp;
      });
    $$("#marketTable th[data-key]").forEach(th => {
      th.classList.toggle("sorted", th.dataset.key === key);
      th.classList.toggle("asc", th.dataset.key === key && asc);
    });
    $("#marketTable tbody").innerHTML = list.map(r => {
      const cls = r.change_pct > 0 ? "up" : r.change_pct < 0 ? "down" : "";
      return `<tr><td><strong>${esc(r.symbol)}</strong></td><td>${esc(r.name)}</td><td class="num">${fmt(r.price)}</td>
        <td class="num ${cls}">${r.change === undefined ? "—" : fmt(r.change)}</td>
        <td class="num ${cls}">${r.change_pct === undefined ? "—" : `${arrow(r.change_pct || 0)} ${fmtPct(r.change_pct)}`}</td>
        <td class="num"><button class="link" data-analyze="${esc(r.symbol)}">Analyze →</button></td></tr>`;
    }).join("") || `<tr><td colspan="6" class="muted">No matches.</td></tr>`;
    const up = rows.filter(r => r.change_pct > 0).length, down = rows.filter(r => r.change_pct < 0).length;
    $("#mCount").textContent = rows.length;
    $("#mUp").textContent = up;
    $("#mDown").textContent = down;
    $("#mFlat").textContent = rows.length - up - down;
    show($("#marketStats"), rows.length > 0);
  }

  function fillDatalist() {
    $("#symbolList").innerHTML = (state.market || []).map(r => `<option value="${esc(r.symbol)}">${esc(r.name)}</option>`).join("");
  }

  // ------------------------------------------------------------ scanner
  function sparkline(values) {
    if (!values || values.length < 2) return "";
    const w = 110, h = 28, lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
    const pts = values.map((v, i) => `${(i / (values.length - 1) * w).toFixed(1)},${(h - 2 - (v - lo) / span * (h - 4)).toFixed(1)}`).join(" ");
    const color = values.at(-1) >= values[0] ? css("--good") : css("--bad");
    return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/></svg>`;
  }

  async function runScan(e) {
    e?.preventDefault();
    show($("#scanError"), false);
    show($("#scanLoading"), true);
    const q = params();
    q.set("symbols", $("#scanSymbols").value);
    q.set("source", $("#sourceSelect").value);
    try {
      const data = await getJSON(`/api/scan?${q}`);
      const ok = data.results.filter(r => !r.error).sort((a, b) => b.score - a.score);
      const bad = data.results.filter(r => r.error);
      const order = ["Price vs Cloud", "Tenkan vs Kijun", "Price vs Kijun", "Future Cloud", "Chikou Span"];
      $("#scanTable tbody").innerHTML = ok.map(r => {
        const t = tone(r.score), w = Math.abs(r.score) / 5 * 50;
        const fillColor = r.score > 0 ? css("--bull") : css("--bear");
        return `<tr><td><button class="link" data-analyze="${esc(r.symbol)}">${esc(r.symbol)}</button></td>
          <td>${esc(r.name || "")}</td><td class="num">${fmt(r.close)}</td>
          <td class="num ${r.change_pct > 0 ? "up" : r.change_pct < 0 ? "down" : ""}">${fmtPct(r.change_pct)}</td>
          <td>${sparkline(r.spark)}</td>
          <td><span class="dots">${order.map(n => `<i class="${tone(r.signals[n])}" title="${n}">${arrow(r.signals[n] ?? 0)}</i>`).join("")}</span></td>
          <td><div class="score-cell"><div class="score-bar"><i style="left:${r.score >= 0 ? 50 : 50 - w}%;width:${w}%;background:${fillColor}"></i></div><strong>${r.score > 0 ? "+" : ""}${r.score}</strong></div></td>
          <td><span class="pill ${t}">${esc(r.verdict)}</span></td></tr>`;
      }).join("") + bad.map(r => `<tr><td><strong>${esc(r.symbol)}</strong></td><td colspan="7" class="muted">Failed: ${esc(r.error)}</td></tr>`).join("");
    } catch (err) {
      $("#scanError").innerHTML = `<strong>Scan failed.</strong>\n${esc(err.message)}`;
      show($("#scanError"), true);
    } finally {
      show($("#scanLoading"), false);
    }
  }

  // ------------------------------------------------------------ wiring
  function init() {
    initTheme();
    $$(".tabs button").forEach(b => b.addEventListener("click", () => switchView(b.dataset.view)));
    $("#searchForm").addEventListener("submit", e => { e.preventDefault(); analyzeSymbol($("#symbolInput").value); });
    $("#csvInput").addEventListener("change", e => { const f = e.target.files[0]; if (f) analyzeCsv(f); e.target.value = ""; });
    $$("#rangeSeg button").forEach(b => b.addEventListener("click", () => setRange(Number(b.dataset.range))));
    $("#quickPicks").innerHTML = POPULAR.map(([s, n]) => `<button class="chip" type="button" data-analyze="${s}"><b>${s}</b>${esc(n)}</button>`).join("");
    document.addEventListener("click", e => {
      const btn = e.target.closest("[data-analyze]");
      if (btn) analyzeSymbol(btn.dataset.analyze);
    });
    $("#marketFilter").addEventListener("input", renderMarket);
    $("#marketRefresh").addEventListener("click", () => loadMarket(true));
    $$("#marketTable th[data-key]").forEach(th => th.addEventListener("click", () => {
      const k = th.dataset.key;
      state.sort = { key: k, asc: state.sort.key === k ? !state.sort.asc : k === "symbol" || k === "name" };
      renderMarket();
    }));
    $("#scanForm").addEventListener("submit", runScan);

    // Deep links: #analysis/2222, #market, #scanner, #guide
    const [view, sym] = location.hash.replace("#", "").split("/");
    if (["market", "scanner", "guide"].includes(view)) switchView(view, false);
    else if (view === "analysis" && sym) analyzeSymbol(decodeURIComponent(sym));
    else if (window.TADAWUL_DEFAULT_SYMBOL) analyzeSymbol(window.TADAWUL_DEFAULT_SYMBOL);

    // Best-effort: load symbol names for autocomplete in the background.
    getJSON("/api/market").then(d => { state.market = d.rows; fillDatalist(); }).catch(() => {});
  }

  document.addEventListener("DOMContentLoaded", init);
})();
