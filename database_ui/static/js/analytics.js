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

  // A "nice" round axis ceiling that clears the data max with one empty step of
  // headroom above the tallest bar (e.g. max 8 → ceiling 10, step 2).
  function niceScale(m) {
    m = Math.max(1, m);
    const pow = Math.pow(10, Math.floor(Math.log10(m)));
    let step = pow;
    for (const s of [1, 2, 5, 10]) {
      step = s * pow;
      if (m / step <= 4) break;
    }
    let ceil = Math.ceil(m / step) * step;
    if (ceil <= m) ceil += step;   // guarantee the empty top layer
    return { ceil, step };
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
    const { ceil, step } = niceScale(max);
    const slot = (w - padX * 2) / n, bw = slot * 0.6;
    const svg = el("svg", { _svg: true, viewBox: `0 0 ${w} ${h}`, class: "chart", role: "img",
      "aria-label": opts.label || "Bar chart" });

    const TICKS = Math.round(ceil / step);
    for (let t = 0; t <= TICKS; t++) {
      const gy = padTop + plotH * (t / TICKS);
      svg.appendChild(el("line", { _svg: true, x1: padX, y1: gy, x2: w - padX, y2: gy, class: "chart-grid" }));
      svg.appendChild(el("text", { _svg: true, x: padX - 6, y: gy + 3, "text-anchor": "end", class: "chart-lbl" },
        [String(Math.round(ceil - step * t))]));
    }

    data.forEach((d, i) => {
      const x = padX + i * slot + (slot - bw) / 2;
      const bh = plotH * (d.value / ceil);
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

  function money(x) { return "$" + (x || 0).toFixed(2); }
  function arrow(wow, key) { return (wow && wow[key] && wow[key].arrow) || ""; }

  function render(payload) {
    const root = $("analytics-content");
    root.textContent = "";
    const s = payload.live, wow = s.week_over_week || {};
    const u = s.usage, co = s.cost;

    root.appendChild(card(null, statList([
      ["Conversations", u.conversations + " " + arrow(wow, "conversations")],
      ["Messages", u.total_messages + " " + arrow(wow, "total_messages")],
      ["Students", u.unique_students + " " + arrow(wow, "unique_students")],
      ["New students", u.new_students + " " + arrow(wow, "new_students")],
      ["Cost", money(co.total_usd) + " " + arrow(wow, "cost_usd")],
    ])));

    const byDay = weekSeries(u.messages_by_day || {}, payload.week.key, "messages");
    root.appendChild(card("Daily activity", barChart(byDay, { label: "Daily message activity, Sunday through Saturday" })));

    // AI review sits under Daily activity: the week's narrative overview, one
    // paragraph per course, scoped on read so a course login sees only its own.
    // Falls back to a pending note before the week's cache has been generated.
    const rBody = el("div");
    if (!payload.cached) {
      rBody.appendChild(el("p", { class: "a-pending" }, ["This week's review is coming soon"]));
    } else {
      const reviews = payload.cached.ai_review_by_course || {};
      const courses = Object.keys(reviews);
      if (courses.length === 0) {
        rBody.appendChild(el("p", { class: "a-muted" }, ["No review available for this week."]));
      } else {
        courses.forEach((course) => {
          if (courses.length > 1) rBody.appendChild(el("p", { class: "a-review-course" }, [course]));
          rBody.appendChild(el("p", { class: "a-review" }, [reviews[course]]));
        });
      }
    }
    root.appendChild(card("AI review", rBody));

    // Flags: judged conversations that didn't work well — internal QA shown only
    // in the master view, never to a course-scoped login (the server also
    // withholds the data). Nothing to show until the week's cache exists.
    if (payload.cached && payload.all_access) {
      const flags = Object.values(payload.cached.conversations || {}).filter((c) => !c.worked_well);
      const flagBody = el("div");
      flagBody.appendChild(el("p", { class: "a-muted" }, [flags.length + " conversations flagged."]));
      flags.forEach((c) => {
        const g = c.grade || null;
        const score = g && typeof g.total_score === "number"
          ? (g.total_score + "/" + (g.max_score || 40)) : "—";
        const overview = (g && g.overview) || c.one_line || "";
        const parts = [c.course, score];
        if (overview) parts.push(overview);
        flagBody.appendChild(el("p", { class: "a-flag" }, [parts.join(" · ")]));
      });
      root.appendChild(card("Flags", flagBody));
    }
  }

  async function load(weekKey) {
    $("analytics-status").textContent = "Loading…";
    const q = weekKey ? ("?week=" + encodeURIComponent(weekKey)) : "";
    const resp = await fetch("/api/analytics" + q);
    const payload = await resp.json();
    render(payload);
    $("analytics-status").textContent = "";
  }

  // ---- Week picker: a trigger that opens a small calendar popover ---------
  const WD = ["S", "M", "T", "W", "T", "F", "S"];
  const MONLONG = ["January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"];

  const dUTC = (y, m, d) => new Date(Date.UTC(y, m, d));
  const keyOf = (dt) => dt.toISOString().slice(0, 10);
  function parseKey(k) { const [y, m, d] = k.split("-").map(Number); return dUTC(y, m - 1, d); }
  const sundayOf = (dt) => new Date(dt.getTime() - dt.getUTCDay() * 86400000);
  function weekLabel(sun) {
    const sat = new Date(sun.getTime() + 6 * 86400000);
    return `${MON[sun.getUTCMonth()]} ${sun.getUTCDate()} — `
      + `${MON[sat.getUTCMonth()]} ${sat.getUTCDate()}, ${sat.getUTCFullYear()}`;
  }

  // Build the calendar popover. `range` = {min, max} week keys (Sundays); weeks
  // outside it are shown disabled. Selecting a week loads it and closes the pop.
  function setupPicker(range, initialKey) {
    const host = $("week-picker"), trigger = $("weekpick-trigger"), label = $("weekpick-label");
    const minKey = range.min, maxKey = range.max;
    let selected = initialKey;
    const sun0 = sundayOf(parseKey(selected));
    let viewY = sun0.getUTCFullYear(), viewM = sun0.getUTCMonth();

    const pop = el("div", { class: "weekpick-pop", role: "dialog", hidden: "" });
    host.appendChild(pop);

    const ix = (y, m) => y * 12 + m;
    const monthIxOf = (k) => { const s = sundayOf(parseKey(k)); return ix(s.getUTCFullYear(), s.getUTCMonth()); };

    const setLabel = () => { label.textContent = weekLabel(sundayOf(parseKey(selected))); };
    // Picking a week updates the highlight and reloads but leaves the popover
    // open; only an outside click (onDoc) closes it.
    function choose(k) { selected = k; setLabel(); renderGrid(); load(k); }

    function renderGrid() {
      pop.textContent = "";
      const head = el("div", { class: "weekpick-head" });
      const prev = el("button", { type: "button", class: "weekpick-nav", "aria-label": "Previous month" }, ["‹"]);
      const next = el("button", { type: "button", class: "weekpick-nav", "aria-label": "Next month" }, ["›"]);
      const cur = ix(viewY, viewM);
      if (cur <= monthIxOf(minKey)) prev.setAttribute("disabled", "");
      if (cur >= monthIxOf(maxKey)) next.setAttribute("disabled", "");
      prev.addEventListener("click", () => { if (--viewM < 0) { viewM = 11; viewY--; } renderGrid(); });
      next.addEventListener("click", () => { if (++viewM > 11) { viewM = 0; viewY++; } renderGrid(); });
      head.appendChild(prev);
      head.appendChild(el("span", { class: "weekpick-month" }, [`${MONLONG[viewM]} ${viewY}`]));
      head.appendChild(next);
      pop.appendChild(head);

      const wd = el("div", { class: "weekpick-wd" });
      WD.forEach((c) => wd.appendChild(el("span", {}, [c])));
      pop.appendChild(wd);

      const lastOfMonth = dUTC(viewY, viewM + 1, 0);
      let sun = sundayOf(dUTC(viewY, viewM, 1));
      while (sun <= lastOfMonth) {
        const wkKey = keyOf(sun);
        const inRange = wkKey >= minKey && wkKey <= maxKey;
        const cls = "weekpick-week" + (wkKey === selected ? " is-selected" : "") + (inRange ? "" : " is-disabled");
        const row = el("div", { class: cls });
        for (let i = 0; i < 7; i++) {
          const day = new Date(sun.getTime() + i * 86400000);
          const off = day.getUTCMonth() !== viewM ? " is-off" : "";
          row.appendChild(el("span", { class: "weekpick-day" + off }, [String(day.getUTCDate())]));
        }
        if (inRange) { const k = wkKey; row.addEventListener("click", () => choose(k)); }
        pop.appendChild(row);
        sun = new Date(sun.getTime() + 7 * 86400000);
      }
    }

    function onDoc(e) { if (!host.contains(e.target)) closePop(); }
    function openPop() {
      renderGrid();
      pop.removeAttribute("hidden");
      trigger.setAttribute("aria-expanded", "true");
      document.addEventListener("mousedown", onDoc);
    }
    function closePop() {
      pop.setAttribute("hidden", "");
      trigger.setAttribute("aria-expanded", "false");
      document.removeEventListener("mousedown", onDoc);
    }
    trigger.addEventListener("click", () => (pop.hasAttribute("hidden") ? openPop() : closePop()));
    setLabel();
  }

  async function initPicker() {
    const resp = await fetch("/api/analytics/weeks");
    const { range } = await resp.json();
    setupPicker(range, range.max);
    load(range.max);
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
