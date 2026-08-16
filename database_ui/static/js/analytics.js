// database_ui/static/js/analytics.js
// Renders the weekly report: fetches JSON, draws lightweight inline-SVG charts.
(function () {
  "use strict";
  const SVG = "http://www.w3.org/2000/svg";
  const $ = (id) => document.getElementById(id);

  function el(tag, attrs, kids) {
    const n = attrs && attrs._svg ? document.createElementNS(SVG, tag) : document.createElement(tag);
    for (const k in (attrs || {})) if (k !== "_svg") n.setAttribute(k, attrs[k]);
    (kids || []).forEach((c) => n.appendChild(typeof c === "string" ? document.createTextNode(c) : c));
    return n;
  }

  const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  // Expand a { "YYYY-MM-DD": value } map into the full Sun–Sat week starting at
  // sundayKey, filling absent days with 0 so every week charts the same seven
  // slots. All date math is in UTC (the keys are date-only) to avoid DST drift.
  function weekSeries(byDay, sundayKey, unit) {
    const [y, m, d] = sundayKey.split("-").map(Number);
    const base = Date.UTC(y, m - 1, d);
    return DOW.map((name, i) => {
      const dt = new Date(base + i * 86400000);
      const iso = dt.toISOString().slice(0, 10);
      const value = byDay[iso] || 0;
      return { label: name, value, title: `${name}, ${MON[dt.getUTCMonth()]} ${dt.getUTCDate()} · ${value} ${unit}` };
    });
  }

  // Accessible bar chart from [{label, value, title}]. Faint horizontal
  // gridlines with left-edge value ticks; top-rounded bars (square bottom);
  // each bar carries a native <title> tooltip.
  function barChart(data, opts) {
    opts = opts || {};
    const w = 520, h = 220, padX = 30, padTop = 20, padBot = 26;
    const plotH = h - padTop - padBot, baseY = padTop + plotH;
    const n = data.length || 1;
    const max = Math.max(1, ...data.map((d) => d.value));
    const slot = (w - padX * 2) / n, bw = slot * 0.6;
    const svg = el("svg", { _svg: true, viewBox: `0 0 ${w} ${h}`, class: "chart", role: "img",
      "aria-label": opts.label || "Bar chart" });

    const TICKS = 4;
    for (let t = 0; t <= TICKS; t++) {
      const gy = padTop + plotH * (t / TICKS);
      svg.appendChild(el("line", { _svg: true, x1: padX, y1: gy, x2: w - padX, y2: gy, class: "chart-grid" }));
      svg.appendChild(el("text", { _svg: true, x: padX - 6, y: gy + 3, "text-anchor": "end", class: "chart-lbl" },
        [String(Math.round(max * (1 - t / TICKS)))]));
    }

    data.forEach((d, i) => {
      const x = padX + i * slot + (slot - bw) / 2;
      const bh = plotH * (d.value / max);
      const y = baseY - bh;
      const r = Math.min(4, bw / 2, bh);
      // Path with rounded upper corners only, so bars sit flat on the baseline.
      const path = `M${x},${baseY} L${x},${y + r} Q${x},${y} ${x + r},${y}`
        + ` L${x + bw - r},${y} Q${x + bw},${y} ${x + bw},${y + r} L${x + bw},${baseY} Z`;
      const bar = el("path", { _svg: true, d: path, fill: "var(--accent)" });
      bar.appendChild(el("title", { _svg: true }, [d.title || `${d.label}: ${d.value}`]));
      svg.appendChild(bar);
      svg.appendChild(el("text", { _svg: true, x: x + bw / 2, y: y - 4, "text-anchor": "middle", class: "chart-val" }, [String(d.value)]));
      svg.appendChild(el("text", { _svg: true, x: x + bw / 2, y: h - 8, "text-anchor": "middle", class: "chart-lbl" }, [d.label]));
    });
    return svg;
  }

  function card(title, body) {
    const c = el("div", { class: "a-card" });
    if (title) c.appendChild(el("h2", { class: "a-card-title" }, [title]));
    c.appendChild(body);
    return c;
  }

  function statList(pairs) {
    const ul = el("ul", { class: "a-stats" });
    pairs.forEach(([k, v]) => {
      const li = el("li");
      li.appendChild(el("span", { class: "a-stat-k" }, [k]));
      li.appendChild(el("span", { class: "a-stat-v" }, [String(v)]));
      ul.appendChild(li);
    });
    return ul;
  }

  function pct(x) { return Math.round((x || 0) * 100) + "%"; }
  function money(x) { return "$" + (x || 0).toFixed(2); }
  function arrow(wow, key) { return (wow && wow[key] && wow[key].arrow) || ""; }

  function render(payload) {
    const root = $("analytics-content");
    root.textContent = "";
    const s = payload.live, wow = s.week_over_week || {};
    const u = s.usage, r = s.ratings, co = s.cost, ct = s.content;

    root.appendChild(card(null, statList([
      ["Conversations", u.conversations + " " + arrow(wow, "conversations")],
      ["Students", u.unique_students + " (" + u.new_students + " new)"],
      ["Positive rating", pct(r.positive_rate) + " " + arrow(wow, "positive_rate")],
      ["Cost", money(co.total_usd) + " " + arrow(wow, "cost_usd")],
      ["RAG rate", pct(ct.rag_rate) + " " + arrow(wow, "rag_rate")],
    ])));

    const byDay = weekSeries(u.messages_by_day || {}, payload.week.key, "messages");
    root.appendChild(card("Messages by day", barChart(byDay, { label: "Messages by day, Sunday through Saturday" })));

    // Judged sections (may be pending).
    if (!payload.cached) {
      root.appendChild(card("Judged review", el("p", { class: "a-pending" },
        ["This week's review is coming soon"])));
      return;
    }
    const flags = Object.values(payload.cached.conversations || {}).filter((c) => !c.worked_well);
    const flagBody = el("div");
    flagBody.appendChild(el("p", {}, [flags.length + " conversations flagged."]));
    root.appendChild(card("🚩 Didn't work well", flagBody));

    const topics = payload.cached.topics_by_course || {};
    const tBody = el("div");
    Object.entries(topics).forEach(([course, rows]) => {
      tBody.appendChild(el("p", {}, [course + ": " + rows.slice(0, 8).map((t) => t.topic + " (" + t.count + ")").join(" · ")]));
    });
    root.appendChild(card("🗣 Top topics", tBody));
  }

  async function load(weekKey) {
    $("analytics-status").textContent = "Loading…";
    const q = weekKey ? ("?week=" + encodeURIComponent(weekKey)) : "";
    const resp = await fetch("/api/analytics" + q);
    const payload = await resp.json();
    render(payload);
    $("analytics-status").textContent = "";
  }

  async function initPicker() {
    const resp = await fetch("/api/analytics/weeks");
    const { weeks } = await resp.json();
    const sel = $("week-picker");
    weeks.forEach((w) => sel.appendChild(el("option", { value: w.key }, [w.label])));
    sel.addEventListener("change", () => load(sel.value));
    load(sel.value || (weeks[0] && weeks[0].key));
  }

  // Fetch + build the picker at most once. Safe to call every time the report
  // is opened; a no-op after the first successful init.
  let inited = false;
  async function ensureInit() {
    if (inited || !$("week-picker")) return;
    inited = true;
    await initPicker();
  }

  // Two hosts share this module:
  //  - Standalone /analytics page (main#analytics-root): init on load.
  //  - Dashboard panel (index.html): stays dormant until database.js calls
  //    WeeklyReport.ensureInit() when the "Weekly report" button is clicked.
  window.WeeklyReport = { ensureInit };
  document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("analytics-root")) ensureInit();
  });
})();
