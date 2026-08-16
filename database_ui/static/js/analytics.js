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

  // Minimal, accessible bar chart from [{label, value}]. Direct-labeled bars.
  function barChart(data, opts) {
    opts = opts || {};
    const w = 520, h = 200, pad = 28, n = data.length || 1;
    const max = Math.max(1, ...data.map((d) => d.value));
    const bw = (w - pad * 2) / n * 0.7;
    const svg = el("svg", { _svg: true, viewBox: `0 0 ${w} ${h}`, class: "chart", role: "img" });
    data.forEach((d, i) => {
      const x = pad + (i + 0.15) * ((w - pad * 2) / n);
      const bh = (h - pad * 2) * (d.value / max);
      const y = h - pad - bh;
      svg.appendChild(el("rect", { _svg: true, x, y, width: bw, height: bh, rx: 2, fill: "var(--accent)" }));
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

    const byDay = Object.entries(u.messages_by_day || {}).map(([d, v]) => ({ label: d.slice(5), value: v }));
    if (byDay.length) root.appendChild(card("Messages by day", barChart(byDay)));

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
